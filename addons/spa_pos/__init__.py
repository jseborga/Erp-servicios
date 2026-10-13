# Part of ERP Servicios Spa. License LGPL-3.
from . import models

# Crédito de ejemplo en restaurante y cafetería para los planes iniciales (editable en cada plan).
DEFAULT_PLAN_CREDIT = {
    'spa_membership.plan_premium': 500.0,
    'spa_membership.plan_vip': 1500.0,
}


def _spa_pos_post_init(env):
    """Crea los puntos de venta del spa en cada compañía con el plan 'bo'.

    En una base nueva el plan contable se carga al final del arranque del registro
    (``registry._auto_install_template``, ver l10n_bo_spa y account). En ese caso la
    configuración del POS se encadena después de la carga del plan.
    """
    for xmlid, credit in DEFAULT_PLAN_CREDIT.items():
        plan = env.ref(xmlid, raise_if_not_found=False)
        if plan and not plan.pos_credit_limit:
            plan.pos_credit_limit = credit

    pending = getattr(env.registry, '_auto_install_template', None)
    if pending:
        def _load_chart_then_pos(env):
            pending(env)
            env['pos.config']._spa_setup_all_companies()

        env.registry._auto_install_template = _load_chart_then_pos
    else:
        env['pos.config']._spa_setup_all_companies()
