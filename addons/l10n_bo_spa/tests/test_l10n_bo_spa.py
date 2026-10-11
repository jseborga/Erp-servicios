# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBoSpa(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_chart_template('bo')
    def setUpClass(cls):
        super().setUpClass()
        cls.ct = cls.env['account.chart.template']
        cls.supplier = cls.env['res.partner'].create({'name': 'Proveedor de prueba'})

    def _ref(self, xmlid):
        return self.ct.ref(xmlid)

    def _bill(self, account_xmlid, tax_xmlids, price=1000.0):
        taxes = self.env['account.tax']
        for xmlid in tax_xmlids:
            taxes |= self._ref(xmlid)
        return self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.supplier.id,
            'invoice_date': '2026-10-10',
            'invoice_line_ids': [Command.create({
                'name': 'Prueba',
                'account_id': self._ref(account_xmlid).id,
                'price_unit': price,
                'quantity': 1,
                'tax_ids': [Command.set(taxes.ids)],
            })],
        })

    def _balance_by_code(self, move):
        result = {}
        for line in move.line_ids:
            result[line.account_id.code] = round(result.get(line.account_id.code, 0.0) + line.balance, 2)
        return result

    def test_accounts_and_journals(self):
        self.assertEqual(self._ref('l10n_bo_spa_2151').code, '215100')
        self.assertEqual(self._ref('l10n_bo_spa_5121').account_type, 'expense_direct_cost')
        self.assertEqual(self._ref('l10n_bo_spa_11121').account_type, 'asset_cash')
        codes = self.env['account.journal'].search([('company_id', '=', self.env.company.id)]).mapped('code')
        for code in ('FFIJ', 'DIFE', 'PLAN', 'DEPR'):
            self.assertIn(code, codes)

    def test_cash_difference_accounts(self):
        company = self.env.company
        self.assertEqual(company.default_cash_difference_income_account_id, self._ref('l10n_bo_spa_43041'))
        self.assertEqual(company.default_cash_difference_expense_account_id, self._ref('l10n_bo_spa_5607'))

    def test_withholding_retained_from_supplier(self):
        bill = self._bill('l10n_bo_spa_5115', ['l10n_bo_spa_ret_serv'])
        bill.action_post()
        balances = self._balance_by_code(bill)
        self.assertEqual(balances['511500'], 1000.0)
        self.assertEqual(balances['213800'], -125.0)
        self.assertEqual(balances['213700'], -30.0)
        self.assertEqual(balances['212100'], -845.0)

    def test_withholding_rciva_retained(self):
        bill = self._bill('l10n_bo_spa_5115', ['l10n_bo_spa_ret_even'])
        bill.action_post()
        balances = self._balance_by_code(bill)
        self.assertEqual(balances['213910'], -130.0)
        self.assertEqual(balances['213700'], -30.0)
        self.assertEqual(balances['212100'], -840.0)

    def test_gross_up_signs(self):
        """El grossing-up debe debitar el gasto y acreditar el pasivo."""
        bill = self._bill('l10n_bo_spa_5115', ['l10n_bo_whh_services_purchase'])
        bill.action_post()
        balances = self._balance_by_code(bill)
        self.assertEqual(balances['520930'], 147.93)
        self.assertEqual(balances['520920'], 35.5)
        self.assertEqual(balances['213800'], -147.93)
        self.assertEqual(balances['213700'], -35.5)
        self.assertEqual(balances['212100'], -1000.0)

        bill = self._bill('l10n_bo_spa_5115', ['l10n_bo_spa_gu_even'])
        bill.action_post()
        balances = self._balance_by_code(bill)
        self.assertEqual(balances['520940'], 154.76)
        self.assertEqual(balances['213910'], -154.76)
        self.assertEqual(balances['212100'], -1000.0)

    def test_purchase_vat_included_to_tax_credit(self):
        """Factura de Bs 1.130: crédito fiscal = 13 % del total = 146,90 en 1141."""
        bill = self._bill('l10n_bo_spa_53017', ['l10n_bo_iva_13_purchase'], price=1130.0)
        bill.action_post()
        balances = self._balance_by_code(bill)
        self.assertEqual(balances['114100'], 146.9)
        self.assertEqual(balances['530170'], 983.1)
        self.assertEqual(balances['212100'], -1130.0)

    def test_analytic_distribution_model(self):
        bill = self._bill('l10n_bo_spa_5121', ['l10n_bo_iva_13_purchase'], price=1130.0)
        distribution = bill.invoice_line_ids.analytic_distribution
        self.assertAlmostEqual(sum(distribution.values()), 100.0)
        piscina = str(self.env.ref('l10n_bo_spa.analytic_area_piscina').id)
        self.assertIn(piscina, distribution)

    def test_mandatory_analytic_on_bills(self):
        bill = self._bill('l10n_bo_spa_51011', ['l10n_bo_iva_13_purchase'], price=100.0)
        with self.assertRaises(UserError):
            bill.with_context(validate_analytic=True).action_post()

    def test_product_category_accounts(self):
        food = self.env.ref('l10n_bo_spa.categ_food_beverage').with_company(self.env.company)
        self.assertEqual(food.property_account_income_categ_id, self._ref('l10n_bo_spa_41015'))
        self.assertEqual(food.property_account_expense_categ_id, self._ref('l10n_bo_spa_51011'))
        prepaid = self.env.ref('l10n_bo_spa.categ_membership_prepaid').with_company(self.env.company)
        self.assertEqual(prepaid.property_account_income_categ_id, self._ref('l10n_bo_spa_2151'))
