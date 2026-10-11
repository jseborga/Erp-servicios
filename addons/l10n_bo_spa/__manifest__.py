# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Bolivia - Plan de cuentas para Spa, Piscina y Restaurante',
    'version': '19.0.1.0.0',
    'summary': 'Extiende l10n_bo con cuentas, retenciones, analítica por área y '
               'categorías de producto para un centro de bienestar con restaurante.',
    'description': """
Plan de cuentas operativo para un centro de bienestar (piscina, sauna, jacuzzi,
masajes, restaurante y cafetería) en Bolivia, construido sobre la localización
oficial l10n_bo, sin reemplazarla.

Incluye cuentas por naturaleza (ingresos por línea de negocio, costos directos,
fondos fijos, ingresos diferidos, inventarios, activos y no deducibles),
retenciones retenidas al proveedor (8 %, 15,5 % y 16 %), grossing-up RC-IVA,
correcciones a impuestos de l10n_bo, plan analítico por área con modelos de
reparto, categorías de producto con cuentas y diarios auxiliares.

Es una propuesta técnica: un contador boliviano debe validar cuentas, tasas de
retención y porcentajes de reparto antes de operar.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Accounting/Localizations/Account Charts',
    'countries': ['bo'],
    'depends': [
        'l10n_bo',
        'analytic',
    ],
    'data': [
        'data/analytic_data.xml',
        'data/product_category_data.xml',
    ],
    'post_init_hook': '_l10n_bo_spa_post_init',
    'installable': True,
    'license': 'LGPL-3',
}
