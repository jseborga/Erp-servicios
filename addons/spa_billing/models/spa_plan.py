# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, models

# Reparto ILUSTRATIVO del ingreso de cada plan por área: se edita en la ficha del plan (pestaña Contabilidad).
DEFAULT_PLAN_AREAS = {
    'spa_membership.plan_basic': {'l10n_bo_spa.analytic_area_piscina': 60,
                                  'l10n_bo_spa.analytic_area_sauna_jacuzzi': 40},
    'spa_membership.plan_premium': {'l10n_bo_spa.analytic_area_piscina': 40,
                                    'l10n_bo_spa.analytic_area_sauna_jacuzzi': 30,
                                    'l10n_bo_spa.analytic_area_spa': 30},
    'spa_membership.plan_vip': {'l10n_bo_spa.analytic_area_piscina': 35,
                                'l10n_bo_spa.analytic_area_sauna_jacuzzi': 25,
                                'l10n_bo_spa.analytic_area_spa': 40},
}


class SpaPlan(models.Model):
    """Reparto del ingreso de la membresía por área del negocio (analítica).

    Se aplica a la línea de la factura de los planes mensuales (van directo a ingresos) y a la línea de
    ingreso de cada devengo mensual de los planes prepagados (la factura va a 215100 Ingresos diferidos).
    """
    _name = 'spa.plan'
    _inherit = ['spa.plan', 'analytic.mixin']

    @api.model
    def _spa_set_default_analytic(self):
        """Carga el reparto de ejemplo en los planes entregados que aún no tienen áreas (no pisa cambios)."""
        for plan_xmlid, areas in DEFAULT_PLAN_AREAS.items():
            plan = self.env.ref(plan_xmlid, raise_if_not_found=False)
            if not plan or plan.analytic_distribution:
                continue
            distribution = {}
            for area_xmlid, percent in areas.items():
                area = self.env.ref(area_xmlid, raise_if_not_found=False)
                if area:
                    distribution[str(area.id)] = percent
            if distribution:
                plan.sudo().analytic_distribution = distribution
        return True
