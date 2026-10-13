# Part of ERP Servicios Spa. License LGPL-3.
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    # El asiento de cierre agrupa las ventas por cuenta e impuestos; se agrega la distribución
    # analítica a la clave para que cada línea de ingreso lleve el área de su punto de venta.
    def _get_sale_key(self, base_line):
        key = super()._get_sale_key(base_line)
        distribution = base_line.get('analytic_distribution')
        key['analytic_distribution'] = tuple(sorted(distribution.items())) if distribution else False
        return key

    def _get_sale_vals(self, key, sale_vals):
        vals = super()._get_sale_vals(key, sale_vals)
        if key.get('analytic_distribution'):
            vals['analytic_distribution'] = dict(key['analytic_distribution'])
        return vals
