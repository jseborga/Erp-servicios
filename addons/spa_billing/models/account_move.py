# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

INVOICE_KINDS = [
    ('membership', 'Membresía (alta)'),
    ('renewal', 'Renovación'),
    ('single', 'Servicio suelto'),
    ('charges', 'Cargos del mes (invitados, penalidades)'),
]


class AccountMove(models.Model):
    _inherit = 'account.move'

    spa_membership_id = fields.Many2one('spa.membership', string='Membresía', index=True, copy=False)
    spa_invoice_kind = fields.Selection(INVOICE_KINDS, string='Tipo de cobro del spa', copy=False)
    spa_period_applied = fields.Boolean('Período aplicado', copy=False,
                                        help='La membresía ya fue activada o extendida con esta factura.')
    spa_offer_id = fields.Many2one('spa.payment.offer', string='Oferta aplicada', copy=False)

    def _invoice_paid_hook(self):
        res = super()._invoice_paid_hook()
        self._spa_apply_period()
        return res

    def _spa_apply_period(self, partial=False):
        """Activa o extiende la membresía al pagar (o al pagar la primera cuota)."""
        for move in self.filtered(lambda m: m.spa_membership_id and m.spa_invoice_kind in ('membership', 'renewal')
                                  and not m.spa_period_applied and m.state == 'posted'):
            if partial and not (move.spa_offer_id.offer_type == 'installments'
                                and move.amount_residual < move.amount_total):
                continue
            move.spa_period_applied = True
            membership = move.spa_membership_id
            membership.action_activate()
            membership._spa_create_deferral(move)
            self.env['spa.message'].queue('payment_validated', membership.partner_id, {
                'monto': move.currency_id.format(move.amount_total - move.amount_residual),
                'plan': membership.plan_id.name,
                'vence': membership.date_end.strftime('%d/%m/%Y'),
            }, record=membership)
