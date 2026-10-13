# Part of ERP Servicios Spa. License LGPL-3.
from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('bo', 'res.company')
    def _get_bo_purchase_res_company(self):
        # Base nueva: el plan 'bo' se carga después de instalar los módulos; la validación
        # fiscal de compras se activa junto con el plan (no solo en el gancho de instalación).
        return {self.env.company.id: {'l10n_bo_purchase_check': True}}
