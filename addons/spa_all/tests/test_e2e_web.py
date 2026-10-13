# Part of ERP Servicios Spa. License LGPL-3.
"""Cara al cliente: alta web, pago con comprobante, reservas en el portal, consumo del
restaurante pagado desde la web, suspensión visible en el portal y aislamiento entre socios."""
from datetime import date, timedelta
from urllib.parse import urlparse

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.tests import HttpCase, freeze_time, tagged
from odoo.tools import mute_logger

from .common import DAY0, PNG_1PX, START, SpaE2EMixin, utc_at

WED, THU = DAY0 + timedelta(days=1), DAY0 + timedelta(days=2)


@tagged('post_install', '-at_install', 'spa', 'spa_e2e')
@freeze_time(START)
class TestSpaE2EWeb(SpaE2EMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()
        cls.website = cls.env.ref('website.default_website')
        assert cls.website.company_id == cls.company
        cls.lucia = cls._portal_member('e2e_lucia', 'Lucía Fernández')
        cls.mateo = cls._portal_member('e2e_mateo', 'Mateo Gutiérrez', phone='+591 72000002')
        cls.coffee = cls.env.ref('spa_pos.product_coffee')
        cls.salad = cls.env.ref('spa_pos.product_salad')
        cls.trout = cls.env.ref('spa_pos.product_trout')
        cls.member_account = cls.env.ref('spa_pos.pm_member_account')
        cls.restaurant = cls.env['pos.config']._spa_get_config('restaurant')

    # ------------------------------------------------------------------
    # Utilidades HTTP
    # ------------------------------------------------------------------
    def _login(self, user):
        self.authenticate(user.login, user.login)

    def _post(self, url, data=None, files=None):
        data = dict(data or {}, csrf_token=http.Request.csrf_token(self))
        return self.url_open(url, data=data, files=files, allow_redirects=False)

    def _assert_redirect(self, response, path, query=None):
        self.assertIn(response.status_code, (302, 303), response.text[:800])
        location = urlparse(response.headers['Location'])
        self.assertEqual(location.path, path)
        if query:
            self.assertIn(query, location.query)

    def _slot(self, day, hour, minute=0):
        return fields.Datetime.to_string(utc_at(day, hour, minute))

    def _submit_receipt(self, invoice, amount, method='qr', reference='QR-E2E'):
        return self._post('/my/spa/pay/%s/submit' % invoice.id,
                          {'method': method, 'amount': amount, 'reference': reference},
                          files={'receipt': ('comprobante.png', PNG_1PX, 'image/png')})

    # ==================================================================
    # 3. Alta en la web → pago con comprobante → caja valida
    # ==================================================================
    def test_03_web_signup_payment_activation(self):
        web = self.env.ref('spa_crm.utm_source_web')
        lead = self.env['crm.lead'].with_user(self.marketing).create({
            'name': 'Consulta web: Lucía Fernández', 'contact_name': 'Lucía Fernández',
            'email_from': self.lucia.email, 'source_id': web.id}).sudo()
        self.assertEqual(lead.team_id, self.team_acq)

        self._login(self.lucia)
        response = self.url_open('/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Premium', response.text)
        period = self._period(self.plan_premium, 1)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id,
                              {'option': '%s:0' % period.id, 'phone': '+591 71234567'})
        membership = self.env['spa.membership'].search([('partner_id', '=', self.lucia.partner_id.id)])
        self.assertEqual(len(membership), 1)
        self.assertEqual(membership.state, 'draft')
        invoice = membership.invoice_ids
        self.assertRecordValues(invoice, [{'state': 'draft', 'spa_invoice_kind': 'membership',
                                           'amount_total': 890.0, 'invoice_date': DAY0}])
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id)
        response = self.url_open('/my/spa/pay/%s' % invoice.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Banco Unión', response.text)
        response = self.url_open('/my/spa/pay/%s/qr' % invoice.id)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        self.assertNotIn(membership.qr_token, self.url_open('/my/spa').text, 'Sin pago no hay credencial')

        # Un comprobante equivocado: caja lo rechaza con el motivo y se avisa por WhatsApp.
        response = self._submit_receipt(invoice, '890', reference='QR-000001')
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=received')
        wrong = self.env['spa.payment.request'].search([('invoice_id', '=', invoice.id)])
        wrong.with_user(self.cashier).write({'reject_reason': 'El comprobante es de otra cuenta'})
        wrong.with_user(self.cashier).action_reject()
        self.assertEqual(wrong.state, 'rejected')
        self.assertIn('otra cuenta', self._messages(self.lucia.partner_id, 'payment_rejected').body)
        self.assertEqual(membership.state, 'draft')
        response = self._submit_receipt(invoice, '890,00', reference='QR-778899')
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=received')
        request = self.env['spa.payment.request'].search([('invoice_id', '=', invoice.id), ('state', '=', 'pending')])
        self.assertRecordValues(request, [{'state': 'pending', 'channel': 'portal', 'method': 'qr',
                                           'amount': 890.0, 'membership_id': membership.id}])
        self.assertTrue(request.receipt)
        # Recepción no valida pagos; caja sí.
        with self._raises(UserError, 'Solo caja'):
            request.with_user(self.reception).action_validate()
        self.env.invalidate_all()
        request.with_user(self.cashier).action_validate()
        self.env.invalidate_all()
        self.assertEqual(request.state, 'validated')
        self.assertEqual(request.validated_by_id, self.cashier)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertEqual(request.payment_id.journal_id, self.bank_journal)
        self.assertRecordValues(membership, [{'state': 'active', 'date_start': DAY0, 'date_end': date(2027, 4, 1)}])
        march = membership.entitlement_ids.filtered(lambda e: e.period_start == date(2027, 3, 1))
        self.assertEqual(march.service_id, self.pool | self.sauna | self.massage | self.jacuzzi)
        self.assertEqual(march.filtered(lambda e: e.service_id == self.massage).remaining, 4)
        message = self._messages(self.lucia.partner_id, 'payment_validated')
        self.assertEqual(len(message), 1)
        self.assertEqual(message.phone, '59171234567')
        self.assertIn('01/04/2027', message.body)
        self.assertEqual(lead.won_status, 'won')
        self.assertEqual(lead.stage_id.spa_stage_code, 'member')
        self.assertEqual(lead.spa_membership_id, membership)
        self.assertEqual(self.lucia.partner_id.property_product_pricelist, self.plan_premium.pricelist_id)
        response = self.url_open('/my/spa')
        self.assertIn('/report/barcode/QR/%s' % membership.qr_token, response.text)
        self.assertIn('4 de 4', response.text)

    # ==================================================================
    # 4. Reservas desde el portal
    # ==================================================================
    def test_04_portal_booking_rules(self):
        m_lucia = self._enroll(self.lucia.partner_id, self.plan_premium)
        self._enroll(self.mateo.partner_id, self.plan_premium)
        self._login(self.lucia)
        response = self.url_open('/my/spa/book?service_id=%s&day=%s' % (self.massage.id, WED))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Te quedan 4 de 4', response.text)
        start = self._slot(WED, 10)
        self.assertIn(start, response.text)
        response = self._post('/my/spa/book/confirm', {'service_id': self.massage.id, 'day': str(WED),
                                                        'guests': 0, 'start': start})
        self._assert_redirect(response, '/my/spa', 'msg=booked')
        booking = self.env['spa.booking'].search([('partner_id', '=', self.lucia.partner_id.id)])
        self.assertRecordValues(booking, [{'state': 'confirmed', 'channel': 'portal', 'membership_id': m_lucia.id,
                                           'employee_id': self.therapist_employee.id}])
        self.assertEqual(self._remaining(m_lucia, self.massage, WED), 3)
        # Otro socio no puede tomar la misma franja (cabina y masajista ocupados).
        self._login(self.mateo)
        response = self._post('/my/spa/book/confirm', {'service_id': self.massage.id, 'day': str(WED),
                                                        'guests': 0, 'start': start})
        self.assertEqual(response.status_code, 200)
        self.assertIn('ya no está disponible', response.text)
        self.assertFalse(self.env['spa.booking'].search([('partner_id', '=', self.mateo.partner_id.id)]))
        response = self._post('/my/spa/book/confirm', {'service_id': self.massage.id, 'day': str(WED),
                                                        'guests': 0, 'start': self._slot(WED, 11)})
        self._assert_redirect(response, '/my/spa', 'msg=booked')
        # Tope semanal de Lucía: 1 masaje por semana.
        self._login(self.lucia)
        response = self.url_open('/my/spa/book?service_id=%s&day=%s' % (self.massage.id, THU))
        self.assertIn('por semana y ya los us', response.text)
        response = self._post('/my/spa/book/confirm', {'service_id': self.massage.id, 'day': str(THU),
                                                        'guests': 0, 'start': self._slot(THU, 10)})
        self.assertEqual(response.status_code, 200)
        self.assertIn('ya no está disponible', response.text)
        # Jacuzzi con un invitado (free pass) desde la web: el invitado queda como prospecto referido.
        response = self._post('/my/spa/book/confirm', {
            'service_id': self.jacuzzi.id, 'day': str(THU), 'guests': 1, 'start': self._slot(THU, 11),
            'guest_name_0': 'Pedro Invitado', 'guest_phone_0': '+591 70011122'})
        self._assert_redirect(response, '/my/spa', 'msg=booked')
        jacuzzi = self.env['spa.booking'].search([('partner_id', '=', self.lucia.partner_id.id),
                                                  ('service_id', '=', self.jacuzzi.id)])
        self.assertEqual(jacuzzi.seats, 2)
        guest = jacuzzi.guest_ids
        self.assertEqual(guest.charge_type, 'free_pass')
        self.assertEqual(guest.lead_id.referred_by_partner_id, self.lucia.partner_id)
        response = self.url_open('/my/spa/guests')
        self.assertIn('Pedro Invitado', response.text)
        # Cancelación con anticipación desde la web: la sesión vuelve al saldo.
        response = self._post('/my/spa/booking/%s/cancel' % booking.id)
        self._assert_redirect(response, '/my/spa', 'msg=cancelled')
        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(self._remaining(m_lucia, self.massage, WED), 4)

    # ==================================================================
    # 7. Restaurante: precio de socio, cuenta del socio y pago desde la web
    # ==================================================================
    def test_07_restaurant_member_account_paid_from_portal(self):
        membership = self._enroll(self.lucia.partner_id, self.plan_premium)
        lucia = self.lucia.partner_id
        session = self._pos_open(self.restaurant)
        self.assertEqual(session.state, 'opened')
        self.assertEqual(session.user_id, self.waiter)
        order = self._pos_order(self.restaurant, [(self.coffee, 1), (self.salad, 1)], partner=lucia,
                                payments=[(self.member_account, None)])
        self.assertEqual(order.pricelist_id, self.plan_premium.pricelist_id)
        self.assertEqual(order.lines.mapped('price_unit'), [13.5, 40.5], 'Premium: 10 % en restaurante')
        self.assertAlmostEqual(order.amount_total, 54.0)
        invoice = order.account_move
        self.assertRecordValues(invoice, [{'state': 'posted', 'spa_invoice_kind': 'pos', 'partner_id': lucia.id,
                                           'spa_membership_id': membership.id, 'amount_residual': 54.0}])
        product_lines = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertTrue(all(line.analytic_distribution == {str(self.area_restaurant.id): 100.0}
                            for line in product_lines))
        # Cliente de paso: paga en efectivo; no puede cargar a una cuenta de socio.
        walk_in = self._pos_order(self.restaurant, [(self.trout, 1)])
        self.assertAlmostEqual(walk_in.amount_total, 85.0)
        stranger = self._partner('Turista sin plan', '+591 70000999')
        with self._raises(UserError, 'no tiene una membresía vigente'):
            self._pos_order(self.restaurant, [(self.trout, 1)], partner=stranger,
                            payments=[(self.member_account, 85.0)])
        # La socia ve la deuda en su web y la paga con comprobante.
        self._login(self.lucia)
        response = self.url_open('/my/spa')
        self.assertIn('/my/spa/pay/%s' % invoice.id, response.text)
        response = self._submit_receipt(invoice, '54.00', method='transfer', reference='TRF-RESTO-1')
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=received')
        request = self.env['spa.payment.request'].search([('invoice_id', '=', invoice.id)])
        self.env.invalidate_all()
        request.with_user(self.cashier).action_validate()
        self.env.invalidate_all()
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertEqual(membership.date_end, date(2027, 4, 1), 'Pagar un consumo no extiende la membresía')
        self.assertNotIn('/my/spa/pay/%s"' % invoice.id, self.url_open('/my/spa').text)
        # Cierre de caja: asiento cuadrado con el ingreso en el área Restaurante.
        closing = self._pos_close(session)
        self.assertEqual(session.state, 'closed')
        self._assert_balanced(closing)
        income_account = self._acc('l10n_bo_spa_41015')
        income = closing.line_ids.filtered(lambda l: l.account_id == income_account)
        self.assertAlmostEqual(-sum(income.mapped('balance')), 73.95, places=2)
        self.assertAlmostEqual(self._area_amount(income, self.area_restaurant), 73.95, places=2)
        self.assertAlmostEqual(self._area_amount(product_lines, self.area_restaurant), 46.97, delta=0.02)

    # ==================================================================
    # 9. Mora visible en la web y renovación pagada desde el portal
    # ==================================================================
    def test_09_portal_suspension_and_renewal(self):
        membership = self._enroll(self.mateo.partner_id, self.plan_premium)
        Membership = self.env['spa.membership']
        with self._at(date(2027, 3, 27), 6, 5):
            Membership._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertEqual(renewal.spa_invoice_kind, 'renewal')
        with self._at(date(2027, 4, 7), 6, 5):
            Membership._cron_membership_daily()
        self.assertEqual(membership.state, 'suspended')
        with self._at(date(2027, 4, 7), 10):
            self._login(self.mateo)
            response = self.url_open('/my/spa/book')
            self.assertIn('no está activa', response.text)
            response = self.url_open('/my/spa')
            self.assertIn('Suspendida', response.text)
            self.assertNotIn(membership.qr_token, response.text, 'Suspendida: sin credencial')
            self.assertIn('/my/spa/pay/%s' % renewal.id, response.text)
            response = self._submit_receipt(renewal, '890', reference='QR-RENUEVA')
            self._assert_redirect(response, '/my/spa/pay/%s' % renewal.id, 'msg=received')
            self.env.invalidate_all()
            request = self.env['spa.payment.request'].search([('invoice_id', '=', renewal.id)])
            request.with_user(self.cashier).action_validate()
            self.env.invalidate_all()
            self.assertEqual(membership.state, 'active')
            self.assertEqual(membership.date_end, date(2027, 5, 6))
            response = self.url_open('/my/spa/book?service_id=%s&day=%s' % (self.massage.id, date(2027, 4, 8)))
            self.assertIn('Confirmar reserva', response.text)
            self.assertIn(membership.qr_token, self.url_open('/my/spa').text)

    # ==================================================================
    # 12. Cada socio ve solo lo suyo
    # ==================================================================
    def test_12_portal_isolation(self):
        membership = self._enroll(self.lucia.partner_id, self.plan_premium)
        invoice = membership.invoice_ids
        booking = self._book(self.lucia.partner_id, self.massage, WED, 10, channel='portal')
        self._enroll(self.mateo.partner_id, self.plan_basic)
        self._login(self.mateo)
        with mute_logger('odoo.http'):
            self.assertEqual(self.url_open('/my/spa/pay/%s' % invoice.id).status_code, 404)
            self.assertEqual(self.url_open('/my/spa/pay/%s/qr' % invoice.id).status_code, 404)
            response = self._post('/my/spa/pay/%s/submit' % invoice.id,
                                  {'method': 'qr', 'amount': '10', 'reference': 'X'})
            self.assertEqual(response.status_code, 404)
            response = self._post('/my/spa/booking/%s/cancel' % booking.id)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(booking.state, 'confirmed')
        response = self.url_open('/my/spa')
        self.assertNotIn(membership.qr_token, response.text)
        self.assertNotIn(invoice.name, response.text)
        self.assertNotIn('Lucía', response.text)
        # Sin sesión: la web del socio pide ingresar.
        self.authenticate(None, None)
        response = self.url_open('/my/spa', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers['Location'])
