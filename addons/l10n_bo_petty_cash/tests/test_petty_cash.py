# Part of ERP Servicios Spa. License LGPL-3.
import base64

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.l10n_bo_purchase.tests.common import L10nBoPurchaseCommon

PHOTO = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 32)


@tagged('post_install', '-at_install', 'spa')
class TestPettyCash(L10nBoPurchaseCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,l10n_bo_petty_cash.group_petty_cash_custodian'
        cls.custodian = new_test_user(cls.env, login='custodio_recepcion', groups=groups,
                                      company_id=cls.company.id, company_ids=[cls.company.id])
        cls.custodian_b = new_test_user(cls.env, login='custodio_cocina', groups=groups,
                                        company_id=cls.company.id, company_ids=[cls.company.id])
        cls.Fund = cls.env['l10n_bo.petty.cash.fund']
        cls.area = cls.env.ref('l10n_bo_spa.analytic_area_administracion')
        cls.fund = cls.Fund.create({
            'name': 'Caja chica Recepción',
            'custodian_id': cls.custodian.id,
            'amount_fixed': 2000.0,
            'max_expense': 1500.0,
            'analytic_account_id': cls.area.id,
        })
        cls.fund.action_open()
        cls.expense = cls._ref('l10n_bo_spa_5118')

    # ------------------------------------------------------------------
    # Ayudantes
    # ------------------------------------------------------------------
    def _voucher(self, user=None, fund=None, **vals):
        values = {
            'fund_id': (fund or self.fund).id,
            'description': 'Gasto de prueba',
            'account_id': self.expense.id,
            'receipt': PHOTO,
            'receipt_filename': 'comprobante.png',
        }
        values.update(vals)
        return self.env['l10n_bo.petty.cash.voucher'].with_user(user or self.custodian).create(values)

    def _invoice_voucher(self, number=501, amount=1130.0, **vals):
        return self._voucher(
            partner_id=self.supplier.id, l10n_bo_doc_type='siat_online', l10n_bo_invoice_number=str(number),
            l10n_bo_cuf=self._cuf('1020703023', number), amount=amount, **vals)

    def _nodoc_voucher(self, amount=100.0, **vals):
        return self._voucher(
            supplier_name='Juan Mamani', l10n_bo_doc_type='none', l10n_bo_withholding_mode='supplier_bears',
            l10n_bo_purchase_kind='goods', amount=amount, **vals)

    def _report(self, cash_counted, user=None):
        report = self.env['l10n_bo.petty.cash.report'].with_user(user or self.custodian).create({
            'fund_id': self.fund.id, 'cash_counted': cash_counted,
        })
        report.action_submit()
        return report.with_env(self.env)

    def _account_balance(self, account):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('company_id', '=', self.company.id), ('parent_state', '=', 'posted'),
        ])
        return round(sum(lines.mapped('balance')), 2)

    # ------------------------------------------------------------------
    # Pruebas
    # ------------------------------------------------------------------
    def test_fund_creation_and_opening_entry(self):
        fund_account = self._ref('l10n_bo_spa_11121')
        self.assertEqual(self.fund.account_id, fund_account)
        journal = self.fund.journal_id
        self.assertEqual(journal.type, 'cash')
        self.assertEqual(journal.default_account_id, fund_account)
        self.assertEqual(set(journal.outbound_payment_method_line_ids.mapped('payment_account_id')), {fund_account})
        self.assertEqual(self.fund.state, 'open')
        opening = self.fund.opening_move_id
        self.assertEqual(opening.state, 'posted')
        self.assertEqual(opening.journal_id, self._ref('l10n_bo_spa_journal_petty_cash'))
        balances = self._balances(opening)
        self.assertEqual(balances['111210'], 2000.0)
        bank_code = self.fund.bank_journal_id.default_account_id.code
        self.assertEqual(balances[bank_code], -2000.0)
        self.assertEqual(self.fund.balance, 2000.0)
        # Un segundo fondo toma la siguiente cuenta de fondo fijo.
        other = self.Fund.create({'name': 'Caja Cocina', 'custodian_id': self.custodian_b.id, 'amount_fixed': 500.0})
        self.assertEqual(other.account_id, self._ref('l10n_bo_spa_11122'))
        self.assertNotEqual(other.journal_id, journal)

    def test_vouchers_have_no_entries_until_approval(self):
        moves_before = self.env['account.move'].search_count([('l10n_bo_petty_cash_fund_id', '=', self.fund.id)])
        voucher = self._invoice_voucher()
        self.assertEqual(voucher.state, 'draft')
        self.assertEqual(voucher.tax_ids, self._ref('l10n_bo_iva_13_purchase'))
        self.assertEqual(voucher.amount_paid, 1130.0)
        self.assertEqual(voucher.analytic_distribution, {str(self.area.id): 100})
        self.assertFalse(voucher.move_id)
        self.assertEqual(
            self.env['account.move'].search_count([('l10n_bo_petty_cash_fund_id', '=', self.fund.id)]), moves_before)
        self.assertEqual(self.fund.pending_amount, 1130.0)
        self.assertEqual(self.fund.cash_expected, 870.0)

    def test_full_cycle_replenishes_fixed_amount(self):
        invoice_voucher = self._invoice_voucher()
        nodoc_voucher = self._nodoc_voucher()
        self.assertEqual(nodoc_voucher.tax_ids, self._ref('l10n_bo_spa_ret_goods'))
        self.assertEqual(nodoc_voucher.amount_paid, 92.0)
        report = self._report(cash_counted=778.0)
        self.assertEqual(report.state, 'submitted')
        self.assertEqual(report.voucher_ids, invoice_voucher | nodoc_voucher)
        self.assertEqual(report.amount_paid, 1222.0)
        self.assertEqual(report.difference, 0.0)
        # El custodio no puede aprobar su propia rendición.
        with self.assertRaises(AccessError):
            report.with_user(self.custodian).action_approve()
        report.action_approve()
        self.assertEqual(report.state, 'approved')

        bill = invoice_voucher.move_id
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(bill.l10n_bo_petty_cash_fund_id, self.fund)
        balances = self._balances(bill)
        self.assertEqual(balances['114100'], 146.9)
        self.assertEqual(balances['511800'], 983.1)
        self.env.flush_all()
        row = self.env['l10n_bo.purchase.book'].search([('move_id', '=', bill.id)])
        self.assertAlmostEqual(row.amount_credit, 146.9)

        nodoc_bill = nodoc_voucher.move_id
        self.assertEqual(nodoc_bill.payment_state, 'paid')
        self.assertEqual(nodoc_bill.partner_id.name, 'Juan Mamani')
        balances = self._balances(nodoc_bill)
        self.assertEqual(balances['213800'], -5.0)
        self.assertEqual(balances['213700'], -3.0)
        self.assertEqual(invoice_voucher.state, 'posted')

        # Pago desde el fondo: Debe proveedor / Haber 111210.
        payment_move = invoice_voucher.payment_id.move_id
        self.assertEqual(self._balances(payment_move)['111210'], -1130.0)

        replenish = report.replenish_move_id
        self.assertEqual(replenish.state, 'posted')
        self.assertEqual(report.replenish_amount, 1222.0)
        balances = self._balances(replenish)
        self.assertEqual(balances['111210'], 1222.0)
        self.assertEqual(self.fund.balance, 2000.0)
        self.assertEqual(self._account_balance(self.fund.account_id), self.fund.amount_fixed)

    def test_shortage_charged_to_custodian(self):
        self._invoice_voucher()
        report = self._report(cash_counted=860.0)  # se esperaban 870
        self.assertEqual(report.difference, -10.0)
        report.action_approve()
        balances = self._balances(report.replenish_move_id)
        self.assertEqual(balances['112210'], 10.0)
        self.assertEqual(report.replenish_amount, 1140.0)
        receivable = report.replenish_move_id.line_ids.filtered(lambda l: l.account_id.code == '112210')
        self.assertEqual(receivable.partner_id, self.custodian.partner_id)
        self.assertEqual(self.fund.balance, 2000.0)

    def test_shortage_assumed_and_surplus(self):
        self.fund.shortage_policy = 'company'
        self._invoice_voucher()
        report = self._report(cash_counted=865.0)
        report.action_approve()
        self.assertEqual(self._balances(report.replenish_move_id)['560700'], 5.0)
        self.assertEqual(self.fund.balance, 2000.0)

        self._invoice_voucher(number=502, amount=226.0)
        report = self._report(cash_counted=1777.0)  # se esperaban 1774
        self.assertEqual(report.difference, 3.0)
        report.action_approve()
        self.assertEqual(self._balances(report.replenish_move_id)['430410'], -3.0)
        self.assertEqual(report.replenish_amount, 223.0)
        self.assertEqual(self.fund.balance, 2000.0)

    def test_custodian_sees_only_own_fund(self):
        other = self.Fund.create({'name': 'Caja Cocina', 'custodian_id': self.custodian_b.id, 'amount_fixed': 500.0})
        other.action_open()
        other_voucher = self._voucher(user=self.custodian_b, fund=other, supplier_name='Mercado', amount=50.0,
                                      l10n_bo_doc_type='none', l10n_bo_withholding_mode='no_withholding')
        Fund = self.Fund.with_user(self.custodian)
        self.assertEqual(Fund.search([]), self.fund)
        Voucher = self.env['l10n_bo.petty.cash.voucher'].with_user(self.custodian)
        self.assertFalse(Voucher.search([('id', '=', other_voucher.id)]))
        with self.assertRaises(AccessError):
            other.with_user(self.custodian).read(['name'])
        with self.assertRaises(AccessError):
            self._voucher(fund=other, supplier_name='X', amount=10.0,
                          l10n_bo_doc_type='none', l10n_bo_withholding_mode='no_withholding')
        # El custodio tampoco crea ni abre fondos.
        with self.assertRaises(AccessError):
            Fund.create({'name': 'Mi fondo', 'custodian_id': self.custodian.id, 'amount_fixed': 100.0})

    def test_voucher_duplicate_of_vendor_bill_is_blocked(self):
        bill = self._bill(number=777)
        bill.action_post()
        with self.assertRaisesText(ValidationError, bill.name):
            self._invoice_voucher(number=777)
        # Y al revés: un comprobante pendiente bloquea registrar la misma factura.
        voucher = self._invoice_voucher(number=778)
        with self.assertRaisesText(ValidationError, voucher.name):
            self._invoice_voucher(number=778)
        duplicate_bill = self._bill(number=778)
        with self.assertRaisesText(UserError, voucher.name):
            duplicate_bill.action_post()

    def test_submission_requires_complete_documents(self):
        self._voucher(partner_id=self.supplier.id, l10n_bo_doc_type='dosificacion', l10n_bo_invoice_number='10',
                      amount=50.0, receipt=False)
        report = self.env['l10n_bo.petty.cash.report'].with_user(self.custodian).create({
            'fund_id': self.fund.id, 'cash_counted': 1950.0})
        with self.assertRaisesText(UserError, 'foto'):
            report.action_submit()

    def test_max_expense_and_reported_voucher_locked(self):
        with self.assertRaisesText(ValidationError, 'tope'):
            self._nodoc_voucher(amount=1600.0)
        voucher = self._nodoc_voucher(amount=200.0)
        report = self._report(cash_counted=1816.0)
        self.assertEqual(voucher.state, 'reported')
        with self.assertRaises(UserError):
            voucher.with_user(self.custodian).amount = 300.0
        report.with_user(self.custodian).action_reset_draft()
        self.assertEqual(voucher.state, 'draft')
        voucher.with_user(self.custodian).amount = 300.0
        self.assertEqual(voucher.amount_paid, 276.0)

    def test_change_fixed_amount(self):
        with self.assertRaises(UserError):
            self.fund.amount_fixed = 3000.0
        wizard = self.env['l10n_bo.petty.cash.amount.wizard'].create({
            'fund_id': self.fund.id, 'new_amount': 2500.0, 'reason': 'Temporada alta'})
        wizard.action_apply()
        self.assertEqual(self.fund.amount_fixed, 2500.0)
        self.assertEqual(self.fund.balance, 2500.0)
        adjustment = self.env['account.move'].search(
            [('l10n_bo_petty_cash_fund_id', '=', self.fund.id)], order='id desc', limit=1)
        self.assertEqual(self._balances(adjustment)['111210'], 500.0)

    def test_qr_fills_voucher(self):
        voucher = self._voucher(partner_id=self.supplier_b.id, amount=10.0)
        cuf = self._cuf('3115970018', 4444)
        action = voucher.with_user(self.custodian).action_l10n_bo_open_qr_wizard()
        wizard = self.env['l10n_bo.qr.wizard'].with_user(self.custodian).browse(action['res_id'])
        wizard.qr_text = 'https://siat.impuestos.gob.bo/consulta/QR?nit=3115970018&cuf=%s&numero=4444&t=1' % cuf
        wizard.amount_total = 87.5
        wizard.action_apply()
        self.assertEqual(voucher.l10n_bo_cuf, cuf)
        self.assertEqual(voucher.l10n_bo_invoice_number, '4444')
        self.assertEqual(voucher.amount, 87.5)
        self.assertFalse(voucher._l10n_bo_document_errors())
