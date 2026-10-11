# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Control de acceso',
    'version': '19.0.1.0.0',
    'summary': 'Check-in y check-out con credencial QR, aforo en vivo de espacios libres',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_booking'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_access_security.xml',
        'data/spa_access_data.xml',
        'wizard/spa_checkin_views.xml',
        'views/spa_access_views.xml',
        'views/spa_access_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
