# Part of ERP Servicios Spa. License LGPL-3.
import logging

from odoo import models
from odoo.addons.account.models.chart_template import template

_logger = logging.getLogger(__name__)

# Cuenta de inventario -> cuenta de gasto/costo usada por la valoración de stock
# (campo de stock_account; se ignora si stock_account no está instalado).
STOCK_EXPENSE_LINKS = {
    'l10n_bo_spa_11311': 'l10n_bo_spa_51012',
    'l10n_bo_spa_11331': 'l10n_bo_spa_51011',
    'l10n_bo_spa_11332': 'l10n_bo_spa_5117',
    'l10n_bo_spa_11333': 'l10n_bo_spa_5116',
    'l10n_bo_spa_11334': 'l10n_bo_spa_5118',
}

# Categoría de producto -> (cuenta de ingreso, cuenta de gasto, cuenta de valoración)
PRODUCT_CATEGORY_ACCOUNTS = {
    'categ_membership_monthly': ('l10n_bo_spa_41011', None, None),
    'categ_membership_prepaid': ('l10n_bo_spa_2151', None, None),
    'categ_entry': ('l10n_bo_spa_41012', None, None),
    'categ_massage': ('l10n_bo_spa_41013', 'l10n_bo_spa_5115', None),
    'categ_package': ('l10n_bo_spa_2152', None, None),
    'categ_guest': ('l10n_bo_spa_41014', None, None),
    'categ_class': ('l10n_bo_spa_41017', 'l10n_bo_spa_5115', None),
    'categ_rental': ('l10n_bo_spa_41016', None, None),
    'categ_penalty': ('l10n_bo_spa_41019', None, None),
    'categ_food_beverage': ('l10n_bo_spa_41015', 'l10n_bo_spa_51011', 'l10n_bo_spa_11331'),
    'categ_shop_goods': ('l10n_bo_spa_41018', 'l10n_bo_spa_51012', 'l10n_bo_spa_11311'),
    'categ_supplies_pool': (None, 'l10n_bo_spa_5116', 'l10n_bo_spa_11333'),
    'categ_supplies_spa': (None, 'l10n_bo_spa_5117', 'l10n_bo_spa_11332'),
    'categ_supplies_amenities': (None, 'l10n_bo_spa_5118', 'l10n_bo_spa_11334'),
    'categ_gift_card': ('l10n_bo_spa_2153', None, None),
    'categ_discount': ('l10n_bo_spa_41021', None, None),
}

# Modelos de reparto analítico (prorrateo) por prefijo de cuenta.
# Porcentajes ILUSTRATIVOS: ajustarlos con mediciones reales (kWh, m³, m², horas).
# sequence menor = más específico; gana el primero que coincide.
DISTRIBUTION_MODELS = [
    # (prefijo, secuencia, {área: %})
    ('5121', 10, {'piscina': 35, 'sauna_jacuzzi': 30, 'spa': 5, 'restaurante': 15, 'cafeteria': 5, 'administracion': 10}),
    ('5122', 10, {'piscina': 45, 'sauna_jacuzzi': 15, 'spa': 5, 'restaurante': 15, 'cafeteria': 5, 'administracion': 15}),
    ('5123', 10, {'piscina': 50, 'sauna_jacuzzi': 30, 'restaurante': 15, 'cafeteria': 5}),
    ('5116', 10, {'piscina': 80, 'sauna_jacuzzi': 20}),
    ('5124', 10, {'piscina': 60, 'sauna_jacuzzi': 40}),
    ('5117', 10, {'spa': 100}),
    ('5115', 10, {'spa': 100}),
    ('53012', 10, {'piscina': 40, 'sauna_jacuzzi': 15, 'spa': 10, 'restaurante': 20, 'cafeteria': 5, 'administracion': 10}),
    ('52', 100, {'administracion': 100}),
    ('53', 100, {'administracion': 100}),
]

