# Part of ERP Servicios Spa. License LGPL-3.
"""Capa de mensajería con proveedor intercambiable.

Proveedores:
* ``wa_link`` (por defecto): el sistema prepara el texto y un enlace https://wa.me;
  recepción lo abre y lo envía desde la app normal de WhatsApp. Sin riesgo de bloqueo.
* ``meta_cloud``: WhatsApp Business Platform (API oficial de Meta, Graph API).
  Requiere número aprobado, token y, para mensajes iniciados por la empresa,
  plantillas aprobadas por Meta. NO probado contra la API real en este proyecto.
"""
import logging
import re
from collections import defaultdict
from urllib.parse import quote

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PROVIDERS = [
    ('wa_link', 'Enlace wa.me (envío manual desde la app)'),
    ('meta_cloud', 'API oficial de WhatsApp (Meta Cloud API)'),
]


class SpaMessageTemplate(models.Model):
    _name = 'spa.message.template'
    _description = 'Plantilla de mensaje'
    _order = 'name'

    code = fields.Char('Código', required=True, readonly=True)
    name = fields.Char('Plantilla', required=True, translate=True)
    body = fields.Text('Texto', required=True, translate=True,
                       help='Use {campo} para insertar datos, por ejemplo {nombre}, {plan}, {fecha}, {monto}.')
    active = fields.Boolean('Activa', default=True, help='Si está inactiva, el sistema no genera este mensaje.')
    meta_template_name = fields.Char('Plantilla aprobada en Meta',
                                     help='Nombre de la plantilla aprobada (solo para la API oficial).')

    _code_uniq = models.Constraint('UNIQUE (code)', 'El código de plantilla debe ser único.')

    def _render(self, values):
        self.ensure_one()
        return self.body.format_map(defaultdict(str, values))


class SpaMessage(models.Model):
    _name = 'spa.message'
    _description = 'Mensaje de WhatsApp'
    _order = 'create_date desc, id desc'

    partner_id = fields.Many2one('res.partner', string='Destinatario', required=True, index=True)
    phone = fields.Char('Celular', required=True)
    body = fields.Text('Mensaje', required=True)
    template_id = fields.Many2one('spa.message.template', string='Plantilla')
    provider = fields.Selection(PROVIDERS, required=True, default='wa_link')
    state = fields.Selection([
        ('ready', 'Listo para enviar'),
        ('queued', 'En cola'),
        ('sent', 'Enviado'),
        ('failed', 'Falló'),
        ('cancelled', 'Descartado'),
    ], default='ready', required=True, index=True)
    wa_url = fields.Char('Enlace WhatsApp', compute='_compute_wa_url')
    res_model = fields.Char('Modelo relacionado')
    res_id = fields.Integer('Registro relacionado')
    sent_date = fields.Datetime('Enviado el')
    sent_by_id = fields.Many2one('res.users', string='Enviado por')
    error = fields.Text('Error')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('phone', 'body')
    def _compute_wa_url(self):
        for message in self:
            message.wa_url = 'https://wa.me/%s?text=%s' % (message.phone or '', quote(message.body or ''))

    @api.model
    def _normalize_phone(self, phone):
        """Deja solo dígitos con código de país (Bolivia 591 por defecto)."""
        if not phone:
            return False
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('00'):
            digits = digits[2:]
        country = self.env['ir.config_parameter'].sudo().get_param('spa_messaging.country_code', '591')
        if len(digits) == 8 and digits[0] in '67':
            digits = country + digits
        return digits if len(digits) >= 10 else False

    @api.model
    def _provider(self):
        return self.env['ir.config_parameter'].sudo().get_param('spa_messaging.provider', 'wa_link')

    @api.model
    def queue(self, template_code, partner, values=None, record=None):
        """Genera un mensaje desde una plantilla. Devuelve el mensaje o un recordset vacío."""
        template = self.env['spa.message.template'].sudo().search([('code', '=', template_code)], limit=1)
        if not template or not partner:
            return self.browse()
        phone = self._normalize_phone(partner.phone)
        if not phone:
            _logger.info('spa_messaging: %s sin celular válido; no se genera %s', partner.name, template_code)
            return self.browse()
        values = dict(values or {})
        values.setdefault('nombre', (partner.name or '').split(' ')[0])
        values.setdefault('empresa', self.env.company.name)
        provider = self._provider()
        message = self.sudo().create({
            'partner_id': partner.id,
            'phone': phone,
            'body': template._render(values),
            'template_id': template.id,
            'provider': provider,
            'state': 'ready' if provider == 'wa_link' else 'queued',
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
        })
        if provider != 'wa_link':
            message._send_now()
        return message

    def action_open_whatsapp(self):
        """Abre WhatsApp con el texto listo y marca el mensaje como enviado."""
        self.ensure_one()
        self.write({'state': 'sent', 'sent_date': fields.Datetime.now(), 'sent_by_id': self.env.user.id})
        return {'type': 'ir.actions.act_url', 'url': self.wa_url, 'target': 'new'}

    def action_retry(self):
        self.filtered(lambda m: m.state in ('failed', 'queued'))._send_now()

    def action_discard(self):
        self.write({'state': 'cancelled'})

    def _send_now(self):
        for message in self:
            if message.provider == 'meta_cloud':
                message._send_meta_cloud()
            else:
                message.state = 'ready'

    def _send_meta_cloud(self):
        """Envío por la API oficial (Graph API /messages). Requiere token y Phone Number ID."""
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        token = params.get_param('spa_messaging.meta_token')
        phone_id = params.get_param('spa_messaging.meta_phone_id')
        version = params.get_param('spa_messaging.meta_api_version', 'v20.0')
        if not (token and phone_id):
            self.write({'state': 'failed', 'error': self.env._('Falta configurar el token o el Phone Number ID.')})
            return
        payload = {'messaging_product': 'whatsapp', 'to': self.phone}
        if self.template_id.meta_template_name:
            payload.update({'type': 'template', 'template': {
                'name': self.template_id.meta_template_name, 'language': {'code': 'es'},
                'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': self.body}]}]}})
        else:
            payload.update({'type': 'text', 'text': {'body': self.body}})
        try:
            response = requests.post(f'https://graph.facebook.com/{version}/{phone_id}/messages',
                                     json=payload, headers={'Authorization': f'Bearer {token}'}, timeout=15)
            if response.status_code >= 300:
                self.write({'state': 'failed', 'error': response.text[:1000]})
            else:
                self.write({'state': 'sent', 'sent_date': fields.Datetime.now(), 'error': False})
        except requests.RequestException as error:
            self.write({'state': 'failed', 'error': str(error)[:1000]})

    @api.model
    def _cron_send_queued(self):
        self.search([('state', '=', 'queued')], limit=200)._send_now()
        return True

    def action_open_record(self):
        self.ensure_one()
        if not (self.res_model and self.res_id):
            raise UserError(self.env._('El mensaje no tiene un registro relacionado.'))
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                'view_mode': 'form'}
