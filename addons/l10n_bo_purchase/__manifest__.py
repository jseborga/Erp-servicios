# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Bolivia - Compras con documento fiscal (SIAT)',
    'version': '19.0.1.0.0',
    'summary': 'Tipo de documento, NIT, CUF/autorización, unicidad, lector QR, '
               'retenciones sin factura y Libro de Compras.',
    'description': """
Compras con y sin factura para Bolivia, sobre l10n_bo y l10n_bo_spa.

* Facturas de proveedor: tipo de documento (en línea con CUF, computarizada con
  dosificación, manual, sin factura), NIT, número, CUF, n.º de autorización, código de
  control y tipo de compra para el Libro de Compras.
* Unicidad bloqueante: empresa + NIT + número + CUF/autorización (índice único parcial y
  mensaje con el documento existente).
* Coherencia al validar: sin factura no lleva IVA crédito fiscal; con factura no lleva
  retenciones; CUF con dígito verificador y NIT/número embebidos (configurable).
* Ayudante de retenciones para compras sin factura (8 %, 15,5 %, 16 %, retenidas o
  asumidas) y gasto no deducible 560500 cuando no hay retención.
* Lector de QR (enlace SIAT y QR de facturas computarizadas).
* Libro de Compras (vista SQL de solo lectura, exportable).

Aprobación de compras por monto: use la doble validación estándar de Compras
(Ajustes > Compras > Aprobación de órdenes, monto mínimo).
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Accounting/Localizations',
    'countries': ['bo'],
    'depends': ['l10n_bo_spa', 'purchase', 'account'],
    'data': [
        'security/l10n_bo_purchase_security.xml',
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/l10n_bo_purchase_book_views.xml',
        'wizard/l10n_bo_qr_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/l10n_bo_purchase_menus.xml',
    ],
    'post_init_hook': '_l10n_bo_purchase_post_init',
    'installable': True,
    'license': 'LGPL-3',
}
