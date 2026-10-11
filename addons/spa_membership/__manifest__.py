# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Membresías',
    'version': '19.0.1.0.0',
    'summary': 'Planes configurables con derechos, saldos por período, invitados y políticas de cancelación',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_base'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_membership_security.xml',
        'data/spa_membership_data.xml',
        'views/spa_plan_views.xml',
        'views/spa_membership_views.xml',
        'views/spa_guest_views.xml',
        'views/res_partner_views.xml',
        'wizard/spa_consumption_adjust_views.xml',
        'views/spa_membership_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
