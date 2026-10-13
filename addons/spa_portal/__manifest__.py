# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Web del socio',
    'version': '19.0.1.0.0',
    'summary': 'Planes en la web, alta en línea, credencial QR, saldos, reservas, invitados y pago con comprobante',
    'description': """
Web pública de planes (/spa) y portal del socio (/my/spa): suscripción en línea,
credencial QR, saldos del mes, reservas por franja con invitados, cancelaciones
según la política del plan, registro de invitados y pago con QR o transferencia
subiendo el comprobante (queda «por validar» en caja).
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['website', 'portal', 'auth_signup', 'spa_access', 'spa_billing'],
    'data': [
        'data/spa_portal_data.xml',
        'views/res_config_settings_views.xml',
        'views/spa_portal_templates.xml',
        'views/spa_website_templates.xml',
        'views/spa_member_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'spa_portal/static/src/scss/spa_portal.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
