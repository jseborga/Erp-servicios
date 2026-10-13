# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - CRM',
    'version': '19.0.1.0.0',
    'summary': 'Fuentes de prospectos, embudos de captación y retención, invitados como prospectos y pases de cortesía',
    'description': """
CRM del spa
===========
* Fuentes de prospectos configurables (``utm.source``) con embudo de destino.
* Embudo de **Captación** (Interesado → Visita de prueba / cortesía → Propuesta → Socio activo).
* Embudo de **Retención** (En riesgo → Recuperado / Ex-socio).
* Cada invitado de un socio se convierte en prospecto referido (sin duplicados por celular o correo).
* Pases de cortesía con código QR, límite mensual por usuario y canje en recepción con control de aforo.
* La activación de una membresía gana el prospecto; la renovación recupera al socio en riesgo.
* Análisis de conversión por fuente.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['crm', 'utm', 'spa_billing', 'spa_access'],
    'data': [
        'security/spa_crm_security.xml',
        'security/ir.model.access.csv',
        'data/spa_crm_data.xml',
        'wizard/spa_courtesy_redeem_views.xml',
        'views/spa_courtesy_pass_views.xml',
        'views/crm_lead_views.xml',
        'views/spa_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_crm_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}
