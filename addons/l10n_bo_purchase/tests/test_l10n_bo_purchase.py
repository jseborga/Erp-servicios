# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import L10nBoPurchaseCommon


@tagged('post_install', '-at_install', 'spa')
class TestL10nBoPurchase(L10nBoPurchaseCommon):

    # ------------------------------------------------------------------
    # Unicidad
    # ------------------------------------------------------------------
    def test_unique_siat_online_blocks_second_bill(self):
        first = self._bill(number=1234)
        first.action_post()
        self.assertEqual(first.state, 'posted')
        self.assertEqual(first.l10n_bo_doc_key, first.l10n_bo_cuf)
        second = self._bill(number=1234)
        self.assertTrue(second.l10n_bo_duplicate_warning)
        with self.assertRaisesText(UserError, first.name):
            second.action_post()
        self.assertEqual(second.state, 'draft')

    def test_unique_normalizes_number_and_nit(self):
        first = self._bill(number=77)
        first.action_post()
        second = self._bill(number='0000077', cuf=first.l10n_bo_cuf.lower(), l10n_bo_supplier_nit='1.020.703-023')
        self.assertEqual(second.l10n_bo_invoice_number, '77')
        self.assertEqual(second.l10n_bo_supplier_nit, '1020703023')
        with self.assertRaisesText(UserError, first.name):
            second.action_post()

    def test_unique_dosificacion_auth_number(self):
        first = self._bill(doc_type='dosificacion', number=50, auth='29040011007', control='73-55-84-AC')
        first.action_post()
        second = self._bill(doc_type='dosificacion', number=50, auth='29040011007', control='7b-f3-48-a8')
        self.assertEqual(second.l10n_bo_control_code, '7B-F3-48-A8')
        with self.assertRaisesText(UserError, first.name):
            second.action_post()
        # Otra autorización con el mismo número sí es otro documento.
        third = self._bill(doc_type='dosificacion', number=50, auth='29040011008', control='73-55-84-AC')
        third.action_post()
        self.assertEqual(third.state, 'posted')

    def test_same_number_other_supplier_is_ok(self):
        self._bill(number=1).action_post()
        other = self._bill(partner=self.supplier_b, number=1)
        other.action_post()
        self.assertEqual(other.state, 'posted')
        self.assertEqual(other.l10n_bo_supplier_nit, '3115970018')

    def test_cancelled_bill_does_not_block(self):
        first = self._bill(number=900)
        first.action_post()
        first.button_draft()
        first.button_cancel()
        self.assertEqual(first.state, 'cancel')
        second = self._bill(number=900)
        second.action_post()
        self.assertEqual(second.state, 'posted')

    def test_unique_index_in_database(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'account_move_l10n_bo_purchase_document_unique'")
        definition = self.env.cr.fetchone()[0]
        self.assertIn('UNIQUE', definition)
        self.assertIn("'posted'", definition)

    def test_fiscal_data_locked_when_posted(self):
        bill = self._bill(number=31)
        bill.action_post()
        with self.assertRaises(UserError):
            bill.l10n_bo_invoice_number = '32'

    # ------------------------------------------------------------------
    # Coherencia del documento
    # ------------------------------------------------------------------
    def test_none_doc_with_vat_rejected(self):
        bill = self._bill(doc_type='none', partner=self.person, price=1000.0,
                          l10n_bo_withholding_mode='no_withholding', account='l10n_bo_spa_5605')
        with self.assertRaisesText(UserError, 'crédito fiscal'):
            bill.action_post()

    def test_invoice_with_withholding_rejected(self):
        bill = self._bill(number=55, taxes=('l10n_bo_spa_ret_goods',), price=1000.0)
        with self.assertRaisesText(UserError, 'retenciones'):
            bill.action_post()

    def test_siat_online_requires_valid_cuf(self):
        bill = self._bill(number=10, cuf='XYZ')
        with self.assertRaisesText(UserError, 'hexadecimal'):
            bill.action_post()
        # CUF de otro proveedor: el NIT embebido no coincide (validación estricta).
        bill.l10n_bo_cuf = self._cuf('3115970018', 10)
        with self.assertRaisesText(UserError, 'NIT 3115970018'):
            bill.action_post()
        # Número distinto del embebido en el CUF.
        bill.l10n_bo_cuf = self._cuf('1020703023', 11)
        with self.assertRaisesText(UserError, 'n.º 11'):
            bill.action_post()
        # Con validación "solo formato" se acepta un CUF hexadecimal de largo plausible.
        self.company.l10n_bo_cuf_check = 'format'
        bill.l10n_bo_cuf = 'ABCDEF0123456789ABCDEF0123456789ABCDEF0123'
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_siat_online_missing_cuf(self):
        bill = self._bill(number=12, cuf=False)
        bill.l10n_bo_cuf = False
        with self.assertRaisesText(UserError, 'Falta el CUF'):
            bill.action_post()

    def test_dosificacion_requires_auth_and_control_code(self):
        bill = self._bill(doc_type='dosificacion', number=60)
        with self.assertRaisesText(UserError, 'autorización'):
            bill.action_post()
        bill.write({'l10n_bo_auth_number': '7904006306693', 'l10n_bo_control_code': 'ZZ-11'})
        with self.assertRaisesText(UserError, 'código de control'):
            bill.action_post()
        bill.l10n_bo_control_code = '7B-F3-48-A8'
        bill.action_post()
        self.assertEqual(bill.l10n_bo_doc_key, '7904006306693')

    def test_manual_requires_auth(self):
        bill = self._bill(doc_type='manual', number=8)
        with self.assertRaisesText(UserError, 'autorización'):
            bill.action_post()
        bill.l10n_bo_auth_number = '123456'
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_supplier_refund_without_document_posts(self):
        bill = self._bill(number=99)
        bill.action_post()
        refund = bill._reverse_moves([{'invoice_date': '2026-10-11', 'date': '2026-10-11'}], cancel=True)
        self.assertEqual(refund.move_type, 'in_refund')
        self.assertFalse(refund.l10n_bo_doc_type)
        self.assertEqual(refund.state, 'posted')
        self.assertEqual(bill.payment_state, 'reversed')

    def test_validation_switch_keeps_uniqueness(self):
        self.company.l10n_bo_purchase_check = False
        incomplete = self._bill(number=False, cuf=False)
        incomplete.action_post()
        self.assertEqual(incomplete.state, 'posted')
        self._bill(number=4040).action_post()
        with self.assertRaisesText(UserError, 'ya está registrado'):
            self._bill(number=4040).action_post()

    def test_default_doc_type_from_company(self):
        self.company.l10n_bo_default_doc_type = 'dosificacion'
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': self.supplier.id})
        self.assertEqual(bill.l10n_bo_doc_type, 'dosificacion')
        self.assertEqual(bill.l10n_bo_supplier_nit, '1020703023')
        self.assertEqual(bill.l10n_bo_purchase_type, '1')
        entry = self.env['account.move'].create({'move_type': 'entry'})
        self.assertFalse(entry.l10n_bo_doc_type)

    # ------------------------------------------------------------------
    # Retenciones (compras sin factura)
    # ------------------------------------------------------------------
    def _none_bill(self, mode, kind=None, account='l10n_bo_spa_53017', price=1000.0):
        bill = self._bill(doc_type='none', partner=self.person, price=price, taxes=(), account=account,
                          l10n_bo_withholding_mode=mode, l10n_bo_purchase_kind=kind)
        bill.action_l10n_bo_apply_withholding()
        bill.action_post()
        return self._balances(bill)

    def test_withholding_goods_retained(self):
        balances = self._none_bill('supplier_bears', 'goods', account='l10n_bo_spa_5118')
        self.assertEqual(balances['511800'], 1000.0)
        self.assertEqual(balances['212100'], -920.0)
        self.assertEqual(balances['213800'], -50.0)
        self.assertEqual(balances['213700'], -30.0)

    def test_withholding_services_retained(self):
        balances = self._none_bill('supplier_bears', 'services')
        self.assertEqual(balances['212100'], -845.0)
        self.assertEqual(balances['213800'], -125.0)
        self.assertEqual(balances['213700'], -30.0)

    def test_withholding_eventual_retained(self):
        balances = self._none_bill('supplier_bears', 'eventual')
        self.assertEqual(balances['212100'], -840.0)
        self.assertEqual(balances['213910'], -130.0)
        self.assertEqual(balances['213700'], -30.0)

    def test_withholding_services_gross_up(self):
        balances = self._none_bill('company_bears', 'services')
        self.assertEqual(balances['212100'], -1000.0)
        self.assertEqual(balances['530170'], 1000.0)
        self.assertEqual(balances['520930'], 147.93)
        self.assertEqual(balances['520920'], 35.5)
        self.assertEqual(balances['213800'], -147.93)
        self.assertEqual(balances['213700'], -35.5)

    def test_no_withholding_goes_to_non_deductible(self):
        balances = self._none_bill('no_withholding')
        self.assertEqual(balances, {'560500': 1000.0, '212100': -1000.0})

    def test_withholding_line_kind_overrides_document(self):
        bill = self._bill(doc_type='none', partner=self.person, price=1000.0, taxes=(),
                          l10n_bo_withholding_mode='supplier_bears', l10n_bo_purchase_kind='services')
        bill.invoice_line_ids.l10n_bo_purchase_kind = 'goods'
        bill.action_l10n_bo_apply_withholding()
        self.assertEqual(bill.invoice_line_ids.tax_ids, self._ref('l10n_bo_spa_ret_goods'))

    def test_withholding_required_at_posting(self):
        bill = self._bill(doc_type='none', partner=self.person, price=1000.0, taxes=(),
                          l10n_bo_withholding_mode='supplier_bears', l10n_bo_purchase_kind='goods')
        with self.assertRaisesText(UserError, 'Aplicar retenciones'):
            bill.action_post()
        bill.l10n_bo_withholding_mode = False
        with self.assertRaisesText(UserError, 'sin factura'):
            bill.action_post()

    def test_withholding_onchange_in_form(self):
        with Form(self.env['account.move'].with_context(default_move_type='in_invoice')) as form:
            form.partner_id = self.person
            form.invoice_date = '2026-10-10'
            with form.invoice_line_ids.new() as line:
                line.name = 'Servicio de electricista'
                line.account_id = self._ref('l10n_bo_spa_5124')
                line.price_unit = 1000.0
                line.tax_ids.clear()
                line.tax_ids.add(self._ref('l10n_bo_iva_13_purchase'))
            form.l10n_bo_doc_type = 'none'
            form.l10n_bo_withholding_mode = 'supplier_bears'
            form.l10n_bo_purchase_kind = 'eventual'
        bill = form.record
        self.assertEqual(bill.invoice_line_ids.tax_ids, self._ref('l10n_bo_spa_ret_even'))
        self.assertAlmostEqual(bill.amount_total, 840.0)

    # ------------------------------------------------------------------
    # Lector QR
    # ------------------------------------------------------------------
    def test_qr_wizard_fills_bill(self):
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': self.supplier_b.id})
        cuf = self._cuf('3115970018', 4321)
        action = bill.action_l10n_bo_open_qr_wizard()
        wizard = self.env['l10n_bo.qr.wizard'].browse(action['res_id'])
        wizard.qr_text = 'https://siat.impuestos.gob.bo/consulta/QR?nit=3115970018&cuf=%s&numero=4321&t=2' % cuf
        self.assertEqual(wizard.doc_type, 'siat_online')
        self.assertEqual(str(wizard.date), '2026-10-10')
        wizard.amount_total = 565.0
        wizard.action_apply()
        self.assertEqual(bill.l10n_bo_cuf, cuf)
        self.assertEqual(bill.l10n_bo_invoice_number, '4321')
        self.assertEqual(str(bill.invoice_date), '2026-10-10')
        self.assertEqual(bill.amount_total, 565.0)
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_qr_wizard_legacy_finds_partner(self):
        bill = self.env['account.move'].create({'move_type': 'in_invoice'})
        action = bill.action_l10n_bo_open_qr_wizard()
        wizard = self.env['l10n_bo.qr.wizard'].browse(action['res_id'])
        wizard.qr_text = '1020703023|50|29040011007|12/10/2026|275.00|275.00|73-55-84-AC|163874028|0|0|0|0'
        wizard.action_apply()
        self.assertEqual(bill.partner_id, self.supplier)
        self.assertEqual(bill.l10n_bo_doc_type, 'dosificacion')
        self.assertEqual(bill.l10n_bo_auth_number, '29040011007')
        self.assertEqual(bill.l10n_bo_control_code, '73-55-84-AC')
        self.assertEqual(bill.amount_total, 275.0)

    # ------------------------------------------------------------------
    # Libro de Compras
    # ------------------------------------------------------------------
    def test_purchase_book_row(self):
        bill = self._bill(number=1130)
        bill.action_post()
        manual = self._bill(partner=self.supplier_b, doc_type='manual', number=5, auth='4001', price=226.0)
        manual.action_post()
        no_doc = self._bill(doc_type='none', partner=self.person, price=100.0, taxes=(),
                            l10n_bo_withholding_mode='no_withholding')
        no_doc.action_l10n_bo_apply_withholding()
        no_doc.action_post()
        self.env.flush_all()
        Book = self.env['l10n_bo.purchase.book']
        row = Book.search([('move_id', '=', bill.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.amount_total, 1130.0)
        self.assertEqual(row.amount_subtotal, 1130.0)
        self.assertEqual(row.amount_base, 1130.0)
        self.assertAlmostEqual(row.amount_credit, 146.9)
        self.assertEqual(row.auth_number, '1')
        self.assertEqual(row.control_code, bill.l10n_bo_cuf)
        self.assertEqual(row.supplier_nit, '1020703023')
        self.assertEqual(row.purchase_type, '1')
        self.assertEqual(row.period, '2026-10')
        manual_row = Book.search([('move_id', '=', manual.id)])
        self.assertEqual(manual_row.auth_number, '4001')
        self.assertEqual(manual_row.control_code, '0')
        self.assertAlmostEqual(manual_row.amount_credit, 29.38)
        self.assertFalse(Book.search([('move_id', '=', no_doc.id)]))

    def test_purchase_book_exempt_amounts(self):
        bill = self._bill(number=2000, price=1130.0)
        bill.write({'invoice_line_ids': [Command.create({
            'name': 'Importe exento',
            'account_id': self._ref('l10n_bo_spa_53017').id,
            'price_unit': 70.0,
            'quantity': 1,
            'tax_ids': [Command.set(self._ref('l10n_bo_iva_0_exempt_purchase').ids)],
        })]})
        bill.action_post()
        self.env.flush_all()
        row = self.env['l10n_bo.purchase.book'].search([('move_id', '=', bill.id)])
        self.assertEqual(row.amount_total, 1200.0)
        self.assertEqual(row.amount_exempt, 70.0)
        self.assertEqual(row.amount_base, 1130.0)
        self.assertAlmostEqual(row.amount_credit, 146.9)
