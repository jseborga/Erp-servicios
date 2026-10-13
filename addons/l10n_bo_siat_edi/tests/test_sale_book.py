# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command
from odoo.tests import tagged

from .common import OTHER_NIT, L10nBoSiatCommon


@tagged('post_install', '-at_install', 'spa')
class TestSaleBook(L10nBoSiatCommon):

    def test_book_row_and_iva_debit_on_890(self):
        move = self._invoice(partner=self.customer_nit)
        self.assertFalse(self._book(move), 'Una factura pendiente de registro no va al libro.')
        self._register(move, 101)
        row = self._book(move)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.specification, 2)
        self.assertEqual(row.invoice_number, '101')
        self.assertEqual(row.auth_code, move.l10n_bo_siat_cuf)
        self.assertEqual(row.buyer_doc_type, '5')
        self.assertEqual(row.buyer_number, OTHER_NIT)
        self.assertEqual(row.buyer_name, 'Hotel Illimani SRL')
        self.assertEqual(row.state, 'V')
        self.assertEqual(row.period, row.date.strftime('%Y-%m'))
        self.assertAlmostEqual(row.amount_total, 890.0, places=2)
        self.assertAlmostEqual(row.amount_ice, 0.0)
        self.assertAlmostEqual(row.amount_exempt, 0.0)
        self.assertAlmostEqual(row.amount_zero_rate, 0.0)
        self.assertAlmostEqual(row.amount_not_subject, 0.0)
        self.assertAlmostEqual(row.amount_subtotal, 890.0, places=2)
        self.assertAlmostEqual(row.amount_discount, 0.0, places=2)
        self.assertAlmostEqual(row.amount_base, 890.0, places=2)
        self.assertAlmostEqual(row.amount_debit, 115.70, places=2)  # 13 % de 890
        self.assertEqual(row.control_code, '0')
        self.assertFalse(row.simulated)

    def test_book_discount_is_reported(self):
        move = self._invoice(discount=10.0)
        self._register(move, 102)
        row = self._book(move)
        self.assertAlmostEqual(move.amount_total, 801.0, places=2)
        self.assertAlmostEqual(row.amount_total, 890.0, places=2)
        self.assertAlmostEqual(row.amount_discount, 89.0, places=2)
        self.assertAlmostEqual(row.amount_base, 801.0, places=2)
        self.assertAlmostEqual(row.amount_debit, 104.13, places=2)

    def test_book_exempt_line(self):
        exempt = self.ct.ref('l10n_bo_iva_0_exempt_sale')
        move = self._invoice(post=False)
        move.write({'invoice_line_ids': [Command.create({
            'name': 'Venta exenta', 'price_unit': 100.0, 'quantity': 1, 'tax_ids': [Command.set(exempt.ids)]})]})
        move.action_post()
        self._register(move, 103)
        row = self._book(move)
        self.assertAlmostEqual(row.amount_total, 990.0, places=2)
        self.assertAlmostEqual(row.amount_exempt, 100.0, places=2)
        self.assertAlmostEqual(row.amount_base, 890.0, places=2)
        self.assertAlmostEqual(row.amount_debit, 115.70, places=2)

    def test_book_cancelled_invoice_state_a_with_zero_amounts(self):
        move = self._invoice()
        self._register(move, 104)
        self._cancel(move)
        row = self._book(move)
        self.assertEqual(row.state, 'A')
        self.assertEqual(row.invoice_number, '104')
        self.assertAlmostEqual(row.amount_total, 0.0)
        self.assertAlmostEqual(row.amount_base, 0.0)
        self.assertAlmostEqual(row.amount_debit, 0.0)
        # La reversión contable no aparece en el libro.
        self.assertFalse(self._book(move.reversal_move_ids))

    def test_book_simulated_rows_are_flagged_and_monthly_filter(self):
        self._use_demo()
        move = self._invoice()
        row = self._book(move)
        self.assertTrue(row.simulated)
        Book = self.env['l10n_bo.sale.book']
        self.assertIn(row, Book.search([('period', '=', row.period)]))
        self.assertNotIn(row, Book.search([('simulated', '=', False)]))
        groups = Book._read_group([('period', '=', row.period)], ['period'], ['amount_debit:sum'])
        self.assertTrue(groups)