# Prefijos de gasto que exigen analítica en facturas de proveedor.
MANDATORY_BILL_PREFIXES = '51,52,53'

# l10n_bo 19.0 define el grossing-up con los signos invertidos: la factura
# DEBITA las retenciones por pagar (2137/2138) y ACREDITA el gasto (52092/52093).
# Lo correcto es debitar el gasto y acreditar el pasivo. Se corrige el signo.
L10N_BO_GROSS_UP_FIX = {
    'l10n_bo_whh_services_it_tax': -3.5503,
    'l10n_bo_whh_services_it_expense': 3.5503,
    'l10n_bo_whh_services_iue_tax': -14.7929,
    'l10n_bo_whh_services_iue_expense': 14.7929,
    'l10n_bo_whh_goods_it_tax': -3.2609,
    'l10n_bo_whh_goods_it_expense': 3.2609,
    'l10n_bo_whh_goods_iue_tax': -5.4348,
    'l10n_bo_whh_goods_iue_expense': 5.4348,
}
L10N_BO_GROSS_UP_GROUPS = {
    'l10n_bo_whh_services_purchase': [
        'l10n_bo_whh_services_it_tax', 'l10n_bo_whh_services_it_expense',
        'l10n_bo_whh_services_iue_tax', 'l10n_bo_whh_services_iue_expense',
    ],
    'l10n_bo_whh_goods_purchase': [
        'l10n_bo_whh_goods_it_tax', 'l10n_bo_whh_goods_it_expense',
        'l10n_bo_whh_goods_iue_tax', 'l10n_bo_whh_goods_iue_expense',
    ],
}

