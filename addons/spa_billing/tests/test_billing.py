# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestBilling(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.chart = cls.env['account.chart.template']
        cls.Request = cls.env['spa.payment.request']
        cls.Message = cls.env['spa.message']

    def _new_member(self, plan, months=1, offer=None, partner=None):
        membership = self._membership(plan, months=months, activate=False, partner=partner)
        if offer:
            membership.offer_id = offer
        return membership, membership.action_create_invoice()

    def _pay(self, invoice, amount=None, method='qr'):
        request = self.Request.create({
            'partner_id': invoice.partner_id.id, 'membership_id': invoice.spa_membership_id.id,
            'invoice_id': invoice.id, 'amount': amount or invoice.amount_residual, 'method': method,
            'reference': 'TRX-001'})
        request.action_validate()
        return request

    def _code(self, xmlid):
        return self.chart.ref(xmlid).code

    def test_new_member_monthly_flow(self):
        membership, invoice = self._new_member(self.plan_premium)
        self.assertEqual(membership.state, 'draft')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_total, 890.0)
        income = invoice.line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertEqual(income.account_id.code, '410110')
        iva = invoice.line_ids.filtered(lambda l: l.account_id.code == '213500')
        self.assertAlmostEqual(-iva.balance, 115.7, places=2)  # 13 % de 890
        request = self._pay(invoice)
        self.assertEqual(request.state, 'validated')
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertEqual(membership.state, 'active')
        self.assertTrue(invoice.spa_period_applied)
        message = self.Message.search([('partner_id', '=', self.partner.id), ('template_id.code', '=', 'payment_validated')])
        self.assertTrue(message)

    def test_annual_plan_deferred_revenue(self):
        membership, invoice = self._new_member(self.plan_premium, months=12)
        deferred = invoice.line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertEqual(deferred.account_id.code, '215100')
        self._pay(invoice)
        self.assertEqual(membership.state, 'active')
        lines = membership.deferral_line_ids
        self.assertEqual(len(lines), 12)
        self.assertAlmostEqual(sum(lines.mapped('amount')), -deferred.balance, places=2)
        self.assertEqual(lines[0].date, self.today)
        self.env['spa.deferral.line']._cron_post_deferrals()
        posted = lines.filtered(lambda l: l.state == 'posted')
        self.assertEqual(len(posted), 1)
        move = posted.move_id
        self.assertEqual(move.journal_id.code, 'DIFE')
        self.assertEqual(move.line_ids.filtered(lambda l: l.debit).account_id.code, '215100')
        self.assertEqual(move.line_ids.filtered(lambda l: l.credit).account_id.code, '410110')

    def test_discount_offer(self):
        offer = self.env.ref('spa_billing.offer_annual_discount')
        membership, invoice = self._new_member(self.plan_basic, months=12, offer=offer)
        self.assertEqual(invoice.invoice_line_ids.discount, 10.0)
        self.assertAlmostEqual(invoice.amount_total, 4590.0 * 0.9, places=2)
        self.assertEqual(invoice.spa_offer_id, offer)

    def test_installments_activate_on_first_payment(self):
        offer = self.env.ref('spa_billing.offer_annual_installments')
        membership, invoice = self._new_member(self.plan_vip, months=12, offer=offer)
        self.assertEqual(len(invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')), 3)
        first = round(invoice.amount_total / 3, 2)
        self._pay(invoice, amount=first)
        self.assertIn(invoice.payment_state, ('partial', 'in_payment'))
        self.assertEqual(membership.state, 'active')
        self.assertEqual(membership.date_end, self.today + relativedelta(months=12) - timedelta(days=1))
        # La segunda cuota no vuelve a extender la membresía
        self._pay(invoice, amount=first)
        self.assertEqual(membership.date_end, self.today + relativedelta(months=12) - timedelta(days=1))

    def test_payment_validation_rules(self):
        membership, invoice = self._new_member(self.plan_basic)
        with self.assertRaisesRegex(UserError, 'supera el saldo'):
            self._pay(invoice, amount=invoice.amount_total + 1)
        request = self.Request.create({'partner_id': self.partner.id, 'invoice_id': invoice.id,
                                       'amount': 450, 'method': 'transfer'})
        with self.assertRaisesRegex(UserError, 'motivo'):
            request.action_reject()
        request.reject_reason = 'Comprobante ilegible'
        request.action_reject()
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(membership.state, 'draft')
        self.assertTrue(self.Message.search([('template_id.code', '=', 'payment_rejected'),
                                             ('partner_id', '=', self.partner.id)]))

    def test_cash_payment_uses_cash_journal(self):
        membership, invoice = self._new_member(self.plan_basic)
        request = self._pay(invoice, method='cash')
        self.assertEqual(request.payment_id.journal_id.type, 'cash')

    def test_renewal_cycle(self):
        membership, invoice = self._new_member(self.plan_basic)
        self._pay(invoice)
        membership.date_end = self.today + timedelta(days=3)
        self.env['spa.membership']._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertEqual(renewal.spa_invoice_kind, 'renewal')
        self.assertTrue(self.Message.search([('template_id.code', '=', 'renewal_notice'),
                                             ('partner_id', '=', self.partner.id)]))
        # El cron no duplica la factura
        self.env['spa.membership']._cron_billing_daily()
        self.assertEqual(len(membership.invoice_ids.filtered(lambda m: m.spa_invoice_kind == 'renewal')), 1)
        self._pay(renewal)
        self.assertEqual(membership.date_end, self.today + timedelta(days=3) + relativedelta(months=1))

    def test_grace_and_suspension_notices(self):
        membership, invoice = self._new_member(self.plan_basic)
        self._pay(invoice)
        membership.date_end = self.today - timedelta(days=1)
        self.env['spa.membership']._cron_membership_daily()
        self.assertEqual(membership.state, 'grace')
        self.assertTrue(self.Message.search([('template_id.code', '=', 'grace_notice'),
                                             ('partner_id', '=', self.partner.id)]))
        membership.date_end = self.today - timedelta(days=30)
        self.env['spa.membership']._cron_membership_daily()
        self.assertEqual(membership.state, 'suspended')
        self.assertTrue(self.Message.search([('template_id.code', '=', 'suspended_notice'),
                                             ('partner_id', '=', self.partner.id)]))

    def test_guest_fee_charge_and_cancel(self):
        membership, invoice = self._new_member(self.plan_basic)  # 1 invitado gratis
        self._pay(invoice)
        Guest = self.env['spa.guest']
        free = Guest.create({'name': 'Gratis', 'membership_id': membership.id, 'service_id': self.pool.id})
        paid = Guest.create({'name': 'Con tarifa', 'membership_id': membership.id, 'service_id': self.pool.id})
        self.assertFalse(free.charge_line_id)
        self.assertTrue(paid.charge_line_id)
        charges = paid.charge_line_id.move_id
        self.assertEqual(charges.spa_invoice_kind, 'charges')
        self.assertEqual(charges.state, 'draft')
        self.assertEqual(paid.charge_line_id.account_id.code, '410140')
        area = str(self.env.ref('l10n_bo_spa.analytic_area_piscina').id)
        self.assertIn(area, paid.charge_line_id.analytic_distribution)
        paid.action_cancel()
        self.assertFalse(charges.exists())

    def test_no_show_fee_vip(self):
        membership, invoice = self._new_member(self.plan_vip)
        self._pay(invoice)
        day = self.today + timedelta(days=2)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': membership.id, 'payment_mode': 'membership',
            'service_id': self.massage.id, 'start': self._dt(day, 10.0)})
        booking.action_confirm()
        past = fields.Datetime.now() - timedelta(hours=3)
        booking.write({'start': past, 'stop': past + timedelta(hours=1)})
        self.env['spa.booking']._cron_booking_states()
        self.assertEqual(booking.state, 'no_show')
        self.assertEqual(sum(booking.consumption_ids.mapped('qty')), 0, 'Con penalidad, la sesión se devuelve')
        charges = self.env['account.move'].search([('partner_id', '=', self.partner.id),
                                                   ('spa_invoice_kind', '=', 'charges')])
        self.assertEqual(charges.invoice_line_ids.account_id.code, '410190')

    def test_single_booking_invoice(self):
        walk_in = self.env['res.partner'].create({'name': 'Cliente de paso'})
        booking = self.env['spa.booking'].create({
            'partner_id': walk_in.id, 'payment_mode': 'single', 'service_id': self.massage.id,
            'start': self._dt(self.today + timedelta(days=2), 11.0)})
        booking.action_confirm()
        invoice = booking.invoice_id
        self.assertEqual(invoice.amount_total, 280.0)
        self.assertEqual(invoice.invoice_line_ids.account_id.code, '410130')
        area = str(self.env.ref('l10n_bo_spa.analytic_area_spa').id)
        self.assertIn(area, invoice.invoice_line_ids.analytic_distribution)
        request = self.Request.create({'partner_id': walk_in.id, 'invoice_id': invoice.id,
                                       'amount': 280.0, 'method': 'cash'})
        request.action_validate()
        self.assertEqual(booking.payment_state, 'paid')

    def test_old_charges_posted_by_cron(self):
        membership, invoice = self._new_member(self.plan_basic)
        self._pay(invoice)
        line = membership._spa_add_charge(self.env.ref('spa_membership.product_penalty_no_show'), name='Penalidad')
        charges = line.move_id
        charges.invoice_date = self.today - relativedelta(months=1)
        self.env['spa.membership']._cron_billing_daily()
        self.assertEqual(charges.state, 'posted')

    def test_booking_reminder(self):
        membership, invoice = self._new_member(self.plan_premium)
        self._pay(invoice)
        start = fields.Datetime.now() + timedelta(hours=24)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': membership.id, 'payment_mode': 'membership',
            'service_id': self.pool.id, 'start': start, 'state': 'confirmed'})
        self.env['spa.booking']._cron_booking_reminders()
        self.assertTrue(booking.reminder_sent)
        self.assertTrue(self.Message.search([('template_id.code', '=', 'booking_reminder'),
                                             ('res_id', '=', booking.id)]))
