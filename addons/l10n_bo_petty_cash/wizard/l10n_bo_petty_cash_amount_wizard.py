# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class L10nBoPettyCashAmountWizard(models.TransientModel):
    _name = 'l10n_bo.petty.cash.amount.wizard'
    _description = 'Cambiar monto de fondo fijo'

    fund_id = fields.Many2one('l10n_bo.petty.cash.fund', string='Fondo fijo', required=True)
    currency_id = fields.Many2one(related='fund_id.currency_id')
    current_amount = fields.Monetary(related='fund_id.amount_fixed', string='Monto actual')
    new_amount = fields.Monetary(string='Nuevo monto fijo', required=True)
    date = fields.Date(string='Fecha del asiento', required=True, default=fields.Date.context_today)
    reason = fields.Char(string='Motivo')

    def action_apply(self):
        self.ensure_one()
        self.fund_id._change_amount(self.new_amount, date=self.date, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
