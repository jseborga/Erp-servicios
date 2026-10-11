# Part of ERP Servicios Spa. License LGPL-3.
import logging

from . import models  # noqa: F401

_logger = logging.getLogger(__name__)


def _l10n_bo_spa_post_init(env):
    """Aplica el plan de cuentas del spa cuando el registro termina de cargar.

    * Base nueva (la compañía principal aún no tiene plan contable): la configura
      como boliviana (país Bolivia, moneda BOB) y carga el plan 'bo', que ya
      incluye las cuentas de este módulo.
    * Compañías que ya usan el plan 'bo': recarga el plan para agregar solo lo
      nuevo (cuentas, impuestos, diarios) y configura analítica y categorías.

    Se usa el mismo mecanismo que el módulo account (registry._auto_install_template,
    ejecutado en ir.module.module._register_hook) para no cargar el plan con el
    registro a medio inicializar.
    """
    main = env.company
    fresh_database = not main.chart_template
    previous = getattr(env.registry, '_auto_install_template', None)

    if fresh_database:
        bolivia = env.ref('base.bo')
        bob = env.ref('base.BOB')
        if main.country_id != bolivia:
            main.country_id = bolivia
        if main.currency_id != bob:
            bob.active = True
            main.currency_id = bob

    def _apply_spa_chart(env):
        ChartTemplate = env['account.chart.template']
        if fresh_database:
            # Reemplaza la carga del plan genérico que pudo programar 'account'.
            ChartTemplate.try_loading('bo', env.company)
            return
        if previous:
            previous(env)
        for company in env['res.company'].search([('chart_template', '=', 'bo'), ('parent_id', '=', False)]):
            _logger.info("l10n_bo_spa: agregando el plan del spa a %s", company.name)
            ChartTemplate.with_company(company)._l10n_bo_spa_fix_gross_up_in_place()
            ChartTemplate.try_loading('bo', company, force_create=True)

    env.registry._auto_install_template = _apply_spa_chart
