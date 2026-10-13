# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError

from .spa_rental_payment import PAYMENT_METHODS


class SpaRentalDepositWizard(models.TransientModel):
    """Liquidación de la garantía después del evento: devolución o aplicación a daños."""
    _name = 'spa.rental.deposit.wizard'
    _description = 'Devolver o aplicar la garantía'

    rental_id = fields.Many2one('spa.rental', string='Alquiler', required=True)
    currency_id = fields.Many2one(related='rental_id.currency_id')
    deposit_balance = fields.Monetary(related='rental_id.deposit_balance', string='En custodia')
    operation = fields.Selection([
        ('refund', 'Devolver al cliente'),
        ('apply', 'Aplicar a daños o reposiciones'),
    ], string='Operación', required=True, default='refund')
    amount = fields.Monetary('Monto', required=True)
    method = fields.Selection(PAYMENT_METHODS, string='Medio de devolución', default='cash')
    product_id = fields.Many2one('product.product', string='Concepto del cargo', domain=[('type', '=', 'service')])
    description = fields.Char('Detalle de los daños')

    @api.onchange('operation')
    def _onchange_operation(self):
        if self.operation == 'apply' and not self.product_id:
            self.product_id = self.rental_id.company_id._spa_rental_damage_product()

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('spa_base.group_spa_cashier'):
            raise UserError(self.env._('Solo caja devuelve o aplica garantías.'))
        if self.operation == 'refund':
            if not self.method:
                raise UserError(self.env._('Indique el medio de devolución.'))
            self.rental_id._spa_refund_deposit(self.amount, self.method)
        else:
            if not (self.description or '').strip():
                raise UserError(self.env._('Describa los daños o reposiciones que se cobran.'))
            self.rental_id._spa_apply_deposit(self.amount, product=self.product_id or None,
                                              description=self.description.strip())
        return True
