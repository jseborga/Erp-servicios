# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Reservas',
    'version': '19.0.1.0.0',
    'summary': 'Reservas por franja con control de aforo, personal, lista de espera, cancelaciones y no-show',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_membership', 'spa_messaging'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_booking_security.xml',
        'data/spa_booking_data.xml',
        'views/spa_booking_views.xml',
        'views/spa_booking_waitlist_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/spa_booking_slot_views.xml',
        'views/spa_booking_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