# IVA de compras: en Bolivia el crédito fiscal es el 13 % del importe facturado
# (IVA incluido). l10n_bo deja estos impuestos con el criterio por defecto de la
# compañía (precio sin impuesto), lo que calcula 13/87 sobre el total.
L10N_BO_PURCHASE_VAT = (
    'l10n_bo_iva_13_purchase',
    'l10n_bo_iva_13_discount_purchase',
    'l10n_bo_iva_13_purchase_personal',
    'l10n_bo_iva_13_purchase_donations',
    'l10n_bo_iva_mixed_purchase',
)
# Impuestos cuyo IVA va a 1141 Crédito Fiscal IVA en lugar de 2135.
L10N_BO_PURCHASE_VAT_TO_CREDIT = ('l10n_bo_iva_13_purchase', 'l10n_bo_iva_mixed_purchase')


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    # ------------------------------------------------------------------
    # Datos de plantilla (se cargan con el plan 'bo')
    # ------------------------------------------------------------------
    @template('bo', 'account.account')
    def _get_bo_spa_account_account(self):
        accounts = self._parse_csv('bo', 'account.account', module='l10n_bo_spa')
        for inventory, expense in STOCK_EXPENSE_LINKS.items():
            accounts[inventory]['account_stock_expense_id'] = expense
        return accounts

    @template('bo', 'account.tax.group')
    def _get_bo_spa_account_tax_group(self):
        return self._parse_csv('bo', 'account.tax.group', module='l10n_bo_spa')

    @template('bo', 'account.tax')
    def _get_bo_spa_account_tax(self):
        taxes = self._parse_csv('bo', 'account.tax', module='l10n_bo_spa')
        self._deref_account_tags('bo', taxes)
        # Correcciones sobre impuestos de l10n_bo (se fusionan con su plantilla).
        for xmlid, amount in L10N_BO_GROSS_UP_FIX.items():
            taxes[xmlid] = {'amount': amount}
        for xmlid in L10N_BO_PURCHASE_VAT:
            taxes[xmlid] = {'price_include_override': 'tax_included'}
        return taxes

    @template('bo', 'account.journal')
    def _get_bo_spa_account_journal(self):
        return {
            'l10n_bo_spa_journal_petty_cash': {
                'name': 'Fondos fijos', 'code': 'FFIJ', 'type': 'general',
                'show_on_dashboard': False, 'sequence': 20,
            },
            'l10n_bo_spa_journal_deferred': {
                'name': 'Ingresos diferidos', 'code': 'DIFE', 'type': 'general',
                'show_on_dashboard': False, 'sequence': 21,
            },
            'l10n_bo_spa_journal_payroll': {
                'name': 'Planillas de sueldos', 'code': 'PLAN', 'type': 'general',
                'show_on_dashboard': False, 'sequence': 22,
            },
            'l10n_bo_spa_journal_depreciation': {
                'name': 'Depreciaciones', 'code': 'DEPR', 'type': 'general',
                'show_on_dashboard': False, 'sequence': 23,
            },
        }

    @template('bo', 'res.company')
    def _get_bo_spa_res_company(self):
        return {
            self.env.company.id: {
                'default_cash_difference_income_account_id': 'l10n_bo_spa_43041',
                'default_cash_difference_expense_account_id': 'l10n_bo_spa_5607',
                # Precios con IVA incluido: redondear por línea evita diferencias de Bs 0,01
                # entre el ticket (POS) y la factura (p. ej. Bs 13,50 facturado como 13,51).
                'tax_calculation_rounding_method': 'round_per_line',
            },
        }

    # ------------------------------------------------------------------
    # Configuración posterior a la carga del plan
    # ------------------------------------------------------------------
    def _post_load_data(self, template_code, company, template_data):
        res = super()._post_load_data(template_code, company, template_data)
        if template_code == 'bo':
            company = company or self.env.company
            company.tax_calculation_rounding_method = 'round_per_line'
            self._l10n_bo_spa_setup_cash_difference(company)
            self._l10n_bo_spa_setup_purchase_vat(company)
            self._l10n_bo_spa_setup_analytic(company)
            self._l10n_bo_spa_setup_product_categories(company)
        return res

    def _l10n_bo_spa_setup_cash_difference(self, company):
        """Diferencias de caja a 43041/5607 en vez de 4301/5601 (ajuste por inflación)."""
        gain = self.ref('l10n_bo_spa_43041', raise_if_not_found=False)
        loss = self.ref('l10n_bo_spa_5607', raise_if_not_found=False)
        old_gain = self.ref('l10n_bo_4301', raise_if_not_found=False)
        old_loss = self.ref('l10n_bo_5601', raise_if_not_found=False)
        if not (gain and loss):
            return
        if company.default_cash_difference_income_account_id in (old_gain, self.env['account.account']):
            company.default_cash_difference_income_account_id = gain
        if company.default_cash_difference_expense_account_id in (old_loss, self.env['account.account']):
            company.default_cash_difference_expense_account_id = loss
        journals = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', 'in', ('cash', 'bank')),
        ])
        for journal in journals:
            if old_gain and journal.profit_account_id == old_gain:
                journal.profit_account_id = gain
            if old_loss and journal.loss_account_id == old_loss:
                journal.loss_account_id = loss

    def _l10n_bo_spa_fix_gross_up_in_place(self):
        """Antes de recargar el plan en una compañía existente, corrige el signo de
        los impuestos de grossing-up no usados para que coincidan con la plantilla
        corregida y Odoo no los duplique como '[old] ...'."""
        for xmlid, amount in L10N_BO_GROSS_UP_FIX.items():
            tax = self.ref(xmlid, raise_if_not_found=False)
            if tax and tax.amount != amount and not self._l10n_bo_spa_tax_is_used(tax):
                tax.amount = amount

    def _l10n_bo_spa_tax_is_used(self, tax):
        return bool(self.env['account.move.line'].search_count([
            '|', ('tax_line_id', '=', tax.id), ('tax_ids', 'in', tax.ids),
        ], limit=1))

    def _l10n_bo_spa_setup_purchase_vat(self, company):
        """Ajustes sobre los impuestos de l10n_bo, solo si aún no tienen movimientos.

        * IVA de compras con precio IVA incluido (crédito fiscal = 13 % del total).
        * IVA de compras a 1141 Crédito Fiscal IVA (l10n_bo lo deja en 2135).
        * Signo correcto del grossing-up de retenciones.
        """
        credit = self.ref('l10n_bo_1141', raise_if_not_found=False)
        debit = self.ref('l10n_bo_2135', raise_if_not_found=False)
        for xmlid in L10N_BO_PURCHASE_VAT:
            tax = self.ref(xmlid, raise_if_not_found=False)
            if not tax or self._l10n_bo_spa_tax_is_used(tax):
                continue
            tax.price_include_override = 'tax_included'
            if credit and debit and xmlid in L10N_BO_PURCHASE_VAT_TO_CREDIT:
                tax.repartition_line_ids.filtered(
                    lambda l: l.repartition_type == 'tax' and l.account_id == debit
                ).account_id = credit

        for xmlid, amount in L10N_BO_GROSS_UP_FIX.items():
            tax = self.ref(xmlid, raise_if_not_found=False)
            if not tax or tax.amount == amount:
                continue
            if self._l10n_bo_spa_tax_is_used(tax):
                _logger.warning("l10n_bo_spa: %s ya tiene movimientos; revise el signo del grossing-up.", tax.name)
                continue
            tax.amount = amount
        for group_xmlid, children in L10N_BO_GROSS_UP_GROUPS.items():
            group = self.ref(group_xmlid, raise_if_not_found=False)
            child_taxes = self.env['account.tax']
            for child in children:
                child_taxes |= self.ref(child, raise_if_not_found=False) or self.env['account.tax']
            if group and child_taxes and group.children_tax_ids != child_taxes:
                group.children_tax_ids = child_taxes

    def _l10n_bo_spa_area(self, key):
        return self.env.ref(f'l10n_bo_spa.analytic_area_{key}')

    def _l10n_bo_spa_setup_analytic(self, company):
        plan = self.env.ref('l10n_bo_spa.analytic_plan_areas', raise_if_not_found=False)
        if not plan:
            return
        plan.with_company(company).default_applicability = 'optional'

        Applicability = self.env['account.analytic.applicability'].sudo()
        if not Applicability.search_count([
            ('analytic_plan_id', '=', plan.id), ('company_id', '=', company.id),
            ('business_domain', '=', 'bill'),
        ]):
            Applicability.create({
                'analytic_plan_id': plan.id,
                'business_domain': 'bill',
                'applicability': 'mandatory',
                'account_prefix': MANDATORY_BILL_PREFIXES,
                'company_id': company.id,
            })

        Model = self.env['account.analytic.distribution.model'].sudo()
        for prefix, sequence, shares in DISTRIBUTION_MODELS:
            if Model.search_count([('company_id', '=', company.id), ('account_prefix', '=', prefix)]):
                continue
            Model.create({
                'company_id': company.id,
                'account_prefix': prefix,
                'sequence': sequence,
                'analytic_distribution': {
                    str(self._l10n_bo_spa_area(area).id): pct for area, pct in shares.items()
                },
            })

    def _l10n_bo_spa_setup_product_categories(self, company):
        for categ_xmlid, (income, expense, valuation) in PRODUCT_CATEGORY_ACCOUNTS.items():
            categ = self.env.ref(f'l10n_bo_spa.{categ_xmlid}', raise_if_not_found=False)
            if not categ:
                continue
            categ = categ.with_company(company)
            vals = {}
            if income and (account := self.ref(income, raise_if_not_found=False)):
                vals['property_account_income_categ_id'] = account.id
            if expense and (account := self.ref(expense, raise_if_not_found=False)):
                vals['property_account_expense_categ_id'] = account.id
            if (
                valuation
                and 'property_stock_valuation_account_id' in categ._fields
                and (account := self.ref(valuation, raise_if_not_found=False))
            ):
                vals['property_stock_valuation_account_id'] = account.id
            if vals:
                categ.write(vals)
