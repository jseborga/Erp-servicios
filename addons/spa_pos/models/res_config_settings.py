# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_spa_analytic_account_id = fields.Many2one(related='pos_config_id.spa_analytic_account_id', readonly=False)
    pos_spa_member_pricing = fields.Boolean(related='pos_config_id.spa_member_pricing', readonly=False)

    def action_spa_pos_setup(self):
        """Crea el Restaurante y la Cafetería del spa en la compañía actual (si aún no existen)."""
        configs = self.env['pos.config']._spa_setup_company(self.env.company)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if configs else 'warning',
                'message': self.env._('Puntos de venta listos: %s', ', '.join(configs.mapped('name')))
                if configs else self.env._('La compañía debe usar el plan contable boliviano (bo).'),
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }
