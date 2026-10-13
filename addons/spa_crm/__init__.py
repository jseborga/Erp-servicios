# Part of ERP Servicios Spa. License LGPL-3.
from . import models
from . import wizard


def post_init_hook(env):
    """Las etapas estándar del CRM (sin equipo) aparecerían en los embudos del spa.

    Se limitan al equipo «Ventas» estándar para que Captación y Retención muestren
    solo sus propias etapas. Solo se tocan las cuatro etapas de datos de ``crm``.
    """
    sales_team = env.ref('sales_team.team_sales_department', raise_if_not_found=False)
    if not sales_team:
        return
    for xmlid in ('crm.stage_lead1', 'crm.stage_lead2', 'crm.stage_lead3', 'crm.stage_lead4'):
        stage = env.ref(xmlid, raise_if_not_found=False)
        if stage and not stage.team_ids:
            stage.team_ids = [(4, sales_team.id)]
