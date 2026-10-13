# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.l10n_bo_fiscal_document import DOC_TYPES
from ..tools import siat


class L10nBoQrWizard(models.TransientModel):
    """Lee el texto del QR de una factura (escáner, celular o pegado) y completa los datos
    fiscales del documento de origen (factura de proveedor o comprobante de fondo fijo)."""
    _name = 'l10n_bo.qr.wizard'
    _description = 'Lector de QR de facturas (Bolivia)'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    qr_text = fields.Text(
        string='Texto del QR',
        help='Escanee el QR con un lector (funciona como teclado) o pegue el texto/enlace leído con el celular.')
    doc_type = fields.Selection(DOC_TYPES, string='Tipo de documento', compute='_compute_parsed', store=True, readonly=False)
    nit = fields.Char(string='NIT emisor', compute='_compute_parsed', store=True, readonly=False)
    number = fields.Char(string='Número de factura', compute='_compute_parsed', store=True, readonly=False)
    cuf = fields.Char(string='CUF', compute='_compute_parsed', store=True, readonly=False)
    auth_number = fields.Char(string='N.º de autorización', compute='_compute_parsed', store=True, readonly=False)
    control_code = fields.Char(string='Código de control', compute='_compute_parsed', store=True, readonly=False)
    date = fields.Date(string='Fecha de emisión', compute='_compute_parsed', store=True, readonly=False)
    amount_total = fields.Float(
        string='Importe total', compute='_compute_parsed', store=True, readonly=False, digits='Account',
        help='El QR de las facturas en línea no trae el monto: ingréselo si el documento aún no tiene líneas.')
    message = fields.Text(compute='_compute_parsed', store=True)

    @api.model
    def _action_open(self, record):
        wizard = self.create({'res_model': record._name, 'res_id': record.id})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Leer QR de la factura'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('qr_text')
    def _compute_parsed(self):
        for wizard in self:
            data = siat.parse_invoice_qr(wizard.qr_text) if wizard.qr_text else None
            if not data:
                wizard.update({
                    'doc_type': False, 'nit': False, 'number': False, 'cuf': False, 'auth_number': False,
                    'control_code': False, 'date': False, 'amount_total': 0.0,
                    'message': wizard.qr_text and self.env._(
                        'No se reconoce el formato del QR. Se aceptan el enlace del SIN (…/consulta/QR?nit=…&cuf=…&numero=…) '
                        'y el texto de facturas computarizadas (NIT|número|autorización|fecha|total|…).') or False,
                })
                continue
            notes = []
            if data['source'] == 'siat':
                notes.append(self.env._('Factura en línea: el QR no incluye el monto; ingréselo si hace falta.'))
                if not data.get('cuf_decoded'):
                    notes.append(self.env._('No se pudo leer la fecha desde el CUF: revise que el CUF esté completo.'))
            wizard.update({
                'doc_type': data['doc_type'],
                'nit': data.get('nit'),
                'number': data.get('number'),
                'cuf': data.get('cuf'),
                'auth_number': data.get('auth_number'),
                'control_code': data.get('control_code'),
                'date': data.get('date') or False,
                'amount_total': data.get('amount_total') or 0.0,
                'message': '\n'.join(notes) or False,
            })

    def _get_record(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record or not hasattr(record, '_l10n_bo_apply_qr_data'):
            raise UserError(self.env._('El documento de origen ya no existe.'))
        return record

    def action_apply(self):
        self.ensure_one()
        if not (self.doc_type and self.nit and self.number):
            raise UserError(self.env._('Faltan datos: lea el QR o complete al menos el tipo, NIT y número.'))
        record = self._get_record()
        record.check_access('write')
        record._l10n_bo_apply_qr_data({
            'doc_type': self.doc_type,
            'nit': siat.normalize_nit(self.nit),
            'number': siat.normalize_number(self.number),
            'cuf': siat.normalize_cuf(self.cuf),
            'auth_number': siat.normalize_auth(self.auth_number),
            'control_code': siat.normalize_control_code(self.control_code),
            'date': self.date,
            'amount_total': self.amount_total,
        })
        return {'type': 'ir.actions.act_window_close'}
