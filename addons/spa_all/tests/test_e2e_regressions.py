# Part of ERP Servicios Spa. License LGPL-3.
"""Pruebas de regresión de los 19 defectos encontrados por la prueba de punta a punta.

Cada ``test_fixed_*`` verifica el comportamiento correcto de un defecto ya corregido (permisos
por rol, aforo, ingresos, devengo, cuotas, reglas multiempresa…). Deben seguir en verde.
"""
import json
from datetime import timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, freeze_time, tagged

from .common import DAY0, START, SpaE2EMixin

WED = DAY0 + timedelta(days=1)


@tagged('post_install', '-at_install', 'spa', 'spa_e2e')
@freeze_time(START)
class TestSpaE2ERegressions(SpaE2EMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()
        cls.ana = cls._partner('Ana Rojas', '+591 70000101', 'ana.rojas@socios.example.com')
        cls.bruno = cls._partner('Bruno Salinas', '+591 70000102', 'bruno.salinas@socios.example.com')

    def _web_read_view(self, user, records, view_type):
        """Lee los campos de la vista por defecto como lo hace el cliente web (petición nueva)."""
        self.env.invalidate_all()
        model = records.with_user(user)
        fields_info = model.get_views([(False, view_type)])['models'][records._name]['fields']
        spec = {name: ({'fields': {'display_name': {}}} if info['type'] in ('many2one', 'one2many', 'many2many')
                       else {}) for name, info in fields_info.items()}
        return model.web_read(spec)

    # ------------------------------------------------------------------
    # spa_billing: vistas de membresía ilegibles para recepción
    # ------------------------------------------------------------------
    def test_fixed_reception_cannot_open_membership_views(self):
        """Recepción, marketing y caja no pueden abrir la lista/ficha de membresías.

        spa_billing/models/spa_membership.py:13-17 agrega ``invoice_ids`` (account.move),
        ``invoice_count``/``amount_due`` (calculados leyendo account.move) y ``deferral_line_ids``
        (spa.deferral.line, sin permiso para recepción ni caja); las vistas
        (spa_billing/views/spa_membership_views.xml) los muestran a todos.
        """
        monthly = self._enroll(self.ana, self.plan_premium)
        annual = self._enroll(self.bruno, self.plan_premium, months=12)
        self.assertTrue(annual.deferral_line_ids)
        for user in (self.reception, self.marketing):
            self._web_read_view(user, monthly, 'list')
            self._web_read_view(user, monthly, 'form')
        self._web_read_view(self.cashier, annual, 'form')

    # ------------------------------------------------------------------
    # spa_base / spa_booking: reservas con personal desde recepción
    # ------------------------------------------------------------------
    def test_fixed_reception_cannot_book_massage(self):
        """Recepción no puede buscar franjas ni confirmar un masaje.

        spa_base/models/spa_service.py:45 ``_qualified_employees`` busca ``hr.employee`` con el
        usuario de recepción (sin permisos de Empleados): Odoo redirige la búsqueda a
        ``hr.employee.public``, que no tiene ``spa_skill_ids`` → ValueError/AccessError. Lo usan
        ``spa.service._free_employee`` (spa_booking/models/spa_service.py:34) y
        ``spa.booking._confirm_one``. La web funciona solo porque usa sudo.
        """
        self._enroll(self.ana, self.plan_premium)
        self.env.invalidate_all()
        wizard = self.env['spa.booking.slot.wizard'].with_user(self.reception).create({
            'partner_id': self.ana.id, 'membership_id': self.ana.spa_membership_id.id,
            'service_id': self.massage.id, 'date': WED})
        wizard.action_search()
        line = wizard.line_ids.filtered(lambda slot: slot.available)[:1]
        self.assertTrue(line, 'Debe haber franjas libres de masaje el miércoles')
        line.action_book()
        booking = self.env['spa.booking'].search([('partner_id', '=', self.ana.id)])
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.employee_id, self.therapist_employee)

    # ------------------------------------------------------------------
    # spa_billing: recepción no factura ni registra pagos
    # ------------------------------------------------------------------
    def test_fixed_reception_cannot_invoice_or_register_payment(self):
        """«Facturar período» y «Registrar pago» fallan para recepción (docs/10: registra pagos por validar).

        spa_billing/models/spa_membership.py:48 ``_open_period_invoice`` lee ``self.invoice_ids``
        (account.move) con el usuario de recepción; lo llaman ``action_create_invoice`` (l. 59) y
        ``action_register_payment_request`` (l. 102). Igual en spa_billing/models/spa_booking.py:70
        (``self.invoice_id.amount_residual``). En las pruebas unitarias no se ve porque la caché ya
        tiene la factura leída como superusuario.
        """
        membership = self.env['spa.membership'].with_user(self.reception).create({
            'partner_id': self.ana.id, 'plan_id': self.plan_premium.id,
            'period_id': self._period(self.plan_premium, 1).id})
        self.env.invalidate_all()
        invoice = membership.with_user(self.reception).action_create_invoice()
        self.assertEqual(invoice.sudo().state, 'draft')
        request = self._register_payment(membership, user=self.reception)
        self.assertEqual(request.sudo().amount, 890.0)

    # ------------------------------------------------------------------
    # spa_base: recepción no puede dar de alta el contacto del socio
    # ------------------------------------------------------------------
    def test_fixed_reception_cannot_create_member_contact(self):
        """docs/10: Recepción hace el «alta de socios». El grupo no implica
        ``base.group_partner_manager`` (spa_base/security/spa_security.xml:17-23), así que no puede
        crear el contacto de un socio nuevo que llega a recepción."""
        partner = self.env['res.partner'].with_user(self.reception).create({
            'name': 'Socio Nuevo de Recepción', 'phone': '+591 70000177'})
        self.assertTrue(partner)

    # ------------------------------------------------------------------
    # spa_membership: el terapeuta no abre su propia sesión
    # ------------------------------------------------------------------
    def test_fixed_therapist_cannot_open_own_booking(self):
        """La ficha de reserva muestra ``guest_ids`` (spa_booking/views/spa_booking_views.xml:79) y el
        terapeuta no tiene permiso de lectura sobre spa.guest
        (spa_membership/security/ir.model.access.csv: solo recepción y gerente)."""
        self._enroll(self.ana, self.plan_premium)
        booking = self._book(self.ana, self.massage, WED, 10)
        self.assertEqual(booking.employee_id.user_id, self.therapist)
        self._web_read_view(self.therapist, booking, 'form')

    # ------------------------------------------------------------------
    # spa_access: socio suspendido ingresa con una reserva anterior
    # ------------------------------------------------------------------
    def test_fixed_suspended_member_checks_in_with_prior_booking(self):
        """docs/04: suspendida = «sin reservas nuevas ni check-in». spa_access/models/spa_access_log.py:87-97
        (espacios por franja) solo busca una reserva confirmada y no valida el estado de la membresía;
        la suspensión tampoco pone las reservas futuras «en espera de pago»."""
        membership = self._enroll(self.ana, self.plan_premium)
        booking = self._book(self.ana, self.massage, WED, 10)
        membership.with_user(self.manager).action_suspend()  # p. ej. cheque/QR rechazado por el banco
        self.assertEqual(membership.state, 'suspended')
        with self._at(WED, 9, 50), self._raises(UserError):
            self._check_in(self.space_massage, membership)
        self.assertEqual(booking.state, 'confirmed')

    # ------------------------------------------------------------------
    # spa_booking / spa_crm: aforo de espacios por franja con ingresos sin reserva
    # ------------------------------------------------------------------
    def test_fixed_courtesy_walkin_ignored_by_booking_capacity(self):
        """Un pase de cortesía canjeado en un espacio por franja (piscina) ocupa un lugar
        (spa_crm/models/spa_courtesy_pass.py:313 lo cuenta), pero ``spa.space._seats_taken``
        (spa_booking/models/spa_service.py:12-21) solo suma reservas: las reservas siguientes
        ignoran a las personas que ya están dentro y se supera el aforo."""
        self.space_pool.with_user(self.owner).capacity = 2
        self._enroll(self.ana, self.plan_premium)
        self._enroll(self.bruno, self.plan_premium)
        courtesy = self.env['spa.courtesy.pass'].with_user(self.marketing).create({
            'guest_name': 'Sofía Vargas', 'phone': '+591 71234567', 'service_ids': [Command.set(self.pool.ids)]})
        with self._at(DAY0, 10):
            self._check_in(self.space_pool, token=courtesy.sudo().token)  # 1 persona dentro hasta las 12:00
            self._book(self.ana, self.pool, DAY0, 10, minute=30)  # 2 de 2
            with self._raises(UserError, 'No hay cupo'):
                self._book(self.bruno, self.pool, DAY0, 10, minute=30)

    # ------------------------------------------------------------------
    # spa_access: ingreso a un espacio libre cerrado
    # ------------------------------------------------------------------
    def test_fixed_free_space_checkin_when_closed(self):
        """El sauna abre 10:00-20:00, pero spa_access/models/spa_access_log.py:103-121 (modo libre) no
        valida el horario ni los cierres programados (``spa.space._within_hours``/``_is_open_on``)."""
        membership = self._enroll(self.ana, self.plan_premium)
        with self._at(DAY0, 8), self._raises(UserError):
            self._check_in(self.space_sauna, membership)

    # ------------------------------------------------------------------
    # spa_access: invitado registrado en la web se cuenta dos veces al ingresar
    # ------------------------------------------------------------------
    def test_fixed_preregistered_guest_counted_twice_at_checkin(self):
        """El socio registra a su invitado en la web (/my/spa/guests, free pass) y luego ingresa con él
        al sauna. spa_access/models/spa_access_log.py:122-126 crea OTRO ``spa.guest`` («Invitado 1 de …»)
        sin vincular el ya registrado: consume un segundo free pass o cobra la tarifa de invitado."""
        membership = self._enroll(self.ana, self.plan_basic)  # Básica: 1 free pass al mes
        # Lo que hace la web del socio (controlador con sudo).
        guest = self.env['spa.guest'].sudo().create({
            'name': 'Carla Invitada', 'phone': '+591 76543210', 'membership_id': membership.id,
            'date': DAY0, 'service_id': self.sauna.id})
        self.assertEqual(guest.charge_type, 'free_pass')
        with self._at(DAY0, 11):
            self._check_in(self.space_sauna, membership, guests=1)
        self.assertEqual(len(membership.guest_ids), 1, 'El invitado registrado es el que ingresa')
        self.assertEqual(guest.state, 'attended')
        self.assertFalse(self._charges_invoice(self.ana), 'No se cobra tarifa: usó su free pass')

    # ------------------------------------------------------------------
    # spa_billing: cuotas desiguales
    # ------------------------------------------------------------------
    def test_fixed_installments_unequal(self):
        """«Anual en 3 cuotas sin recargo» de Bs 9.070: spa_billing/models/spa_payment_offer.py:63 redondea
        el porcentaje a 2 decimales (33,33 %), así que las cuotas son 3.023,03 / 3.023,03 / 3.023,94 en
        lugar de 3.023,33 / 3.023,33 / 3.023,34."""
        offer = self.env['spa.payment.offer'].with_user(self.owner).create({
            'name': 'Anual en 3 cuotas', 'offer_type': 'installments', 'installments': 3, 'months': 12,
            'date_from': DAY0, 'date_to': DAY0 + timedelta(days=30)})
        membership = self.env['spa.membership'].with_user(self.reception).create({
            'partner_id': self.ana.id, 'plan_id': self.plan_premium.id,
            'period_id': self._period(self.plan_premium, 12).id})
        invoice = membership.with_user(self.cashier).action_create_invoice(offer=offer).sudo()
        installments = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable').sorted('date_maturity')
        self.assertEqual([round(line.balance, 2) for line in installments], [3023.33, 3023.33, 3023.34])

    # ------------------------------------------------------------------
    # Roles (docs/10)
    # ------------------------------------------------------------------
    def test_fixed_cashier_can_post_manual_journal_entry(self):
        """docs/10: Cajero «No puede: Asientos manuales». ``group_spa_cashier`` implica
        ``account.group_account_invoice`` (spa_billing/security/spa_billing_security.xml:4), que en Odoo
        permite crear y publicar asientos manuales: la caja puede, por ejemplo, sacar efectivo a un gasto."""
        cash_account = self.cash_journal.default_account_id
        shortage = self._acc('l10n_bo_spa_5607')
        misc = self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', self.company.id),
                                                   ('code', '=', 'MISC')], limit=1)
        with self._raises(UserError):  # AccessError es subclase de UserError
            move = self.env['account.move'].with_user(self.cashier).create({
                'move_type': 'entry', 'journal_id': misc.id, 'line_ids': [
                    Command.create({'account_id': shortage.id, 'debit': 500.0, 'name': 'Faltante'}),
                    Command.create({'account_id': cash_account.id, 'credit': 500.0, 'name': 'Faltante'})]})
            move.action_post()

    def test_fixed_reception_has_no_crm_access(self):
        """docs/10: Recepción implica «CRM usuario» y gestiona leads (paso por recepción). El grupo de
        recepción no da acceso a crm.lead (solo marketing implica sales_team, spa_crm/security)."""
        lead = self.env['crm.lead'].with_user(self.reception).create({
            'name': 'Pasó por recepción: Tomás', 'phone': '+591 71230000',
            'source_id': self.env.ref('spa_crm.utm_source_reception').id})
        self.assertEqual(lead.sudo().team_id, self.team_acq)

    # ------------------------------------------------------------------
    # spa_billing: devengo de una membresía cancelada y reembolsada
    # ------------------------------------------------------------------
    def test_fixed_deferral_continues_after_cancellation(self):
        """Plan anual pagado, el socio desiste en marzo: el gerente cancela la membresía y el contador
        emite la nota de crédito. spa_billing/models/spa_deferral.py:56-59 sigue contabilizando cada mes
        las cuotas «programadas» (Debe 215100 / Haber 410110) porque ni ``spa.membership.action_cancel``
        (spa_membership/models/spa_membership.py:110) ni la reversión de la factura las anulan:
        se reconoce ingreso de una venta devuelta y 215100 queda con saldo deudor."""
        from datetime import date

        membership = self._enroll(self.ana, self.plan_premium, months=12)
        invoice = membership.invoice_ids
        self.env['spa.membership']._cron_billing_daily()  # marzo devengado
        membership.with_user(self.manager).action_cancel()
        refund = invoice.with_user(self.accountant)._reverse_moves(
            [{'date': DAY0, 'invoice_date': DAY0, 'ref': 'Desistimiento del socio'}])
        refund.with_user(self.accountant).action_post()
        with self._at(date(2027, 4, 2), 7):
            self.env['spa.membership']._cron_billing_daily()
        posted = membership.deferral_line_ids.filtered(lambda line: line.state == 'posted')
        self.assertEqual(len(posted), 1, 'Después de cancelar no se devenga más ingreso')

    # ------------------------------------------------------------------
    # spa_billing / spa_booking: reserva suelta cancelada con factura abierta
    # ------------------------------------------------------------------
    def test_fixed_cancelled_single_booking_keeps_open_invoice(self):
        """Un visitante reserva la piscina con pago suelto: se publica la factura (spa_billing
        ``_create_single_invoice``). Cancela con anticipación y ``spa.booking.action_cancel``
        (spa_booking/models/spa_booking.py:201) no toca la factura: queda una cuenta por cobrar y un
        débito fiscal por un servicio que no se prestó."""
        visitor = self._partner('Visitante', '+591 70000150')
        booking = self._book(visitor, self.pool, WED, 9, payment_mode='single')
        invoice = booking.invoice_id
        self.assertEqual(invoice.state, 'draft')
        booking.with_user(self.reception).action_cancel()
        self.assertEqual(booking.state, 'cancelled')
        self.assertTrue(invoice.state == 'cancel' or invoice.payment_state == 'reversed',
                        'La factura de una reserva suelta cancelada sin pago se anula')

    # ------------------------------------------------------------------
    # spa_crm: pase de cortesía duplica el contacto por el formato del celular
    # ------------------------------------------------------------------
    def test_fixed_courtesy_duplicates_contact_by_phone_format(self):
        """Ana es socia (celular «+591 70000101»). Marketing le emite una cortesía para un evento y
        escribe «70000101». spa_crm/models/spa_courtesy_pass.py:155-156 busca el contacto por
        igualdad exacta del texto: crea un contacto duplicado y un prospecto de Captación para una
        socia vigente (los invitados sí comparan los últimos 8 dígitos)."""
        self._enroll(self.ana, self.plan_premium)
        courtesy = self.env['spa.courtesy.pass'].with_user(self.marketing).create({
            'guest_name': 'Ana Rojas', 'phone': '70000101', 'service_ids': [Command.set(self.sauna.ids)],
            'reason': 'Evento aniversario'}).sudo()
        self.assertEqual(courtesy.partner_id, self.ana)
        self.assertFalse(courtesy.lead_id, 'Una socia vigente no es un prospecto de captación')

    # ------------------------------------------------------------------
    # Multiempresa (CLAUDE.md regla 5)
    # ------------------------------------------------------------------
    def test_fixed_multicompany_rules_missing(self):
        """Modelos propios con ``company_id`` y sin ``ir.rule`` multiempresa: ``spa.message`` (WhatsApp con
        celular y texto: datos personales), ``spa.payment.offer``, ``spa.cancel.policy``,
        ``spa.entitlement`` y ``spa.deferral.line``. La recepción de otra empresa los ve."""
        self._enroll(self.ana, self.plan_premium)
        self.env['spa.payment.offer'].with_user(self.owner).create({
            'name': 'Descuento anual (empresa A)', 'offer_type': 'discount', 'discount_percent': 10,
            'date_from': DAY0, 'date_to': DAY0 + timedelta(days=30)})
        self.assertTrue(self._messages(self.ana, 'payment_validated'))
        branch = self.env['res.company'].create({'name': 'Spa Sucursal Santa Cruz'})
        other = self.env['res.users'].create({
            'name': 'Recepción Santa Cruz', 'login': 'e2e_reception_scz', 'company_id': branch.id,
            'company_ids': [Command.set(branch.ids)],
            'group_ids': [Command.set([self.env.ref('spa_base.group_spa_reception').id])]})
        # Lo que sí está protegido: membresías y reservas de la empresa A.
        self.assertFalse(self.env['spa.membership'].with_user(other).search([]))
        leaks = {model: self.env[model].with_user(other).search_count([])
                 for model in ('spa.message', 'spa.payment.offer', 'spa.cancel.policy', 'spa.entitlement')}
        self.assertEqual(leaks, dict.fromkeys(leaks, 0))

    def test_fixed_manager_cannot_create_petty_cash_fund(self):
        """docs/08 (Fondo fijo): la creación del fondo y el cambio de monto los hace el Gerente.
        l10n_bo_petty_cash solo da acceso al contador (security/ir.model.access.csv) y
        ``_check_accountant`` (models/l10n_bo_petty_cash_fund.py) exige el grupo Contador:
        el gerente del spa ni siquiera ve los fondos."""
        fund = self.env['l10n_bo.petty.cash.fund'].with_user(self.manager).create({
            'name': 'Caja chica Cocina', 'custodian_id': self.custodian.id, 'amount_fixed': 800.0,
            'bank_journal_id': self.bank_journal.id})
        fund.action_open()
        self.assertEqual(fund.sudo().state, 'open')

    def test_fixed_manager_cannot_approve_purchase(self):
        """docs/08: «> Bs 1.000 aprueba Gerente» con la doble validación estándar de Compras.
        ``group_spa_manager`` no implica ``purchase.group_purchase_manager``: ``button_approve`` del
        gerente no hace nada (sin error) y la orden queda «Por aprobar»."""
        self.company.write({'po_double_validation': 'two_step', 'po_double_validation_amount': 1000.0})
        supplier = self.env['res.partner'].create({'name': 'Química Andina S.R.L.', 'vat': '1020703023'})
        po = self.env['purchase.order'].with_user(self.buyer).create({
            'partner_id': supplier.id,
            'order_line': [Command.create({'product_id': self.env.ref('spa_pos.product_water').id,
                                           'product_qty': 300, 'price_unit': 10.0})]})
        po.button_confirm()
        self.assertEqual(po.state, 'to approve')
        po.with_user(self.manager).button_approve()
        self.assertEqual(po.state, 'purchase')


