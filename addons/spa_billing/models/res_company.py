# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    spa_payment_qr = fields.Binary('QR de pago', attachment=True,
                                   help='Imagen del QR de la cuenta bancaria que se muestra al socio para pagar.')
    spa_payment_instructions = fields.Text('Instrucciones de pago',
                                           default='Paga con el QR desde tu app bancaria o por transferencia y envía el comprobante.')
    spa_bank_account_text = fields.Char('Datos para transferencia', help='Banco, número de cuenta y titular.')
    spa_payment_journal_id = fields.Many2one('account.journal', string='Diario para QR y transferencias',
                                             domain="[('type', '=', 'bank'), ('company_id', '=', id)]")
    spa_cash_journal_id = fields.Many2one('account.journal', string='Caja de recepción',
                                          domain="[('type', '=', 'cash'), ('company_id', '=', id)]")
    spa_renewal_days = fields.Integer('Avisar la renovación con (días)', default=5)

    def _spa_sale_taxes(self):
        """IVA 13 % (precio incluido) + IT 3 % de la localización boliviana."""
        self.ensure_one()
        chart = self.env['account.chart.template'].with_company(self)
        taxes = self.env['account.tax']
        for xmlid in ('l10n_bo_iva_13_sale', 'l10n_bo_it_3_sale'):
            taxes |= chart.ref(xmlid, raise_if_not_found=False) or self.env['account.tax']
        return taxes

    def _spa_journal(self, method):
        """Diario según el medio de pago; crea la caja de recepción si no existe."""
        self.ensure_one()
        Journal = self.env['account.journal'].sudo()
        if method == 'cash':
            journal = self.spa_cash_journal_id or Journal.search(
                [('type', '=', 'cash'), ('company_id', '=', self.id)], limit=1)
            if not journal:
                journal = Journal.create({'name': 'Caja recepción', 'code': 'CREC', 'type': 'cash',
                                          'company_id': self.id})
            return journal
        return self.spa_payment_journal_id or Journal.search(
            [('type', '=', 'bank'), ('company_id', '=', self.id)], limit=1)
