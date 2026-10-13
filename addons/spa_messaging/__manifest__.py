# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Mensajería (WhatsApp)',
    'version': '19.0.1.0.0',
    'summary': 'Plantillas y cola de mensajes con proveedor intercambiable: enlace wa.me, API oficial de Meta',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_base'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_messaging_security.xml',
        'data/spa_message_template_data.xml',
        'data/spa_messaging_data.xml',
        'views/spa_message_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
