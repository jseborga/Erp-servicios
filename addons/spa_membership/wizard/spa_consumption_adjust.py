# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaConsumptionAdjust(models.TransientModel):
    _name = 'spa.consumption.adjust'
    _description = 'Ajuste manual de saldo'

    membership_id = fields.Many2one('spa.membership', required=True)
    service_id = fields.Many2one('spa.service', required=True,
                                 domain="[('id', 'in', allowed_service_ids)]")
    allowed_service_ids = fields.Many2many('spa.service', compute='_compute_allowed_service_ids')
    qty = fields.Integer('Sesiones a devolver (positivo) o descontar (negativo)', required=True, default=1)
    reason = fields.Char('Motivo', required=True)

    @api.depends('membership_id')
    def _compute_allowed_service_ids(self):
        for wizard in self:
            wizard.allowed_service_ids = wizard.membership_id.plan_id.line_ids.service_id

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('spa_base.group_spa_manager'):
            raise UserError(self.env._('Solo el gerente puede ajustar saldos.'))
        if not self.qty:
            raise UserError(self.env._('Indique una cantidad distinta de cero.'))
        # En el libro, una devolución es un consumo negativo.
        self.membership_id._spa_consume(self.service_id, fields.Datetime.now(), 'manual_adjust',
                                        qty=-self.qty, note=self.reason)
        return {'type': 'ir.actions.act_window_close'}
