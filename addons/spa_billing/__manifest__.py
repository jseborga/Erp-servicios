# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Cobros y mora',
    'version': '19.0.1.0.0',
    'summary': 'Facturación de planes, pagos QR por validar, renovación, mora, cuotas, cargos y devengo diferido',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_booking', 'spa_messaging', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_billing_security.xml',
        'data/spa_billing_data.xml',
        'views/spa_payment_request_views.xml',
        'views/spa_payment_offer_views.xml',
        'views/spa_membership_views.xml',
        'views/spa_booking_views.xml',
        'views/spa_deferral_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_billing_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
