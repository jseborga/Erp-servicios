# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Bolivia - Facturación de ventas SIAT',
    'version': '19.0.1.0.0',
    'summary': 'Modalidad de facturación (Portal Web del SIN, proveedor certificado o no habilitada), '
               'datos SIAT de la factura (número, CUF, comprador), anulación, ventas sin factura '
               'y Libro de Ventas.',
    'description': """
Facturación de ventas para Bolivia sobre l10n_bo / l10n_bo_spa / l10n_bo_purchase.

Modalidades por compañía (Ajustes > Contabilidad > Facturación SIAT):

* **Portal Web del SIN** (por defecto): la caja emite la factura en el sistema gratuito
  "Facturación en Línea – Portal Web" del SIN y registra en Odoo el número y el CUF. Odoo
  valida el CUF (dígito verificador, NIT de la compañía y número) con el decodificador de
  l10n_bo_purchase. Al validar la factura queda "Por registrar" con una actividad para caja.
* **Proveedor certificado (API)**: se emite al validar mediante un registro
  ``l10n_bo.siat.provider``. **Solo existe el tipo "Simulador – NO válido ante el SIN"**: genera
  un CUF ficticio con prefijo SIMULADO para capacitación y pruebas. No hay contrato ni conexión
  con un proveedor real; el punto de extensión para uno real es ``_siat_emit_<tipo>``.
* **Aún no habilitada**: las ventas se registran sin datos SIAT y se muestra un aviso permanente.

Además:

* Datos del comprador (tipo y número de documento, complemento, razón social) con valores por
  defecto del contacto y un "consumidor final" configurable (S/N, 0).
* Anulación (motivo de la paramétrica del SIN, plazo configurable) y reversión contable estándar
  (nota de crédito conciliada).
* Venta sin factura: solo usuarios autorizados, motivo obligatorio y monto máximo configurable;
  los impuestos (IVA, IT) se registran igual. Los casos legales deben confirmarse con el contador.
* Libro de Ventas (vista SQL de solo lectura, exportable) y lista de control de ventas sin factura.
* Las facturas creadas por procesos automáticos (membresías, portal, POS, tareas programadas) se
  validan siempre: nunca se bloquean por datos SIAT faltantes.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Accounting/Localizations',
    'countries': ['bo'],
    'depends': ['l10n_bo_purchase', 'account', 'mail'],
    'data': [
        'security/l10n_bo_siat_security.xml',
        'security/ir.model.access.csv',
        'data/l10n_bo_siat_data.xml',
        'views/l10n_bo_siat_provider_views.xml',
        'views/l10n_bo_siat_cancel_reason_views.xml',
        'wizard/l10n_bo_siat_register_wizard_views.xml',
        'wizard/l10n_bo_siat_cancel_wizard_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/l10n_bo_sale_book_views.xml',
        'views/res_config_settings_views.xml',
        'views/l10n_bo_siat_menus.xml',
    ],
    'post_init_hook': '_l10n_bo_siat_edi_post_init',
    'installable': True,
    'license': 'LGPL-3',
}
