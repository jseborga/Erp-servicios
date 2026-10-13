# Part of ERP Servicios Spa. License LGPL-3.
from . import models
from . import wizard


def _l10n_bo_siat_edi_post_init(env):
    """* Las ventas publicadas antes de instalar el módulo no tienen datos SIAT: quedan como
      "No aplica" (no aparecen como pendientes ni en el Libro de Ventas).
    * Crea un "Simulador SIAT" (inactivo para la emisión real) en cada compañía con plan 'bo',
      para capacitación. No cambia la modalidad de la compañía."""
    env.cr.execute("""
        UPDATE account_move
           SET l10n_bo_siat_state = 'not_applicable'
         WHERE state != 'draft'
           AND move_type IN ('out_invoice', 'out_refund')
           AND l10n_bo_siat_state IS NULL
    """)
    for company in env['res.company'].search([('chart_template', '=', 'bo')]):
        env['l10n_bo.siat.provider']._l10n_bo_create_demo(company)

    # Base nueva: el plan 'bo' se carga después de instalar los módulos (registry._auto_install_template,
    # ejecutado en ir.module.module._register_hook). Se encadena la creación del simulador después de esa carga.
    previous = getattr(env.registry, '_auto_install_template', None)
    if previous:
        def _load_chart_then_simulator(env):
            previous(env)
            for company in env['res.company'].search([('chart_template', '=', 'bo')]):
                env['l10n_bo.siat.provider']._l10n_bo_create_demo(company)

        env.registry._auto_install_template = _load_chart_then_simulator
