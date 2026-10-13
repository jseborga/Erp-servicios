# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Restaurante y cafetería (POS)',
    'version': '19.0.1.0.0',
    'summary': 'Restaurante con mesas y cafetería en el POS: socio en la comanda, descuentos del plan, '
               'cargo a la cuenta del socio con límite y analítica por área',
    'description': """
Extiende el Punto de Venta de Odoo Community (point_of_sale + pos_restaurant) para el spa:

* Al instalar crea dos puntos de venta por compañía con el plan 'bo': **Restaurante** (plano con
  8 mesas) y **Cafetería** (mostrador), con los métodos de pago Efectivo, QR / Transferencia y
  Cuenta del socio, y una carta de ejemplo editable.
* El cajero identifica al socio (nombre, teléfono o CI) y ve su plan y estado.
* Descuentos del plan: el POS usa la lista de precios del plan asignada al socio vigente.
  El servidor rechaza una lista de precios de socio usada para quien no la tiene.
* Cargo a la cuenta del socio: solo socios activos o en gracia, hasta el límite de crédito del plan.
  El consumo se factura al socio (tipo "Consumo restaurante/cafetería") y puede pagarse desde la
  web del socio o en caja.
* Analítica por área: ventas y facturas del Restaurante y de la Cafetería llevan su área analítica.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['pos_restaurant', 'spa_billing', 'l10n_bo_spa'],
    'data': [
        'security/spa_pos_security.xml',
        'data/spa_pos_data.xml',
        'views/pos_config_views.xml',
        'views/pos_payment_method_views.xml',
        'views/spa_plan_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_pos_menus.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'spa_pos/static/src/app/**/*',
        ],
    },
    'post_init_hook': '_spa_pos_post_init',
    'installable': True,
    'license': 'LGPL-3',
}
