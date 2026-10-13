# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'ERP Servicios Spa – instalación completa',
    'version': '19.0.1.0.0',
    'summary': 'Instala todos los módulos del spa (operación, web, CRM, POS, compras, fondo fijo y reportes '
               'contables OCA) y contiene las pruebas de punta a punta de «un mes de negocio».',
    'description': """
ERP Servicios Spa – instalación completa
========================================

Módulo «paraguas» sin menús ni datos propios. Al instalarlo se instalan juntos:

* Contabilidad Bolivia: ``l10n_bo_spa`` (plan de cuentas, retenciones, analítica por área),
  ``l10n_bo_purchase`` (compras con CUF / dosificación, unicidad, Libro de Compras),
  ``l10n_bo_petty_cash`` (fondo fijo imprest).
* Operación del spa: ``spa_base``, ``spa_membership``, ``spa_booking``, ``spa_access``,
  ``spa_messaging``, ``spa_billing``.
* Cara al cliente y ventas: ``spa_portal`` (web del socio), ``spa_crm`` (captación y retención),
  ``spa_pos`` (restaurante y cafetería).
* Reportes contables OCA: ``account_financial_report``, ``account_tax_balance``, ``mis_builder``,
  ``account_asset_management``, ``account_fiscal_year``.

Pruebas de punta a punta (``--test-tags /spa_all`` o la etiqueta ``spa_e2e``): un mes de negocio
con usuarios reales por rol (recepción, caja, terapeuta, marketing, gerente, comprador, contador,
custodio de fondo fijo, mesero del POS y socios del portal) y fechas fijas (marzo-abril de 2027,
hora de La Paz).
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': [
        'l10n_bo_spa',
        'spa_base',
        'spa_membership',
        'spa_booking',
        'spa_access',
        'spa_messaging',
        'spa_billing',
        'spa_portal',
        'spa_crm',
        'spa_pos',
        'l10n_bo_purchase',
        'l10n_bo_petty_cash',
        'account_financial_report',
        'account_tax_balance',
        'mis_builder',
        'account_asset_management',
        'account_fiscal_year',
    ],
    'data': [],
    'application': False,
    'auto_install': False,
    'installable': True,
    'license': 'LGPL-3',
}
