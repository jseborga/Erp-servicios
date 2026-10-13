# Part of ERP Servicios Spa. License LGPL-3.
from ast import literal_eval
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.l10n_bo_purchase.tools import siat
from odoo.addons.l10n_bo_siat_edi.models.l10n_bo_siat_provider import L10nBoSiatProvider, L10nBoSiatTransientError

from .common import COMPANY_NIT, OTHER_NIT, L10nBoSiatCommon

REGISTER = 'l10n_bo_siat_edi.mail_activity_siat_register'
REVIEW = 'l10n_bo_siat_edi.mail_activity_siat_review'


@tagged('post_install', '-at_install', 'spa')
class TestL10nBoSiatEdi(L10nBoSiatCommon):

    # ------------------------------------------------------------------
    # Proveedor simulado
    # ------------------------------------------------------------------
    def test_demo_provider_emits_on_post(self):
        self._use_demo()
        move = self._invoice()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')
        self.assertEqual(move.l10n_bo_siat_mode, 'provider')
        self.assertEqual(move.l10n_bo_siat_provider_id, self.demo)
        self.assertTrue(move.l10n_bo_siat_simulated)
        self.assertTrue(move.l10n_bo_siat_number)
        self.assertTrue(move.l10n_bo_siat_cuf.startswith('SIMULADO'))
        self.assertTrue(move.l10n_bo_siat_emission_date)
        self.assertIn('SIMULADO', move.l10n_bo_siat_log)
        self.assertFalse(self._activities(move, REGISTER))
        # Determinista: misma factura y número → mismo CUF.
        self.assertEqual(self.demo._siat_demo_cuf(move, move.l10n_bo_siat_number), move.l10n_bo_siat_cuf)
        second = self._invoice()
        self.assertEqual(int(second.l10n_bo_siat_number), int(move.l10n_bo_siat_number) + 1)
        self.assertNotEqual(second.l10n_bo_siat_cuf, move.l10n_bo_siat_cuf)

    def test_demo_cuf_can_never_pass_as_real(self):
        self._use_demo()
        fake = self._invoice().l10n_bo_siat_cuf
        self.assertFalse(siat.is_plausible_cuf(fake))
        self.assertIsNone(siat.decode_cuf(fake))
        self.company.l10n_bo_siat_mode = 'portal_web'
        move = self._invoice()
        with self.assertRaisesText(UserError, 'SIMULADO'):
            self._register(move, 5, cuf=fake)

    def test_provider_without_emit_on_post_waits_for_cron(self):
        self._use_demo()
        self.demo.emit_on_post = False
        move = self._invoice()
        self.assertEqual(move.l10n_bo_siat_state, 'to_send')
        self.env['account.move']._cron_l10n_bo_siat_process()
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')

    def test_provider_failure_is_retried_by_cron(self):
        self._use_demo()

        def fail(provider, move):
            raise L10nBoSiatTransientError('Tiempo de espera agotado')

        with patch.object(L10nBoSiatProvider, '_siat_emit_demo', fail):
            move = self._invoice()
        self.assertEqual(move.state, 'posted')  # nunca bloquea la validación
        self.assertEqual(move.l10n_bo_siat_state, 'to_send')
        self.assertEqual(move.l10n_bo_siat_attempts, 1)
        self.assertIn('Tiempo de espera agotado', move.l10n_bo_siat_log)
        self.assertFalse(move.l10n_bo_siat_cuf)
        self.env['account.move']._cron_l10n_bo_siat_process()
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')
        self.assertTrue(move.l10n_bo_siat_cuf)

    def test_retry_limit_stops_cron_and_asks_review(self):
        self._use_demo()
        self.company.l10n_bo_siat_retry_limit = 1

        def fail(provider, move):
            raise L10nBoSiatTransientError('Servicio caído')

        with patch.object(L10nBoSiatProvider, '_siat_emit_demo', fail):
            move = self._invoice()
        self.assertTrue(self._activities(move, REVIEW))
        self.env['account.move']._cron_l10n_bo_siat_process()
        self.assertEqual(move.l10n_bo_siat_state, 'to_send', 'Superado el límite, la tarea programada ya no reintenta.')
        move.action_l10n_bo_siat_send()  # el usuario reintenta a mano
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')
        self.assertFalse(self._activities(move, REVIEW))

    def test_provider_local_validation_rejects_anonymous_over_limit(self):
        self._use_demo()
        move = self._invoice(price=1500.0)
        self.assertEqual(move.l10n_bo_siat_state, 'rejected')
        self.assertIn('identifique al comprador', move.l10n_bo_siat_log)
        self.assertTrue(self._activities(move, REVIEW))
        self.assertTrue(move.l10n_bo_siat_warning)
        move.write({'l10n_bo_sale_buyer_doc_type': '1', 'l10n_bo_sale_buyer_number': '4789632',
                    'l10n_bo_sale_buyer_complement': '1f', 'l10n_bo_sale_buyer_name': 'Ana Pérez'})
        self.assertEqual(move.l10n_bo_sale_buyer_complement, '1F')
        move.action_l10n_bo_siat_send()
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')

    # ------------------------------------------------------------------
    # Portal Web del SIN (registro manual)
    # ------------------------------------------------------------------
    def test_portal_web_post_leaves_to_send_with_activity(self):
        move = self._invoice()
        self.assertEqual(move.l10n_bo_siat_state, 'to_send')
        self.assertEqual(move.l10n_bo_siat_mode, 'portal_web')
        activity = self._activities(move, REGISTER)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.env.user)
        self.assertIn('S/N', activity.note)
        self.assertIn('Portal Web', move.l10n_bo_siat_warning)
        # Responsable configurado en la compañía.
        cashier = self.env['res.users'].create({
            'name': 'Cajera', 'login': 'cajera_siat', 'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, self.env.ref('account.group_account_invoice').ids)],
        })
        self.company.l10n_bo_siat_user_id = cashier
        self.assertEqual(self._activities(self._invoice(), REGISTER).user_id, cashier)

    def test_portal_web_never_blocks_posting_without_nit(self):
        self.company.vat = False
        move = self._invoice()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.l10n_bo_siat_state, 'to_send')
        self.assertIn('NIT de la compañía', move.l10n_bo_siat_warning)
        with self.assertRaisesText(UserError, 'NIT de la compañía'):
            self._register(move, 15)

    def test_portal_web_register_accepts(self):
        move = self._invoice()
        when = self._local_now() - timedelta(minutes=5)
        cuf = self._cuf(15, when=when)
        wizard = self._register(move, '0015', cuf=cuf.lower())
        self.assertIn('CUF válido', wizard.check_message)
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')
        self.assertEqual(move.l10n_bo_siat_number, '15')
        self.assertEqual(move.l10n_bo_siat_cuf, cuf)
        self.assertFalse(move.l10n_bo_siat_simulated)
        # La fecha de emisión se toma del CUF (hora de Bolivia → UTC, +4 h).
        self.assertEqual(move.l10n_bo_siat_emission_date, when.replace(microsecond=0) + timedelta(hours=4))
        self.assertFalse(self._activities(move, REGISTER))
        self.assertTrue(move.need_cancel_request)
        self.assertFalse(move.show_reset_to_draft_button)
        with self.assertRaisesText(UserError, 'Anular en SIAT'):
            move.button_draft()
        with self.assertRaisesText(UserError, 'ya fue emitida'):
            move.l10n_bo_sale_buyer_number = '123'

    def test_register_updates_buyer_data(self):
        move = self._invoice()
        self._register(move, 16, buyer_doc_type='5', buyer_number=OTHER_NIT, buyer_name='Hotel Illimani SRL')
        self.assertEqual(move.l10n_bo_sale_buyer_doc_type, '5')
        self.assertEqual(move.l10n_bo_sale_buyer_number, OTHER_NIT)
        self.assertEqual(move.l10n_bo_sale_buyer_name, 'Hotel Illimani SRL')

    def test_register_from_qr_link(self):
        move = self._invoice()
        cuf = self._cuf(21)
        action = move.action_l10n_bo_siat_open_register()
        wizard = self.env['l10n_bo.siat.register.wizard'].browse(action['res_id'])
        wizard.qr_text = 'https://siat.impuestos.gob.bo/consulta/QR?nit=%s&cuf=%s&numero=21&t=2' % (COMPANY_NIT, cuf)
        wizard._onchange_qr_text()
        self.assertEqual(wizard.siat_number, '21')
        self.assertEqual(wizard.cuf, cuf)
        wizard.action_confirm()
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')

    def test_register_duplicate_cuf_rejected(self):
        first = self._invoice()
        cuf = self._cuf(30)
        self._register(first, 30, cuf=cuf)
        second = self._invoice()
        with self.assertRaisesText(UserError, first.name):
            self._register(second, 30, cuf=cuf)
        self.assertEqual(second.l10n_bo_siat_state, 'to_send')
        # Mismo número con otro CUF tampoco.
        with self.assertRaisesText(UserError, 'n.º 30 ya está registrada'):
            self._register(second, 30, cuf=self._cuf(30, when=self._local_now() - timedelta(hours=1)))

    def test_cuf_unique_index_in_database(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'account_move_l10n_bo_siat_cuf_unique'")
        definition = self.env.cr.fetchone()[0]
        self.assertIn('UNIQUE', definition)
        self.assertIn('company_id', definition)

    def test_register_cuf_mismatch_rejected(self):
        move = self._invoice()
        with self.assertRaisesText(UserError, 'NIT %s' % OTHER_NIT):
            self._register(move, 40, cuf=self._cuf(40, nit=OTHER_NIT))
        with self.assertRaisesText(UserError, 'n.º 41'):
            self._register(move, 40, cuf=self._cuf(41))
        with self.assertRaisesText(UserError, 'hexadecimal'):
            self._register(move, 40, cuf='XYZ-NO-ES-CUF')
        # Hexadecimal plausible que no se puede decodificar: aceptado solo con validación no estricta.
        opaque = 'ABCDEF0123456789ABCDEF0123456789ABCDEF0123'
        self.company.l10n_bo_siat_cuf_check = 'strict'
        with self.assertRaisesText(UserError, 'módulo 11'):
            self._register(move, 40, cuf=opaque)
        self.company.l10n_bo_siat_cuf_check = 'decodable'
        self._register(move, 40, cuf=opaque)
        self.assertEqual(move.l10n_bo_siat_state, 'accepted')
        self.assertIn('solo el formato', move.l10n_bo_siat_log)

    # ------------------------------------------------------------------
    # Compañía no habilitada
    # ------------------------------------------------------------------
    def test_mode_none_not_applicable(self):
        self.company.l10n_bo_siat_mode = 'none'
        move = self._invoice()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.l10n_bo_siat_state, 'not_applicable')
        self.assertFalse(move.activity_ids)
        self.assertIn('no habilitada', move.l10n_bo_siat_warning)
        self.assertIn('SIN factura del SIN', move.l10n_bo_siat_warning)
        draft = self._invoice(post=False)
        self.assertIn('no habilitada', draft.l10n_bo_siat_warning)
        self.assertFalse(self._book(move))
        with self.assertRaises(UserError):
            move.action_l10n_bo_siat_open_register()

    # ------------------------------------------------------------------
    # Venta sin factura
    # ------------------------------------------------------------------
    def test_no_invoice_requires_group(self):
        self.env.user.group_ids -= self.no_invoice_group
        self.assertFalse(self.env.user.has_group('l10n_bo_siat_edi.group_l10n_bo_sale_no_invoice'))
        with self.assertRaisesText(UserError, 'Ventas sin factura (autorizado)'):
            self._invoice(post=False, l10n_bo_sale_doc='no_invoice')
        move = self._invoice(post=False)
        with self.assertRaisesText(UserError, 'Ventas sin factura (autorizado)'):
            move.l10n_bo_sale_doc = 'no_invoice'
        self.assertFalse(move.l10n_bo_sale_user_can_no_invoice)

        self.env.user.group_ids |= self.no_invoice_group
        move = self._invoice(post=False, l10n_bo_sale_doc='no_invoice')
        with self.assertRaisesText(UserError, 'motivo'):
            move.action_post()
        move.l10n_bo_sale_no_invoice_reason = 'Caso confirmado por el contador'
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.l10n_bo_siat_state, 'not_applicable')
        self.assertEqual(move.l10n_bo_sale_no_invoice_user_id, self.env.user)
        self.assertFalse(move.activity_ids)
        # Los impuestos se registran igual: IVA débito 13 % y el IT.
        iva = move.line_ids.filtered(lambda l: l.tax_line_id == self.ct.ref('l10n_bo_iva_13_sale'))
        self.assertAlmostEqual(-iva.balance, 115.70, places=2)
        self.assertTrue(move.line_ids.filtered(lambda l: l.tax_line_id and 'IT' in l.tax_line_id.tax_group_id.name))
        self.assertFalse(self._book(move))
        action = self.env.ref('l10n_bo_siat_edi.action_l10n_bo_sale_no_invoice')
        self.assertIn(move, self.env['account.move'].search(literal_eval(action.domain)))

    def test_no_invoice_max_amount(self):
        self.env.user.group_ids |= self.no_invoice_group
        self.company.l10n_bo_sale_no_invoice_max = 500.0
        move = self._invoice(post=False, l10n_bo_sale_doc='no_invoice', l10n_bo_sale_no_invoice_reason='Prueba')
        with self.assertRaisesText(UserError, 'supera el máximo'):
            move.action_post()
        small = self._invoice(price=450.0, post=False, l10n_bo_sale_doc='no_invoice', l10n_bo_sale_no_invoice_reason='Prueba')
        small.action_post()
        self.assertEqual(small.state, 'posted')
        self.company.l10n_bo_sale_no_invoice_max = 0.0  # sin límite
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_no_invoice_cannot_switch_when_posted(self):
        self.env.user.group_ids |= self.no_invoice_group
        move = self._invoice()
        with self.assertRaisesText(UserError, 'restablézcalo a borrador'):
            move.write({'l10n_bo_sale_doc': 'no_invoice', 'l10n_bo_sale_no_invoice_reason': 'x'})

    # ------------------------------------------------------------------
    # Anulación
    # ------------------------------------------------------------------
    def test_cancel_portal_web_creates_reversal(self):
        move = self._invoice()
        self._register(move, 50)
        action = move.action_l10n_bo_siat_open_cancel()
        wizard = self.env['l10n_bo.siat.cancel.wizard'].browse(action['res_id'])
        self.assertFalse(wizard.uses_provider)
        self.assertTrue(wizard.deadline)
        wizard.reason_id = self.reason
        with self.assertRaisesText(UserError, 'Portal Web del SIN'):
            wizard.action_confirm()
        reversal = self._cancel(move, manual=True)
        self.assertEqual(move.l10n_bo_siat_state, 'cancelled')
        self.assertEqual(move.l10n_bo_siat_cancel_reason_id, self.reason)
        self.assertTrue(move.l10n_bo_siat_cancel_date)
        self.assertEqual(len(reversal), 1)
        self.assertEqual(reversal.move_type, 'out_refund')
        self.assertEqual(reversal.state, 'posted')
        self.assertTrue(reversal.l10n_bo_siat_cancel_reversal)
        self.assertEqual(reversal.l10n_bo_siat_state, 'not_applicable')
        self.assertFalse(reversal.activity_ids)
        self.assertEqual(move.payment_state, 'reversed')
        self.assertAlmostEqual(reversal.amount_total, move.amount_total)
        # Contabilidad consistente: la reversión anula ingreso, IVA e IT.
        balances = {}
        for line in (move | reversal).line_ids:
            balances[line.account_id] = balances.get(line.account_id, 0.0) + line.balance
        self.assertTrue(all(abs(b) < 0.001 for b in balances.values()))
        with self.assertRaisesText(UserError, 'Anular en SIAT'):
            move.button_draft()

    def test_cancel_demo_paid_invoice_leaves_customer_credit(self):
        self._use_demo()
        move = self._invoice()
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({})._create_payments()
        self.assertIn(move.payment_state, ('paid', 'in_payment'))
        reversal = self._cancel(move, manual=False)
        self.assertEqual(move.l10n_bo_siat_state, 'cancelled')
        self.assertIn('SIMULADO', move.l10n_bo_siat_log)
        self.assertEqual(move.payment_state, 'reversed')
        self.assertEqual(reversal.l10n_bo_siat_state, 'not_applicable')
        receivable = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertAlmostEqual(receivable.amount_residual, -890.0, places=2)

    def test_cancel_deadline(self):
        move = self._invoice()
        self._register(move, 60)
        move.l10n_bo_siat_emission_date = fields.Datetime.now() - timedelta(days=75)
        with self.assertRaisesText(UserError, 'plazo'):
            move.action_l10n_bo_siat_open_cancel()
        self.company.l10n_bo_siat_cancel_day = 0
        self._cancel(move)
        self.assertEqual(move.l10n_bo_siat_state, 'cancelled')

    def test_cancel_deadline_day_of_next_month(self):
        move = self._invoice()
        self._register(move, 61)
        move.l10n_bo_siat_emission_date = '2026-01-30 15:00:00'
        self.assertEqual(str(move._l10n_bo_siat_cancel_deadline()), '2026-02-09')
        self.company.l10n_bo_siat_cancel_day = 31
        self.assertEqual(str(move._l10n_bo_siat_cancel_deadline()), '2026-02-28')

    def test_only_accepted_can_be_cancelled(self):
        move = self._invoice()
        with self.assertRaisesText(UserError, 'aceptadas'):
            move.action_l10n_bo_siat_open_cancel()

    def test_refund_of_accepted_invoice_is_a_siat_document(self):
        move = self._invoice(partner=self.customer_nit)
        self._register(move, 70)
        reversal_wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=move.ids).create({'journal_id': move.journal_id.id, 'reason': 'Devolución'})
        refund = self.env['account.move'].browse(reversal_wizard.refund_moves()['res_id'])
        self.assertEqual(refund.l10n_bo_sale_doc, 'siat')
        self.assertEqual(refund.l10n_bo_sale_buyer_number, OTHER_NIT)
        refund.action_post()
        self.assertEqual(refund.l10n_bo_siat_state, 'to_send')
        self.assertFalse(self._book(refund), 'Las notas de crédito-débito no van al Libro de Ventas.')

    def test_reset_to_draft_clears_pending_state(self):
        move = self._invoice()
        self.assertTrue(self._activities(move, REGISTER))
        move.button_draft()
        self.assertFalse(move.l10n_bo_siat_state)
        self.assertFalse(self._activities(move, REGISTER))
        move.action_post()
        self.assertEqual(move.l10n_bo_siat_state, 'to_send')

    # ------------------------------------------------------------------
    # Comprador y configuración
    # ------------------------------------------------------------------
    def test_buyer_defaults(self):
        anonymous = self._invoice(post=False)
        self.assertEqual(anonymous.l10n_bo_sale_buyer_doc_type, '1')
        self.assertEqual(anonymous.l10n_bo_sale_buyer_number, '0')
        self.assertEqual(anonymous.l10n_bo_sale_buyer_name, 'S/N')
        company_buyer = self._invoice(post=False, partner=self.customer_nit)
        self.assertEqual(company_buyer.l10n_bo_sale_buyer_doc_type, '5')
        self.assertEqual(company_buyer.l10n_bo_sale_buyer_number, OTHER_NIT)
        self.assertEqual(company_buyer.l10n_bo_sale_buyer_name, 'Hotel Illimani SRL')
        person = self.env['res.partner'].create({
            'name': 'Luis Quispe', 'vat': '4.789.632', 'l10n_bo_siat_id_type': '1', 'l10n_bo_siat_id_complement': '1F'})
        ci_buyer = self._invoice(post=False, partner=person)
        self.assertEqual(ci_buyer.l10n_bo_sale_buyer_doc_type, '1')
        self.assertEqual(ci_buyer.l10n_bo_sale_buyer_number, '4789632')
        self.assertEqual(ci_buyer.l10n_bo_sale_buyer_complement, '1F')
        # Consumidor final configurable.
        self.company.write({'l10n_bo_siat_buyer_number': '99001', 'l10n_bo_siat_buyer_name': 'Sin nombre'})
        configured = self._invoice(post=False)
        self.assertEqual(configured.l10n_bo_sale_buyer_number, '99001')
        self.assertEqual(configured.l10n_bo_sale_buyer_name, 'Sin nombre')

    def test_buyer_errors(self):
        move = self._invoice(post=False, partner=self.customer_nit)
        move.write({'l10n_bo_sale_buyer_number': '12A', 'l10n_bo_sale_buyer_complement': '1F'})
        errors = ' '.join(move._l10n_bo_siat_buyer_errors())
        self.assertIn('solo dígitos', errors)
        self.assertIn('complemento solo se admite', errors)

    def test_settings_require_nit_and_provider(self):
        self.company.write({'vat': False, 'l10n_bo_siat_mode': 'none'})
        with self.assertRaisesText(ValidationError, 'NIT'):
            self.env['res.config.settings'].create({'l10n_bo_siat_mode': 'portal_web'})
        self.company.vat = COMPANY_NIT
        with self.assertRaisesText(ValidationError, 'proveedor'):
            self.env['res.config.settings'].create({'l10n_bo_siat_mode': 'provider'})
        self.env['res.config.settings'].create({'l10n_bo_siat_mode': 'provider', 'l10n_bo_siat_provider_id': self.demo.id})
        self.assertEqual(self.company.l10n_bo_siat_mode, 'provider')
        self.assertIn('SIMULADOR', self.company.l10n_bo_siat_warning)
        # Guardar otros ajustes sin cambiar la modalidad no exige el NIT.
        self.company.write({'vat': False, 'l10n_bo_siat_mode': 'portal_web'})
        self.env['res.config.settings'].create({'l10n_bo_siat_cancel_day': 10})
        self.assertEqual(self.company.l10n_bo_siat_cancel_day, 10)

    def test_provider_of_other_company_rejected(self):
        other = self.env['res.company'].create({'name': 'Otra compañía'})
        foreign = self.env['l10n_bo.siat.provider'].sudo().create({'name': 'Ajeno', 'company_id': other.id})
        with self.assertRaises(ValidationError):
            self.company.l10n_bo_siat_provider_id = foreign
