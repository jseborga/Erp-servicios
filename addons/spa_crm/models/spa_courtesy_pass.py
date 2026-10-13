# Part of ERP Servicios Spa. License LGPL-3.
import re
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Sin 0/O ni 1/I/L para que se pueda dictar o tipear sin confusiones.
TOKEN_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
TOKEN_LENGTH = 10


def _new_token():
    return ''.join(secrets.choice(TOKEN_ALPHABET) for _index in range(TOKEN_LENGTH))


class SpaCourtesyPass(models.Model):
    _name = 'spa.courtesy.pass'
    _description = 'Pase de cortesía'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'issue_date desc, id desc'
    _check_company_auto = True

    name = fields.Char('Número', readonly=True, copy=False, default='/')
    guest_name = fields.Char('Invitado', required=True, tracking=True)
    phone = fields.Char('Celular', tracking=True)
    email = fields.Char('Correo')
    partner_id = fields.Many2one('res.partner', string='Contacto', tracking=True, index=True,
                                 help='Se crea automáticamente con el nombre, celular y correo si no se elige.')
    referrer_partner_id = fields.Many2one('res.partner', string='Solicitado por (socio)',
                                          help='Socio que pidió la cortesía para esta persona (cuenta como referido).')
    service_ids = fields.Many2many('spa.service', string='Servicios incluidos', required=True, check_company=True)
    valid_from = fields.Date('Válido desde', required=True, tracking=True,
                             default=lambda self: self.env['spa.tools'].local_today())
    valid_to = fields.Date('Válido hasta', required=True, tracking=True, default=lambda self: self._default_valid_to())
    visits = fields.Integer('Visitas incluidas', required=True, default=1, tracking=True)
    visits_used = fields.Integer('Visitas usadas', compute='_compute_visits', store=True)
    visits_left = fields.Integer('Visitas disponibles', compute='_compute_visits', store=True)
    token = fields.Char('Código', readonly=True, copy=False, index=True, default=lambda self: _new_token(),
                        help='Código que se muestra en recepción y que va dentro del QR.')
    qr_url = fields.Char('QR', compute='_compute_qr_url')
    issue_date = fields.Date('Emitido el', readonly=True, copy=False,
                             default=lambda self: self.env['spa.tools'].local_today())
    issued_by_id = fields.Many2one('res.users', string='Emitido por', readonly=True, copy=False,
                                   default=lambda self: self.env.user)
    source_id = fields.Many2one('utm.source', string='Fuente',
                                default=lambda self: self.env['crm.lead']._spa_source('courtesy'),
                                help='Origen del prospecto (por defecto «Cortesía»). Útil si la cortesía es de un '
                                     'sorteo en Instagram, un evento, etc.')
    reason = fields.Char('Motivo / campaña')
    lead_id = fields.Many2one('crm.lead', string='Prospecto', readonly=True, copy=False, index='btree_not_null',
                              groups='sales_team.group_sale_salesman')
    access_log_ids = fields.One2many('spa.access.log', 'courtesy_pass_id', string='Ingresos')
    spa_message_id = fields.Many2one('spa.message', string='Mensaje de WhatsApp', readonly=True, copy=False)
    spa_message_state = fields.Selection(related='spa_message_id.state', string='WhatsApp')
    state = fields.Selection([
        ('issued', 'Emitido'),
        ('redeemed', 'Canjeado'),
        ('expired', 'Vencido'),
        ('cancelled', 'Anulado'),
    ], string='Estado', default='issued', required=True, tracking=True, index=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    note = fields.Text('Notas internas')

    _token_uniq = models.Constraint('UNIQUE (token)', 'El código del pase de cortesía debe ser único.')
    _visits_positive = models.Constraint('CHECK (visits > 0)', 'El pase debe incluir al menos una visita.')

    @api.model
    def _default_valid_to(self):
        days = self._spa_param_int('spa_crm.courtesy_validity_days') or 15
        return self.env['spa.tools'].local_today() + timedelta(days=days)

    @api.model
    def _spa_param_int(self, key, default=0):
        value = self.env['ir.config_parameter'].sudo().get_param(key, default)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    @api.depends('visits', 'access_log_ids')
    def _compute_visits(self):
        for courtesy in self:
            courtesy.visits_used = len(courtesy.access_log_ids)
            courtesy.visits_left = max(courtesy.visits - courtesy.visits_used, 0)

    @api.depends('token')
    def _compute_qr_url(self):
        for courtesy in self:
            courtesy.qr_url = f'/report/barcode/QR/{courtesy.token}?width=240&height=240' if courtesy.token else False

    def _compute_display_name(self):
        for courtesy in self:
            # Sin el «/» provisional de un pase aún no guardado.
            parts = (courtesy.name if courtesy.name != '/' else '', courtesy.guest_name)
            courtesy.display_name = ' · '.join(part for part in parts if part)

    @api.constrains('valid_from', 'valid_to')
    def _check_dates(self):
        for courtesy in self:
            if courtesy.valid_to < courtesy.valid_from:
                raise ValidationError(self.env._('La fecha «Válido hasta» no puede ser anterior a «Válido desde».'))

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.guest_name = self.partner_id.name
            self.phone = self.partner_id.phone or self.phone
            self.email = self.partner_id.email or self.email

    # ------------------------------------------------------------------
    # Emisión
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        self._spa_check_issue_limit(len(vals_list))
        today = self.env['spa.tools'].local_today()
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('spa.courtesy.pass') or '/'
            if not self.env.su:
                # Quién emite y cuándo no se eligen: cuentan para el límite mensual.
                vals.update(issued_by_id=self.env.user.id, issue_date=today)
        passes = super().create(vals_list)
        for courtesy in passes:
            if not (courtesy.phone or courtesy.email or courtesy.partner_id):
                raise UserError(self.env._('Indique el celular o el correo de %s para enviarle el pase.',
                                           courtesy.guest_name))
            courtesy._spa_after_issue()
        return passes

    @api.model
    def _spa_check_issue_limit(self, count=1):
        """Límite mensual de pases por usuario (0 = sin límite). Los gerentes no tienen límite."""
        limit = self._spa_param_int('spa_crm.courtesy_monthly_limit')
        user = self.env.user
        if not limit or self.env.su or user.has_group('spa_base.group_spa_manager'):
            return True
        tools = self.env['spa.tools']
        start, end = tools.month_bounds(tools.local_today())
        used = self.sudo().search_count([
            ('issued_by_id', '=', user.id), ('state', '!=', 'cancelled'),
            ('issue_date', '>=', start), ('issue_date', '<=', end),
        ])
        if used + count > limit:
            raise UserError(self.env._(
                'Alcanzó el límite de %(limit)s pases de cortesía por mes (ya emitió %(used)s). '
                'Pida a un gerente que emita el pase o que amplíe el límite en Spa › Configuración › Ajustes.',
                limit=limit, used=used))
        return True

    def _spa_ensure_partner(self):
        Partner = self.env['res.partner'].sudo()
        for courtesy in self:
            partner = courtesy.partner_id.sudo()
            if not partner and courtesy.phone:
                # Mismo celular escrito distinto («70000101» y «+591 70000101»): últimos 8 dígitos.
                partner = Partner._spa_find_by_phone(courtesy.phone)
            if not partner and courtesy.email:
                partner = Partner.search([('email', '=ilike', courtesy.email)], limit=1)
            if not partner:
                partner = Partner.create({'name': courtesy.guest_name, 'phone': courtesy.phone,
                                          'email': courtesy.email})
            else:
                missing = {}
                if courtesy.phone and not partner.phone:
                    missing['phone'] = courtesy.phone
                if courtesy.email and not partner.email:
                    missing['email'] = courtesy.email
                if missing:
                    partner.write(missing)
            if courtesy.partner_id != partner:
                courtesy.partner_id = partner
        return True

    def _spa_after_issue(self):
        """Contacto, prospecto en «Visita de prueba / cortesía» y mensaje de WhatsApp."""
        self.ensure_one()
        self._spa_ensure_partner()
        partner = self.partner_id.sudo()
        if not partner._spa_has_live_membership():
            lead = self.env['crm.lead']._spa_upsert_acquisition(
                partner, self.company_id, source=self.source_id, stage_code='visit',
                name=self.env._('Cortesía: %s', self.guest_name), referred_by=self.referrer_partner_id or None,
                phone=self.phone, email=self.email, lead=self.sudo().lead_id,
                note=self.env._('Pase de cortesía %(name)s emitido por %(user)s, válido hasta el %(date)s.',
                                name=self.name, user=self.issued_by_id.name,
                                date=self.valid_to.strftime('%d/%m/%Y')))
            if lead:
                self.sudo().lead_id = lead
        self._spa_send_pass()
        return True

    def _spa_message_values(self):
        self.ensure_one()
        base_url = self.get_base_url()
        return {
            'nombre': (self.guest_name or '').split(' ')[0],
            'vence': self.valid_to.strftime('%d/%m/%Y'),
            'desde': self.valid_from.strftime('%d/%m/%Y'),
            'servicios': ', '.join(self.service_ids.mapped('name')),
            'codigo': self.token,
            'visitas': self.visits,
            'qr': f'{base_url}{self.qr_url}' if self.qr_url else '',
        }

    def _spa_send_pass(self):
        """Genera el WhatsApp con el código del pase (plantilla ``courtesy_pass``)."""
        for courtesy in self:
            message = self.env['spa.message'].queue('courtesy_pass', courtesy.partner_id,
                                                     courtesy._spa_message_values(), record=courtesy)
            if message:
                courtesy.spa_message_id = message
            else:
                courtesy.message_post(body=self.env._(
                    'No se generó el WhatsApp: revise que el celular sea válido y que la plantilla '
                    '«Pase de cortesía» esté activa.'))
        return True

    def action_send_whatsapp(self):
        """Abre el WhatsApp pendiente del pase; si ya se envió (o falló) genera uno nuevo."""
        self.ensure_one()
        if self.state != 'issued':
            raise UserError(self.env._('Solo se envían pases vigentes.'))
        message = self.spa_message_id
        if not message or message.state in ('sent', 'failed', 'cancelled'):
            self._spa_send_pass()
            message = self.spa_message_id if self.spa_message_id != message else self.env['spa.message']
        if not message:
            raise UserError(self.env._('No se pudo generar el WhatsApp: revise que el celular sea válido y que la '
                                       'plantilla «Pase de cortesía» esté activa.'))
        if message.provider == 'wa_link':
            return message.action_open_whatsapp()
        return True

    def action_cancel(self):
        for courtesy in self:
            if courtesy.state == 'redeemed' or courtesy.access_log_ids:
                raise UserError(self.env._('El pase %s ya se usó: no se puede anular.', courtesy.name))
        self.write({'state': 'cancelled'})
        return True

    def action_open_redeem(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Canjear pase de cortesía'),
            'res_model': 'spa.courtesy.redeem.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_pass_id': self.id},
        }

    # ------------------------------------------------------------------
    # Canje en recepción
    # ------------------------------------------------------------------
    @api.model
    def _clean_token(self, token):
        return re.sub(r'[\s-]', '', token or '').upper()

    @api.model
    def _find_by_token(self, token):
        clean = self._clean_token(token)
        if not clean:
            return self.browse()
        return self.search([('token', '=', clean)], limit=1)

    def _redeem(self, space, service=None, method='manual'):
        """Valida el pase y registra el ingreso (``spa.access.log``). Devuelve el ingreso."""
        self.ensure_one()
        tools = self.env['spa.tools']
        today = tools.local_today()
        now = fields.Datetime.now()
        if self.state == 'cancelled':
            raise UserError(self.env._('El pase %s fue anulado.', self.name))
        if self.state == 'redeemed' or self.visits_left < 1:
            raise UserError(self.env._('El pase %(name)s ya se usó (%(used)s de %(visits)s visitas).',
                                       name=self.name, used=self.visits_used, visits=self.visits))
        if self.state == 'expired' or today > self.valid_to:
            raise UserError(self.env._('El pase %(name)s venció el %(date)s.', name=self.name,
                                       date=self.valid_to.strftime('%d/%m/%Y')))
        if today < self.valid_from:
            raise UserError(self.env._('El pase %(name)s es válido desde el %(date)s.', name=self.name,
                                       date=self.valid_from.strftime('%d/%m/%Y')))
        if space.company_id != self.company_id:
            raise UserError(self.env._('El pase %s es de otra empresa.', self.name))
        allowed = self.service_ids.filtered(lambda s: s.space_id == space)
        if service:
            if service not in allowed:
                raise UserError(self.env._('El pase %(name)s no incluye %(service)s. Incluye: %(services)s.',
                                           name=self.name, service=service.name,
                                           services=', '.join(self.service_ids.mapped('name'))))
        else:
            service = allowed[:1]
        if not service:
            raise UserError(self.env._('El pase %(name)s no incluye %(space)s. Incluye: %(services)s.',
                                       name=self.name, space=space.name,
                                       services=', '.join(self.service_ids.mapped('name'))))
        # Estado, horario de atención, días y cierres programados del espacio.
        space._check_open_now(now)
        self._spa_ensure_partner()
        person = self.partner_id
        Log = self.env['spa.access.log']
        if Log.search_count([('partner_id', '=', person.id), ('space_id', '=', space.id), ('state', '=', 'open')]):
            raise UserError(self.env._('%(name)s ya está dentro de %(space)s.', name=person.name, space=space.name))

        # Aforo: misma serialización que el check-in de socios.
        space._lock_for_booking()
        space.invalidate_recordset(['occupancy', 'free_now', 'occupancy_percent'])
        if space.access_mode == 'free':
            taken = space.occupancy
        else:
            # Reservas + personas dentro sin reserva (spa_access extiende _seats_taken).
            stop = now + timedelta(hours=service.duration)
            taken = space._seats_taken(now, stop)
        if taken + 1 > space.capacity:
            raise UserError(self.env._('%(space)s está lleno (%(n)s de %(cap)s). Espere a que se libere un cupo.',
                                       space=space.name, n=taken, cap=space.capacity))

        log = Log.create({
            'partner_id': person.id,
            'space_id': space.id,
            'service_id': service.id,
            'people': 1,
            'method': method,
            'courtesy_ref': self.name,
            'courtesy_pass_id': self.id,
        })
        if self.visits_left <= 0:
            self.state = 'redeemed'
        self.message_post(body=self.env._('Canjeado en %(space)s (%(used)s de %(visits)s visitas).',
                                          space=space.name, used=self.visits_used, visits=self.visits))
        lead = self.sudo().lead_id
        if lead:
            lead.message_post(body=self.env._('Usó su pase de cortesía %(name)s en %(space)s.',
                                              name=self.name, space=space.name))
            days = self._spa_param_int('spa_crm.followup_days')
            if days:
                lead._spa_schedule_activity(self.env._('Seguimiento de la visita de cortesía'),
                                            deadline=today + timedelta(days=days))
        return log

    @api.model
    def _cron_expire_passes(self):
        today = self.env['spa.tools'].local_today()
        self.sudo().search([('state', '=', 'issued'), ('valid_to', '<', today)]).write({'state': 'expired'})
        return True
