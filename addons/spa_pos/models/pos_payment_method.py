# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    spa_member_account = fields.Boolean(
        'Cuenta del socio (spa)',
        help='Cargo a la cuenta del socio: solo para socios con membresía activa o en gracia y hasta el '
             'límite de crédito de su plan. La orden se factura al socio y la deuda aparece en su web.')

    @api.constrains('spa_member_account', 'journal_id', 'split_transactions')
    def _check_spa_member_account(self):
        for method in self.filtered('spa_member_account'):
            if method.journal_id:
                raise ValidationError(self.env._(
                    'El método "%s" es de cuenta del socio: deje el diario vacío para que el consumo '
                    'quede en la cuenta por cobrar del socio.', method.name))
            if not method.split_transactions:
                raise ValidationError(self.env._(
                    'El método "%s" es de cuenta del socio: active "Identificar cliente" para que el '
                    'cajero tenga que elegir al socio.', method.name))
