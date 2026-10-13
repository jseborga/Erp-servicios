# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Bolivia - Fondo fijo (caja chica)',
    'version': '19.0.1.0.0',
    'summary': 'Fondos fijos imprest: comprobantes con foto y QR, rendición con arqueo, '
               'facturas y retenciones al aprobar y una reposición desde el banco.',
    'description': """
Fondo fijo (caja chica) con sistema imprest para Bolivia.

* Fondo: custodio, monto fijo, tope por gasto, cuenta (111210/111220/111230), diario de
  caja propio, área analítica, cuentas permitidas. Apertura: Debe fondo / Haber banco.
* Comprobantes: el custodio registra cada gasto con foto, QR de la factura y datos fiscales
  (mismas reglas y unicidad que las facturas de proveedor). Sin asientos en borrador.
* Rendición: comprobantes + arqueo; el contador aprueba: cada comprobante se registra como
  factura de proveedor (Libro de Compras, IVA crédito fiscal o retenciones) pagada desde el
  fondo, y un asiento de reposición desde el banco devuelve el fondo a su monto fijo.
  Faltantes a cuenta por cobrar al custodio (112210) o faltantes de caja (560700);
  sobrantes a 430410.
* Cambio de monto y cierre del fondo con su asiento.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Accounting/Localizations',
    'countries': ['bo'],
    'depends': ['l10n_bo_purchase', 'hr'],
    'data': [
        'security/l10n_bo_petty_cash_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/l10n_bo_petty_cash_voucher_views.xml',
        'views/l10n_bo_petty_cash_report_views.xml',
        'views/l10n_bo_petty_cash_fund_views.xml',
        'views/l10n_bo_petty_cash_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
