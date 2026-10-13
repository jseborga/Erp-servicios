# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

from .l10n_bo_fiscal_document import DOC_TYPES, PURCHASE_TYPES

# Impuesto por defecto para cada (tratamiento, tipo de compra) en compras sin factura.
WITHHOLDING_TAX_XMLIDS = {
    ('supplier_bears', 'goods'): 'l10n_bo_spa_ret_goods',
    ('supplier_bears', 'services'): 'l10n_bo_spa_ret_serv',
    ('supplier_bears', 'eventual'): 'l10n_bo_spa_ret_even',
    ('company_bears', 'goods'): 'l10n_bo_whh_goods_purchase',
    ('company_bears', 'services'): 'l10n_bo_whh_services_purchase',
    ('company_bears', 'eventual'): 'l10n_bo_spa_gu_even',
}
WITHHOLDING_TAX_FIELDS = {
    ('supplier_bears', 'goods'): 'l10n_bo_ret_goods_tax_id',
    ('supplier_bears', 'services'): 'l10n_bo_ret_services_tax_id',
    ('supplier_bears', 'eventual'): 'l10n_bo_ret_eventual_tax_id',
    ('company_bears', 'goods'): 'l10n_bo_gu_goods_tax_id',
    ('company_bears', 'services'): 'l10n_bo_gu_services_tax_id',
    ('company_bears', 'eventual'): 'l10n_bo_gu_eventual_tax_id',
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_bo_purchase_check = fields.Boolean(
        string='Validar documentos fiscales de compra',
        help='Al validar facturas de proveedor exige los datos del documento (NIT, número, CUF o '
             'autorización y código de control) y su coherencia con los impuestos (sin factura no hay '
             'crédito fiscal; con factura no hay retenciones). Se activa al instalar el módulo en las '
             'compañías con plan "bo"; en compañías nuevas actívelo en Ajustes. La unicidad '
             'NIT + número + CUF/autorización se controla siempre.')
    l10n_bo_default_doc_type = fields.Selection(
        DOC_TYPES, string='Tipo de documento por defecto en compras', default='siat_online')
    l10n_bo_default_purchase_type = fields.Selection(
        PURCHASE_TYPES, string='Tipo de compra por defecto (Libro de Compras)', default='1')
    l10n_bo_cuf_check = fields.Selection(
        [('strict', 'Estricta: dígito verificador y NIT/número embebidos'),
         ('format', 'Solo formato: hexadecimal y longitud')],
        string='Validación del CUF', default='strict',
        help='Estricta: decodifica el CUF (módulo 11) y exige que el NIT y el número coincidan. '
             'El algoritmo se verificó con una implementación abierta y un CUF del ambiente piloto; '
             'si una factura real es rechazada, use "Solo formato" y reporte el caso.')
    l10n_bo_nodoc_account_id = fields.Many2one(
        'account.account', string='Cuenta de compras sin factura ni retención', check_company=True,
        help='Gasto no deducible para compras sin factura y sin retención. Por defecto 560500.')
    l10n_bo_ret_goods_tax_id = fields.Many2one(
        'account.tax', string='Retención bienes (al proveedor)', check_company=True,
        help='Por defecto: Ret. 8% bienes (IUE 5 % + IT 3 %).')
    l10n_bo_ret_services_tax_id = fields.Many2one(
        'account.tax', string='Retención servicios profesionales (al proveedor)', check_company=True,
        help='Por defecto: Ret. 15.5% servicios prof. (IUE 12,5 % + IT 3 %).')
    l10n_bo_ret_eventual_tax_id = fields.Many2one(
        'account.tax', string='Retención eventuales/alquiler (al proveedor)', check_company=True,
        help='Por defecto: Ret. 16% eventuales/alquiler (RC-IVA 13 % + IT 3 %).')
    l10n_bo_gu_goods_tax_id = fields.Many2one(
        'account.tax', string='Retención asumida bienes (grossing-up)', check_company=True,
        help='Por defecto: 8% WHH IT+IUE G de l10n_bo.')
    l10n_bo_gu_services_tax_id = fields.Many2one(
        'account.tax', string='Retención asumida servicios (grossing-up)', check_company=True,
        help='Por defecto: 15.5% Whh. IT+IUE S de l10n_bo.')
    l10n_bo_gu_eventual_tax_id = fields.Many2one(
        'account.tax', string='Retención asumida eventuales/alquiler (grossing-up)', check_company=True,
        help='Por defecto: 16% gross-up eventuales/alquiler.')

    def _l10n_bo_chart_ref(self, xmlid):
        self.ensure_one()
        return self.env['account.chart.template'].with_company(self).ref(xmlid, raise_if_not_found=False)

    def _l10n_bo_get_withholding_tax(self, mode, kind):
        self.ensure_one()
        tax = self[WITHHOLDING_TAX_FIELDS[(mode, kind)]]
        return tax or self._l10n_bo_chart_ref(WITHHOLDING_TAX_XMLIDS[(mode, kind)]) or self.env['account.tax']

    def _l10n_bo_get_nodoc_account(self):
        self.ensure_one()
        return (
            self.l10n_bo_nodoc_account_id
            or self._l10n_bo_chart_ref('l10n_bo_spa_5605')
            or self.env['account.account']
        )
