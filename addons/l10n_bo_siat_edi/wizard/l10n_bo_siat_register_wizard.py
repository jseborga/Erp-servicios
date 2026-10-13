# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models

from odoo.addons.l10n_bo_purchase.tools import siat

from ..models.l10n_bo_siat_catalog import BUYER_DOC_TYPES

WIZARD_BUYER_FIELDS = {
    'buyer_doc_type': 'l10n_bo_sale_buyer_doc_type',
    'buyer_number': 'l10n_bo_sale_buyer_number',
    'buyer_complement': 'l10n_bo_sale_buyer_complement',
    'buyer_name': 'l10n_bo_sale_buyer_name',
}


class L10nBoSiatRegisterWizard(models.TransientModel):
    """Registro del número y CUF de una factura emitida en el Portal Web del SIN."""
    _name = 'l10n_bo.siat.register.wizard'
    _description = 'Registrar datos SIAT de una factura'

    move_id = fields.Many2one('account.move', string='Factura', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(related='move_id.company_id', string='Compañía')
    currency_id = fields.Many2one(related='move_id.currency_id')
    amount_total = fields.Monetary(related='move_id.amount_total', string='Importe total')
    qr_text = fields.Char(
        string='QR o enlace de la factura',
        help='Opcional: pegue el enlace del QR de la factura del SIN (…/consulta/QR?nit=…&cuf=…&numero=…) o léalo '
             'con un lector; se completan el número y el CUF.')
    siat_number = fields.Char(string='N.º de factura SIAT')
    cuf = fields.Char(string='CUF')
    emission_date = fields.Datetime(
        string='Fecha y hora de emisión', help='Vacío: se toma del CUF (si se puede decodificar) o la hora actual.')
    buyer_doc_type = fields.Selection(BUYER_DOC_TYPES, string='Tipo de documento del comprador')
    buyer_number = fields.Char(string='NIT/CI del comprador')
    buyer_complement = fields.Char(string='Complemento')
    buyer_name = fields.Char(string='Razón social del comprador')
    check_message = fields.Text(string='Verificación', compute='_compute_check_message')

    @api.model
    def _action_open(self, move):
        vals = {'move_id': move.id}
        vals.update({wfield: move[mfield] for wfield, mfield in WIZARD_BUYER_FIELDS.items()})
        wizard = self.create(vals)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar datos SIAT'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.onchange('qr_text')
    def _onchange_qr_text(self):
        data = siat.parse_siat_url_qr(self.qr_text) if self.qr_text else None
        if data:
            self.cuf = data['cuf']
            if data.get('number'):
                self.siat_number = data['number']

    @api.depends('siat_number', 'cuf', 'buyer_number', 'buyer_name', 'buyer_doc_type', 'buyer_complement')
    def _compute_check_message(self):
        for wizard in self:
            move = wizard.move_id
            if not move:
                wizard.check_message = False
                continue
            number = siat.normalize_number(wizard.siat_number)
            cuf = siat.normalize_cuf(wizard.cuf)
            lines = []
            if number or cuf:
                errors, decoded = move._l10n_bo_siat_manual_errors(number, cuf)
                lines += ['✗ %s' % e for e in errors]
                if decoded and not errors:
                    lines.append(self.env._(
                        '✓ CUF válido: NIT %(nit)s, factura n.º %(number)s, emitida el %(date)s.',
                        nit=decoded['nit'], number=decoded['number'],
                        date=decoded['emission'].strftime('%d/%m/%Y %H:%M')))
                elif cuf and not decoded and not errors:
                    lines.append(self.env._('CUF con formato válido (no se pudo decodificar para comparar NIT y número).'))
            buyer_values = {mfield: wizard[wfield] for wfield, mfield in WIZARD_BUYER_FIELDS.items()}
            lines += ['⚠ %s' % e for e in move._l10n_bo_siat_buyer_errors(buyer_values)]
            wizard.check_message = '\n'.join(lines) or False

    def action_confirm(self):
        self.ensure_one()
        buyer_vals = {
            mfield: self[wfield] for wfield, mfield in WIZARD_BUYER_FIELDS.items()
            if (self[wfield] or False) != (self.move_id[mfield] or False)
        }
        self.move_id._l10n_bo_siat_register(
            self.siat_number, self.cuf, emission_date=self.emission_date, buyer_vals=buyer_vals)
        return {'type': 'ir.actions.act_window_close'}