@tagged('post_install', '-at_install', 'spa', 'spa_e2e')
@freeze_time(START)
class TestSpaE2EWebRegressions(SpaE2EMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()

    def _contact_form(self, name, email, cookies=None):
        self.authenticate(None, None)
        for key, value in (cookies or {}).items():
            self.opener.cookies.set(key, value)
        response = self.url_open('/website/form/crm.lead', data={
            'contact_name': name, 'email_from': email, 'phone': '+591 71111111',
            'name': 'Quiero información del plan Premium', 'description': 'Me interesa la piscina y masajes.'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        lead_id = json.loads(response.text).get('id')
        self.assertTrue(lead_id, response.text[:300])
        return self.env['crm.lead'].browse(lead_id)

    def test_fixed_web_contact_form_lead_not_in_acquisition(self):
        """docs/06: «Formulario web → Lead en Interesado con fuente UTM». Un visitante que llega desde un
        anuncio de Instagram (cookie UTM ``odoo_utm_source``) y deja sus datos en «Contáctenos»:
        spa_crm/models/crm_lead.py ``create`` decide el embudo con ``vals.get('source_id')`` ANTES de que
        Odoo aplique la fuente por defecto de la cookie (``utm.mixin.default_get``), así que el prospecto
        cae en el equipo por defecto («Ventas») y no en Captación."""
        lead = self._contact_form('Marta Instagram', 'marta.ig@example.com', {'odoo_utm_source': 'Instagram'})
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_instagram'))
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id.spa_stage_code, 'interested')
