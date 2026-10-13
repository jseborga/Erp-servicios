# Part of ERP Servicios Spa. License LGPL-3.
import base64
from datetime import timedelta
from urllib.parse import urlparse

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

# PNG de 1x1 px: comprobante y QR de cobro de prueba.
PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


@tagged('post_install', '-at_install', 'spa')
class TestSpaPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tools = cls.env['spa.tools']
        cls.today = cls.tools.local_today()
        cls.website = cls.env.ref('website.default_website')
        cls.company = cls.website.company_id
        cls.plan_basic = cls.env.ref('spa_membership.plan_basic')
        cls.plan_premium = cls.env.ref('spa_membership.plan_premium')
        cls.plan_vip = cls.env.ref('spa_membership.plan_vip')
        cls.massage = cls.env.ref('spa_base.service_massage')
        cls.sauna = cls.env.ref('spa_base.service_sauna')
        (cls.plan_basic | cls.plan_premium | cls.plan_vip).write({'website_published': True})
        if not cls.env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1):
            cls.env['account.journal'].create({'name': 'Banco (prueba)', 'code': 'BTST', 'type': 'bank',
                                               'company_id': cls.company.id})
        cls.company.spa_payment_qr = base64.b64encode(PNG_1PX)
        cls.company.spa_bank_account_text = 'Banco Prueba · Cta. 100-200 · ERP Spa'
        cls.member = new_test_user(cls.env, login='spa_portal_member', password='spa_portal_member',
                                   groups='base.group_portal', name='Lucía Socia', email='lucia.socia@example.com')
        cls.intruder = new_test_user(cls.env, login='spa_portal_other', password='spa_portal_other',
                                     groups='base.group_portal', name='Otro Socio', email='otro.socio@example.com')
        cls.cashier = new_test_user(cls.env, login='spa_portal_cashier', password='spa_portal_cashier',
                                    groups='base.group_user,spa_base.group_spa_cashier', name='Caja (prueba)')
        cls.manager = new_test_user(cls.env, login='spa_portal_manager', password='spa_portal_manager',
                                    groups='base.group_user,spa_base.group_spa_manager', name='Responsable (prueba)')

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _login(self, user):
        self.authenticate(user.login, user.login)

    def _post(self, url, data=None, files=None):
        data = dict(data or {}, csrf_token=http.Request.csrf_token(self))
        return self.url_open(url, data=data, files=files, allow_redirects=False)

    def _assert_redirect(self, response, path, query=None):
        self.assertIn(response.status_code, (302, 303), response.text[:500])
        location = urlparse(response.headers['Location'])
        self.assertEqual(location.path, path)
        if query:
            self.assertIn(query, location.query)

    def _membership(self, user, plan=None, activate=True):
        """Membresía (y factura) creada como lo haría recepción."""
        plan = plan or self.plan_premium
        membership = self.env['spa.membership'].create({
            'partner_id': user.partner_id.id,
            'plan_id': plan.id,
            'period_id': plan.period_ids.filtered(lambda p: p.months == 1).id,
        })
        invoice = membership.action_create_invoice()
        if activate:
            membership.action_activate()
        return membership, invoice

    def _slot_values(self, service, membership, day):
        return [dict(slot, value=fields.Datetime.to_string(slot['start']))
                for slot in service._get_slots(day, membership=membership)]

    def _first_slot(self, service, membership, day):
        slot = next((s for s in service._get_slots(day, membership=membership) if s['available']), None)
        self.assertTrue(slot, 'No hay franjas libres de %s el %s' % (service.name, day))
        return fields.Datetime.to_string(slot['start'])

    # ------------------------------------------------------------------
    # Web pública
    # ------------------------------------------------------------------
    def test_01_public_pages(self):
        self.plan_basic.website_published = False
        response = self.url_open('/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Premium', response.text)
        self.assertIn('VIP', response.text)
        self.assertNotIn('/spa/plan/%s"' % self.plan_basic.id, response.text, 'Un plan no publicado no se lista')

        response = self.url_open('/spa/plan/%s' % self.plan_premium.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Premium', response.text)
        self.assertIn('Elige la duración', response.text)
        self.assertIn(self.massage.name, response.text)
        with mute_logger('odoo.http'):
            self.assertEqual(self.url_open('/spa/plan/%s' % self.plan_basic.id).status_code, 404)

        # Un visitante que intenta suscribirse va al ingreso (y vuelve al plan elegido).
        self.authenticate(None, None)
        period = self.plan_premium.period_ids.filtered(lambda p: p.months == 3)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id, {'option': '%s:0' % period.id})
        self._assert_redirect(response, '/web/login', 'redirect=')
        self.assertFalse(self.env['spa.membership'].search([('plan_id', '=', self.plan_premium.id),
                                                            ('partner_id.name', '=', 'Public user')]))

    # ------------------------------------------------------------------
    # Flujo completo del socio
    # ------------------------------------------------------------------
    def test_02_member_flow(self):
        self._login(self.member)
        response = self.url_open('/my')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/my/spa', response.text)
        self.assertIn('Mi membresía', response.text)
        response = self.url_open('/my/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Aún no eres socio', response.text)

        # 1. Alta en línea: membresía por activar + cobro pendiente (la factura se emite al validar el pago)
        period = self.plan_premium.period_ids.filtered(lambda p: p.months == 1)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id,
                              {'option': '%s:0' % period.id, 'phone': ''})
        self.assertEqual(response.status_code, 200, 'Sin celular se vuelve al formulario')
        self.assertIn('Escribe tu número de celular', response.text)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id,
                              {'option': '%s:0' % period.id, 'phone': '+591 71234567'})
        self.env.invalidate_all()
        membership = self.env['spa.membership'].search([('partner_id', '=', self.member.partner_id.id)])
        self.assertEqual(len(membership), 1)
        self.assertEqual(membership.state, 'draft')
        self.assertEqual(membership.plan_id, self.plan_premium)
        invoice = membership.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(invoice.spa_invoice_kind, 'membership')
        self.assertFalse(invoice.invoice_user_id, 'El usuario portal no queda como vendedor')
        self.assertEqual(self.member.partner_id.phone, '+591 71234567')
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id)

        # Suscribirse de nuevo no duplica: lleva a pagar la misma factura.
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id, {'option': '%s:0' % period.id})
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=existing')
        self.assertEqual(self.env['spa.membership'].search_count([('partner_id', '=', self.member.partner_id.id)]), 1)
        # Otro plan mientras tiene uno abierto: se explica que pase por recepción.
        vip_period = self.plan_vip.period_ids.filtered(lambda p: p.months == 1)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_vip.id, {'option': '%s:0' % vip_period.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Para cambiar de plan', response.text)

        # 2. Página de pago y QR de cobro de la compañía
        response = self.url_open('/my/spa/pay/%s' % invoice.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Envía tu comprobante', response.text)
        self.assertIn('Banco Prueba', response.text)
        self.assertIn('Cobro pendiente %s' % membership.name, response.text)
        self.assertIn('Tu factura se emite cuando caja confirme el pago', response.text)
        self.assertNotIn('Ver factura', response.text)
        self.assertIn('/my/spa/pay/%s/qr' % invoice.id, response.text)
        response = self.url_open('/my/spa/pay/%s/qr' % invoice.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        response = self.url_open('/my/spa')
        self.assertIn('Pendiente de pago', response.text)
        self.assertIn('Tu credencial QR se activa', response.text)
        self.assertNotIn(membership.qr_token, response.text, 'Sin pago no hay credencial')
        response = self.url_open('/my/spa/book')
        self.assertIn('no está activa', response.text)

        # 3. Pago con comprobante (archivo) → queda por validar
        amount = '%.2f' % invoice.amount_residual
        response = self._post('/my/spa/pay/%s/submit' % invoice.id, {'method': 'bitcoin', 'amount': amount})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Elige cómo pagaste', response.text)
        response = self._post('/my/spa/pay/%s/submit' % invoice.id, {'method': 'qr', 'amount': amount},
                              files={'receipt': ('script.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                                                 'image/svg+xml')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('debe ser una imagen', response.text)
        response = self._post('/my/spa/pay/%s/submit' % invoice.id,
                              {'method': 'qr', 'amount': amount.replace('.', ','), 'reference': 'TX-778899'},
                              files={'receipt': ('C:\\fotos\\comprobante.png', PNG_1PX, 'image/png')})
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=received')
        # Un segundo aviso por el mismo saldo se frena mientras caja valida el primero.
        response = self._post('/my/spa/pay/%s/submit' % invoice.id, {'method': 'transfer', 'amount': amount,
                                                                      'reference': 'TX-778899'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Ya informaste', response.text)
        self.env.invalidate_all()
        pay_request = self.env['spa.payment.request'].search([('invoice_id', '=', invoice.id)])
        self.assertEqual(len(pay_request), 1)
        self.assertRecordValues(pay_request, [{
            'state': 'pending', 'method': 'qr', 'channel': 'portal', 'reference': 'TX-778899',
            'receipt_filename': 'comprobante.png', 'partner_id': self.member.partner_id.id,
            'membership_id': membership.id,
        }])
        self.assertEqual(base64.b64decode(pay_request.receipt), PNG_1PX)
        self.assertAlmostEqual(pay_request.amount, invoice.amount_residual)
        response = self.url_open('/my/spa/pay/%s' % invoice.id)
        self.assertIn('por validar', response.text)
        self.assertIn(pay_request.name, response.text)
        self.assertIn('Pago en validación', self.url_open('/my/spa').text)

        # 4. Caja valida → se emite la factura y la membresía se activa
        pay_request.with_user(self.cashier).action_validate()
        self.env.invalidate_all()
        self.assertEqual(pay_request.state, 'validated')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.invoice_date, self.today)
        self.assertEqual(membership.state, 'active')
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        response = self.url_open('/my/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/report/barcode/QR/%s' % membership.qr_token, response.text)
        self.assertIn(self.massage.name, response.text)
        with mute_logger('odoo.http'):
            self.assertEqual(self.url_open('/my/spa/pay/%s/qr' % invoice.id).status_code, 404,
                             'Factura pagada: ya no se muestra el QR de cobro')

        # 5. Reserva de masaje (pasado mañana: la cancelación queda dentro de plazo)
        day = self.today + timedelta(days=2)
        response = self.url_open('/my/spa/book?service_id=%s&day=%s' % (self.massage.id, day))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirmar reserva', response.text)
        self.assertIn('Te quedan 4 de 4', response.text)
        start = self._first_slot(self.massage, membership, day)
        self.assertIn(start, response.text)
        response = self._post('/my/spa/book/confirm', {'service_id': self.massage.id, 'day': fields.Date.to_string(day),
                                                        'guests': 0, 'start': '2000-01-01 10:00:00'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Elige un horario de la lista', response.text)
        response = self._post('/my/spa/book/confirm', {
            'service_id': self.massage.id, 'day': fields.Date.to_string(day), 'guests': 0, 'start': start})
        self._assert_redirect(response, '/my/spa', 'msg=booked')
        self.env.invalidate_all()
        booking = self.env['spa.booking'].search([('partner_id', '=', self.member.partner_id.id)])
        self.assertEqual(len(booking), 1)
        self.assertRecordValues(booking, [{'state': 'confirmed', 'channel': 'portal', 'membership_id': membership.id,
                                           'service_id': self.massage.id}])
        self.assertEqual(fields.Datetime.to_string(booking.start), start)
        self.assertEqual(membership._entitlement_for(self.massage, day).remaining, 3)
        # Tope semanal del plan (1 masaje por semana): el resto del día queda bloqueado y se explica.
        response = self.url_open('/my/spa/book?service_id=%s&day=%s' % (self.massage.id, day))
        self.assertIn('por semana y ya los us', response.text)
        other_start = next(slot['value'] for slot in self._slot_values(self.massage, membership, day)
                           if slot['value'] != start)
        response = self._post('/my/spa/book/confirm', {
            'service_id': self.massage.id, 'day': fields.Date.to_string(day), 'guests': 0, 'start': other_start})
        self.assertEqual(response.status_code, 200)
        self.assertIn('ya no está disponible', response.text)
        self.assertEqual(self.env['spa.booking'].search_count([('partner_id', '=', self.member.partner_id.id)]), 1)
        response = self.url_open('/my/spa')
        self.assertIn('/my/spa/booking/%s/cancel' % booking.id, response.text)
        self.assertIn('Cancelación sin costo', response.text)

        # 6. Cancelación dentro de plazo → la sesión vuelve al saldo
        response = self._post('/my/spa/booking/%s/cancel' % booking.id)
        self._assert_redirect(response, '/my/spa', 'msg=cancelled')
        self.env.invalidate_all()
        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(sum(booking.consumption_ids.mapped('qty')), 0)
        self.assertEqual(membership._entitlement_for(self.massage, day).remaining, 4)
        response = self._post('/my/spa/booking/%s/cancel' % booking.id)
        self._assert_redirect(response, '/my/spa', 'msg=cancel_denied')

        # 7. Invitado en un espacio de acceso libre (sauna) con free pass
        response = self.url_open('/my/spa/guests')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Registrar invitado', response.text)
        response = self._post('/my/spa/guests/register', {
            'name': 'Carla Invitada', 'phone': '+591 76543210', 'date': fields.Date.to_string(self.today),
            'service_id': self.sauna.id})
        self._assert_redirect(response, '/my/spa/guests', 'msg=guest_free_pass')
        self.env.invalidate_all()
        guest = membership.guest_ids
        self.assertEqual(len(guest), 1)
        self.assertRecordValues(guest, [{'name': 'Carla Invitada', 'charge_type': 'free_pass',
                                         'service_id': self.sauna.id, 'date': self.today}])
        response = self._post('/my/spa/guests/register', {
            'name': 'Segundo Invitado', 'date': fields.Date.to_string(self.today), 'service_id': self.sauna.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn('por visita', response.text)
        self.assertEqual(len(membership.guest_ids), 1)
        response = self.url_open('/my/spa/guests?msg=guest_free_pass')
        self.assertIn('Carla Invitada', response.text)
        self.assertIn('Invitado registrado con free pass', response.text)
        # Un servicio con reserva no se registra por aquí.
        response = self._post('/my/spa/guests/register', {
            'name': 'Otro', 'date': fields.Date.to_string(self.today), 'service_id': self.massage.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Elige un espacio de acceso libre', response.text)

    def test_03_booking_with_guests(self):
        """Reserva de piscina con un invitado: se registra con la reserva y usa el free pass."""
        membership, _invoice = self._membership(self.member)
        pool = self.env.ref('spa_base.service_pool')
        day = self.today + timedelta(days=1)
        self._login(self.member)
        response = self.url_open('/my/spa/book?service_id=%s&day=%s&guests=1' % (pool.id, day))
        self.assertEqual(response.status_code, 200)
        self.assertIn('guest_name_0', response.text)
        slot = next(s for s in pool._get_slots(day, seats=2, membership=membership, guests=1) if s['available'])
        start = fields.Datetime.to_string(slot['start'])
        values = {'service_id': pool.id, 'day': fields.Date.to_string(day), 'guests': 1, 'start': start}
        response = self._post('/my/spa/book/confirm', dict(values, guest_name_0=''))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Escribe el nombre de cada invitado', response.text)
        response = self._post('/my/spa/book/confirm', dict(values, guest_name_0='Pedro Invitado',
                                                           guest_phone_0='+591 70011122'))
        self._assert_redirect(response, '/my/spa', 'msg=booked')
        self.env.invalidate_all()
        booking = membership.booking_ids
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.seats, 2)
        self.assertEqual(booking.guest_ids.name, 'Pedro Invitado')
        self.assertEqual(booking.guest_ids.charge_type, 'free_pass')

    # ------------------------------------------------------------------
    # Seguridad: cada socio ve solo lo suyo
    # ------------------------------------------------------------------
    def test_04_security(self):
        membership, invoice = self._membership(self.member, activate=False)
        payment_request = self.env['spa.payment.request'].create({
            'partner_id': self.member.partner_id.id, 'membership_id': membership.id, 'invoice_id': invoice.id,
            'amount': 10.0, 'method': 'transfer', 'channel': 'portal'})
        other_membership, _other_invoice = self._membership(self.member, plan=self.plan_vip)
        other_membership.invalidate_recordset()
        day = self.today + timedelta(days=2)
        booking = self.env['spa.booking'].create({
            'partner_id': self.member.partner_id.id, 'membership_id': other_membership.id,
            'payment_mode': 'membership', 'service_id': self.massage.id,
            'start': fields.Datetime.to_datetime(self._first_slot(self.massage, other_membership, day)),
            'channel': 'reception'})
        booking.action_confirm()

        # El dueño ve su factura y el QR de cobro.
        self._login(self.member)
        self.assertEqual(self.url_open('/my/spa/pay/%s' % invoice.id).status_code, 200)
        response = self.url_open('/my/spa/pay/%s/qr' % invoice.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG_1PX)

        # Otro socio: 404 en todo lo ajeno (lectura y escritura).
        self._login(self.intruder)
        with mute_logger('odoo.http'):
            self.assertEqual(self.url_open('/my/spa/pay/%s' % invoice.id).status_code, 404)
            self.assertEqual(self.url_open('/my/spa/pay/%s/qr' % invoice.id).status_code, 404)
            response = self._post('/my/spa/pay/%s/submit' % invoice.id,
                                  {'method': 'qr', 'amount': '10', 'reference': 'X'})
            self.assertEqual(response.status_code, 404)
            response = self._post('/my/spa/booking/%s/cancel' % booking.id)
            self.assertEqual(response.status_code, 404)
        self.env.invalidate_all()
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(self.env['spa.payment.request'].search_count([('invoice_id', '=', invoice.id)]), 1)
        response = self.url_open('/my/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Aún no eres socio', response.text)
        self.assertNotIn(membership.name, response.text)
        self.assertNotIn(payment_request.name, response.text)
        self.assertNotIn(membership.qr_token, response.text)
        self.assertNotIn(other_membership.qr_token, response.text)

        # Visitante sin sesión: el QR de cobro pide ingresar.
        self.authenticate(None, None)
        response = self.url_open('/my/spa/pay/%s/qr' % invoice.id, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers['Location'])

    def test_05_portal_home_counter(self):
        self._membership(self.member)
        self._login(self.member)
        result = self.make_jsonrpc_request('/my/counters', {'counters': ['spa_membership_count']})
        self.assertEqual(result, {'spa_membership_count': 1})
        self._login(self.intruder)
        result = self.make_jsonrpc_request('/my/counters', {'counters': ['spa_membership_count']})
        self.assertEqual(result, {'spa_membership_count': 0})

    def test_06_parse_amount(self):
        from odoo.addons.spa_portal.controllers.main import parse_amount
        for text, expected in [('890', 890.0), ('890,50', 890.5), ('1.234,50', 1234.5), ('1,234.50', 1234.5),
                               ('Bs. 1.234,50', 1234.5), (' 12 ', 12.0)]:
            self.assertAlmostEqual(parse_amount(text), expected, msg=text)
        for text in ('', 'abc', 'nan', 'inf', '1.2.3'):
            with self.assertRaises(ValueError, msg=text):
                parse_amount(text)

    def test_07_installments_offer(self):
        """Plan anual en cuotas: se paga la primera cuota y la membresía se activa."""
        period = self.plan_premium.period_ids.filtered(lambda p: p.months == 12)
        offer = self.env['spa.payment.offer'].create({
            'name': 'Anual en 3 cuotas (prueba)', 'offer_type': 'installments', 'installments': 3, 'months': 12,
            'plan_ids': [(6, 0, self.plan_premium.ids)], 'company_id': self.company.id,
            'date_from': self.today, 'date_to': self.today + timedelta(days=30)})
        self.member.partner_id.phone = '+591 70000999'
        self._login(self.member)
        response = self.url_open('/spa/plan/%s' % self.plan_premium.id)
        self.assertIn('%s:%s' % (period.id, offer.id), response.text)
        self.assertIn('Anual en 3 cuotas (prueba)', response.text)
        response = self._post('/spa/plan/%s/subscribe' % self.plan_premium.id,
                              {'option': '%s:%s' % (period.id, offer.id)})
        self.env.invalidate_all()
        membership = self.env['spa.membership'].search([('partner_id', '=', self.member.partner_id.id)])
        invoice = membership.invoice_ids
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id)
        self.assertEqual(invoice.spa_offer_id, offer)
        next_amount = invoice._get_invoice_next_payment_values()['next_amount_to_pay']
        self.assertAlmostEqual(next_amount, invoice.amount_total / 3, delta=1.0)  # plazos en % redondeado

        response = self.url_open('/my/spa/pay/%s' % invoice.id)
        self.assertIn('Próxima cuota', response.text)
        self.assertIn('value="%.2f"' % next_amount, response.text)
        response = self._post('/my/spa/pay/%s/submit' % invoice.id,
                              {'method': 'transfer', 'amount': '%.2f' % next_amount, 'reference': 'DEP-001'})
        self._assert_redirect(response, '/my/spa/pay/%s' % invoice.id, 'msg=received')
        self.env.invalidate_all()
        # Plan prepagado (12 meses): caja valida (el devengo se programa con sudo).
        self.assertEqual(invoice.state, 'draft')
        invoice.spa_membership_id.payment_request_ids.with_user(self.cashier).action_validate()
        self.env.invalidate_all()
        self.assertEqual(membership.state, 'active')
        self.assertEqual(invoice.state, 'posted', 'Se emite toda la factura al pagar la primera cuota')
        self.assertEqual(invoice.payment_state, 'partial')
        response = self.url_open('/my/spa')
        self.assertIn('/report/barcode/QR/%s' % membership.qr_token, response.text)
        self.assertIn('/my/spa/pay/%s' % invoice.id, response.text, 'Las cuotas restantes siguen por pagar')

    def test_08_late_cancel(self):
        """Fuera de plazo: se avisa la consecuencia antes y se aplica la política del plan."""
        membership, _invoice = self._membership(self.member)
        day = self.today + timedelta(days=2)
        booking = self.env['spa.booking'].create({
            'partner_id': self.member.partner_id.id, 'membership_id': membership.id, 'payment_mode': 'membership',
            'service_id': self.massage.id, 'channel': 'portal',
            'start': fields.Datetime.to_datetime(self._first_slot(self.massage, membership, day))})
        booking.action_confirm()
        policy = self.plan_premium.cancel_policy_id
        policy.write({'free_cancel_hours': 1000, 'late_cancel_action': 'lose_session'})
        self._login(self.member)
        response = self.url_open('/my/spa')
        self.assertIn('Estás fuera de plazo: según tu plan pierdes la sesión.', response.text)
        response = self._post('/my/spa/booking/%s/cancel' % booking.id)
        self._assert_redirect(response, '/my/spa', 'msg=late_lose_session')
        self.env.invalidate_all()
        self.assertEqual(booking.state, 'late_cancel')
        self.assertEqual(membership._entitlement_for(self.massage, day).remaining, 3, 'La sesión se pierde')
        self.assertIn('la sesión se descuenta', self.url_open('/my/spa?msg=late_lose_session').text)

    # ------------------------------------------------------------------
    # Renovación pendiente (sin factura) en la web del socio
    # ------------------------------------------------------------------
    def test_09_pending_renewal_in_portal(self):
        membership, invoice = self._membership(self.member, activate=False)
        payment = self.env['spa.payment.request'].create({
            'partner_id': self.member.partner_id.id, 'membership_id': membership.id, 'invoice_id': invoice.id,
            'amount': invoice.amount_residual, 'method': 'cash', 'channel': 'reception'})
        payment.with_user(self.cashier).action_validate()
        self.assertEqual(membership.state, 'active')
        membership.date_end = self.today + timedelta(days=2)
        self.env['spa.membership']._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertEqual(renewal.state, 'draft')
        self._login(self.member)
        response = self.url_open('/my/spa')
        self.assertIn('/my/spa/pay/%s' % renewal.id, response.text)
        self.assertIn('Cobro pendiente %s' % membership.name, response.text)
        response = self.url_open('/my/spa/pay', allow_redirects=False)
        self._assert_redirect(response, '/my/spa/pay/%s' % renewal.id)
        response = self.url_open('/my/spa/pay/%s' % renewal.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(membership.name, response.text, 'Referencia del pago = número de la membresía')
        self.assertIn('value="890.00"', response.text)
        self.assertEqual(self.url_open('/my/spa/pay/%s/qr' % renewal.id).status_code, 200)
        response = self._post('/my/spa/pay/%s/submit' % renewal.id,
                              {'method': 'transfer', 'amount': '890', 'reference': 'TRF-RENUEVA'})
        self._assert_redirect(response, '/my/spa/pay/%s' % renewal.id, 'msg=received')
        self.env.invalidate_all()
        request = self.env['spa.payment.request'].search([('invoice_id', '=', renewal.id)])
        self.assertRecordValues(request, [{'state': 'pending', 'amount': 890.0, 'membership_id': membership.id}])
        request.with_user(self.cashier).action_validate()
        self.env.invalidate_all()
        self.assertEqual(renewal.state, 'posted')
        self.assertEqual(membership.date_end, self.today + timedelta(days=2) + relativedelta(months=1))

    def test_10_cancelled_pending_charge_not_payable(self):
        membership, invoice = self._membership(self.member, activate=False)
        membership.action_cancel()
        self.assertEqual(invoice.state, 'cancel')
        self._login(self.member)
        with mute_logger('odoo.http'):
            self.assertEqual(self.url_open('/my/spa/pay/%s' % invoice.id).status_code, 404)
            self.assertEqual(self.url_open('/my/spa/pay/%s/qr' % invoice.id).status_code, 404)
        response = self.url_open('/my/spa/pay', allow_redirects=False)
        self._assert_redirect(response, '/my/spa', 'msg=nothing_due')

    def test_11_grace_shows_last_access_day(self):
        membership, invoice = self._membership(self.member)
        membership.write({'date_end': self.today - timedelta(days=1), 'state': 'grace'})
        until = membership._spa_access_until()
        self.assertLessEqual(until, membership.grace_until)
        self._login(self.member)
        response = self.url_open('/my/spa')
        self.assertIn('en gracia hasta el', response.text)
