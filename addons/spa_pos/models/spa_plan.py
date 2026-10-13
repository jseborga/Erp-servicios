# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaPlan(models.Model):
    _inherit = 'spa.plan'

    pos_credit_limit = fields.Monetary(
        'Crédito en restaurante y cafetería', default=0.0, tracking=True,
        help='Monto máximo que el socio puede cargar a su cuenta en el POS (facturas de consumo pendientes '
             'incluidas). 0 = no se permite cargar consumos a la cuenta.')

    @api.constrains('pos_credit_limit')
    def _check_pos_credit_limit(self):
        for plan in self:
            if plan.pos_credit_limit < 0:
                raise ValidationError(self.env._('El crédito en restaurante y cafetería no puede ser negativo.'))

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._spa_sync_pos_pricelists()
        return plans

    def write(self, vals):
        res = super().write(vals)
        if {'pricelist_id', 'company_id', 'active'} & set(vals):
            self._spa_sync_pos_pricelists()
        return res

    def _spa_sync_pos_pricelists(self):
        plans = self.filtered('pricelist_id')
        if plans:
            self.env['pos.config'].sudo().search([
                ('company_id', 'in', plans.company_id.ids), ('spa_member_pricing', '=', True),
            ])._spa_sync_member_pricelists()
