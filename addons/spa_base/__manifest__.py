# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Base',
    'version': '19.0.1.0.0',
    'summary': 'Espacios, servicios, especialidades del personal y roles del spa',
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['mail', 'hr', 'resource', 'product', 'l10n_bo_spa'],
    'data': [
        'security/spa_security.xml',
        'security/ir.model.access.csv',
        'views/spa_space_views.xml',
        'views/spa_service_views.xml',
        'views/spa_skill_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_menus.xml',
        'data/spa_base_data.xml',
    ],
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}
