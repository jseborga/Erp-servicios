# Part of ERP Servicios Spa. License LGPL-3.
"""Un mes de negocio del spa (marzo de 2027), operado por usuarios reales de cada rol.

Cada prueba es independiente (las clases de Odoo revierten la base al terminar cada método).
"""
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, freeze_time, tagged

from .common import DAY0, PNG_B64, START, SpaE2EMixin

WED, THU, FRI, SAT = DAY0 + timedelta(days=1), DAY0 + timedelta(days=2), DAY0 + timedelta(days=3), \
    DAY0 + timedelta(days=4)
NEXT_MON = DAY0 + timedelta(days=6)


@tagged('post_install', '-at_install', 'spa', 'spa_e2e')
@freeze_time(START)
class TestSpaE2EOperations(SpaE2EMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()
        cls.Membership = cls.env['spa.membership']
        cls.Booking = cls.env['spa.booking']
        cls.Lead = cls.env['crm.lead']
        cls.ana = cls._partner('Ana Rojas', '+591 70000101', 'ana.rojas@socios.example.com')
        cls.bruno = cls._partner('Bruno Salinas', '+591 70000102', 'bruno.salinas@socios.example.com')
        cls.carla = cls._partner('Carla Méndez', '+591 70000103', 'carla.mendez@socios.example.com')
        cls.dario = cls._partner('Darío Flores', '+591 70000104', 'dario.flores@socios.example.com')
        # Datos maestros de compras (los crea el administrador).
        cls.chlorine = cls.env['product.product'].create({
            'name': 'Cloro granulado 45 kg', 'type': 'consu', 'purchase_method': 'purchase',
            'categ_id': cls.env.ref('l10n_bo_spa.categ_supplies_pool').id,
            'supplier_taxes_id': [Command.set(cls.chart.ref('l10n_bo_iva_13_purchase').ids)],
            'standard_price': 1130.0})
        cls.supplier = cls.env['res.partner'].create({'name': 'Química Andina S.R.L.', 'vat': '1020703023',
                                                      'supplier_rank': 1})
        cls.plumber = cls.env['res.partner'].create({'name': 'Juan Mamani (plomero)', 'supplier_rank': 1})

    # ==================================================================
    # 1. Configuración del dueño
    # ==================================================================
    def test_01_owner_configuration(self):
        company = self.company
        self.assertTrue(company.spa_payment_qr)
        self.assertEqual(company._spa_journal('qr'), self.bank_journal)
        self.assertEqual(company._spa_journal('transfer'), self.bank_journal)
        self.assertEqual(company._spa_journal('cash'), self.cash_journal)
        # Espacios y aforos entregados (docs/03)
        self.assertRecordValues(self.space_pool | self.space_sauna | self.space_jacuzzi | self.space_massage, [
            {'capacity': 15, 'access_mode': 'slot', 'open_hour': 7.0, 'close_hour': 21.0,
             'analytic_account_id': self.area_pool.id, 'state': 'active'},
            {'capacity': 5, 'access_mode': 'free', 'open_hour': 10.0, 'close_hour': 20.0,
             'analytic_account_id': self.area_wet.id, 'state': 'active'},
            {'capacity': 5, 'access_mode': 'slot', 'open_hour': 10.0, 'close_hour': 20.0,
             'analytic_account_id': self.area_wet.id, 'state': 'active'},
            {'capacity': 1, 'access_mode': 'slot', 'open_hour': 9.0, 'close_hour': 18.0,
             'analytic_account_id': self.area_spa.id, 'state': 'active'},
        ])
        # Masaje: requiere personal; un solo masajista con turno 09-18.
        self.assertTrue(self.massage.requires_staff)
        self.assertEqual(self.massage._qualified_employees(), self.therapist_employee)
        self.assertEqual(self.therapist_employee.user_id, self.therapist)
        self.assertTrue(self.therapist_employee._spa_is_working(self._dt(WED, 10), self._dt(WED, 11)))
        self.assertFalse(self.therapist_employee._spa_is_working(self._dt(WED, 18), self._dt(WED, 19)))
        # Ajustes del spa desde la pantalla de Ajustes (el dueño tiene «Ajustes»).
        settings = self.env['res.config.settings'].with_user(self.owner).create({
            'spa_renewal_days': 7, 'spa_crm_courtesy_monthly_limit': 10, 'spa_crm_followup_days': 2})
        settings.execute()
        self.assertEqual(company.spa_renewal_days, 7)
        icp = self.env['ir.config_parameter'].sudo()
        self.assertEqual(icp.get_param('spa_crm.courtesy_monthly_limit'), '10')
        self.assertEqual(icp.get_param('spa_crm.followup_days'), '2')
        # Aforo editable sin código (cambia para nuevas reservas).
        self.space_jacuzzi.with_user(self.owner).capacity = 6
        self.assertEqual(self.jacuzzi._get_slots(WED, ignore_lead=True)[0]['capacity'], 6)
        # Planes publicados con precios y lista de precios de socio.
        self.assertEqual(self._period(self.plan_premium, 1).price, 890.0)
        self.assertEqual(self.plan_premium.pricelist_id, self.env.ref('spa_membership.pricelist_premium'))
        self.assertEqual(self.plan_premium.guest_quota, 2)
        # Restaurante y cafetería creados con sus métodos de pago.
        restaurant = self.env['pos.config']._spa_get_config('restaurant')
        self.assertEqual(restaurant.spa_analytic_account_id, self.area_restaurant)
        self.assertIn(self.env.ref('spa_pos.pm_member_account'), restaurant.payment_method_ids)

    # ==================================================================
    # 2. Prospecto de Instagram → cortesía → canje en la piscina
    # ==================================================================
    def test_02_instagram_prospect_courtesy_pass(self):
        instagram = self.env.ref('spa_crm.utm_source_instagram')
        lead = self.Lead.with_user(self.marketing).create({
            'name': 'Consulta por Instagram: Sofía Vargas',
            'contact_name': 'Sofía Vargas',
            'phone': '+591 71234567',
            'email_from': 'sofia.vargas@example.com',
            'source_id': instagram.id,
        }).sudo()
        self.assertEqual(lead.team_id, self.team_acq, 'La fuente Instagram lleva al embudo de Captación')
        self.assertEqual(lead.stage_id.spa_stage_code, 'interested')

        # Marketing emite el pase desde el prospecto (botón «Emitir pase de cortesía»).
        action = lead.with_user(self.marketing).action_spa_issue_courtesy()
        Pass = self.env['spa.courtesy.pass'].with_user(self.marketing).with_context(**action['context'])
        courtesy = Pass.create({'service_ids': [Command.set(self.pool.ids)], 'visits': 2,
                                'reason': 'Sorteo Instagram de marzo'}).sudo()
        self.assertEqual(courtesy.lead_id, lead)
        self.assertEqual(courtesy.issued_by_id, self.marketing)
        self.assertEqual(courtesy.valid_to, DAY0 + timedelta(days=15))
        self.assertEqual(lead.stage_id.spa_stage_code, 'visit')
        self.assertEqual(lead.partner_id, courtesy.partner_id)
        self.assertEqual(lead.source_id, instagram, 'Se conserva la fuente original')
        whatsapp = self._messages(courtesy.partner_id, 'courtesy_pass')
        self.assertEqual(len(whatsapp), 1)
        self.assertIn(courtesy.token, whatsapp.body)
        self.assertEqual(whatsapp.phone, '59171234567')

        # Recepción canjea el QR en la piscina (el lector acepta el código con guiones/minúsculas).
        typed = '%s-%s' % (courtesy.token[:5].lower(), courtesy.token[5:])
        log = self._check_in(self.space_pool, token=typed)
        self.assertEqual(log.courtesy_pass_id, courtesy)
        self.assertEqual(log.partner_id, courtesy.partner_id)
        self.assertEqual(log.method, 'qr')
        self.assertEqual(courtesy.visits_left, 1)
        self.assertEqual(courtesy.state, 'issued')
        self.assertTrue(lead.activity_ids, 'Se programa la llamada de seguimiento de la visita')
        # Ya está dentro: no puede volver a ingresar sin salir.
        with self._raises(UserError, 'ya está dentro'):
            self._check_in(self.space_pool, token=courtesy.token)
        log.with_user(self.reception).action_check_out()
        self.assertEqual(log.state, 'closed')

        # Segunda visita al día siguiente: agota el pase.
        with self._at(WED, 10):
            log2 = self._check_in(self.space_pool, token=courtesy.token)
            log2.with_user(self.reception).action_check_out()
        self.assertEqual(courtesy.state, 'redeemed')
        self.assertEqual(courtesy.visits_used, 2)
        with self._at(THU, 10), self._raises(UserError, 'ya se usó'):
            self._check_in(self.space_pool, token=courtesy.token)
        # No incluye otros espacios.
        other = self.env['spa.courtesy.pass'].with_user(self.marketing).create({
            'guest_name': 'Tomás Vargas', 'phone': '+591 71234599', 'service_ids': [Command.set(self.pool.ids)]}).sudo()
        self.assertNotEqual(other.lead_id, lead)
        with self._raises(UserError, 'no incluye'):
            self._check_in(self.space_sauna, token=other.token)
        # Recepción también emite cortesías, con tope mensual configurable (el gerente no tiene tope).
        self.env['ir.config_parameter'].sudo().set_param('spa_crm.courtesy_monthly_limit', 2)
        ReceptionPass = self.env['spa.courtesy.pass'].with_user(self.reception)
        first = ReceptionPass.create({'guest_name': 'Raúl Pinto', 'phone': '+591 71234501',
                                      'service_ids': [Command.set(self.sauna.ids)]})
        ReceptionPass.create({'guest_name': 'Rita Pinto', 'phone': '+591 71234502',
                              'service_ids': [Command.set(self.sauna.ids)]})
        with self._raises(UserError, 'límite de 2 pases'):
            ReceptionPass.create({'guest_name': 'Rosa Pinto', 'phone': '+591 71234503',
                                  'service_ids': [Command.set(self.sauna.ids)]})
        self.env['spa.courtesy.pass'].with_user(self.manager).create({
            'guest_name': 'Rosa Pinto', 'phone': '+591 71234503', 'service_ids': [Command.set(self.sauna.ids)]})
        # Vencimiento: el proceso diario vence los pases no usados.
        with self._at(DAY0 + timedelta(days=16), 6):
            self.env['spa.courtesy.pass']._cron_expire_passes()
            self.assertEqual(first.sudo().state, 'expired')
            with self._raises(UserError, 'venció'):
                self._check_in(self.space_sauna, token=first.sudo().token)

    # ==================================================================
    # 4. Reglas de reserva
    # ==================================================================
    def test_04_booking_rules(self):
        m_ana = self._enroll(self.ana, self.plan_premium)
        self._enroll(self.bruno, self.plan_premium)
        # Masaje del miércoles 10:00 por WhatsApp asistido.
        b1 = self._book(self.ana, self.massage, WED, 10, channel='whatsapp')
        self.assertEqual(b1.state, 'confirmed')
        self.assertEqual(b1.employee_id, self.therapist_employee)
        self.assertEqual(self._remaining(m_ana, self.massage, WED), 3)
        self.assertEqual(len(self._messages(self.ana, 'booking_confirmed')), 1)
        # Otro socio en la misma franja: cabina con aforo 1.
        with self._raises(UserError, 'No hay cupo'):
            self._book(self.bruno, self.massage, WED, 10)
        # Con una segunda cabina, el límite es el masajista (uno solo y ya ocupado).
        cabin2 = self.env['spa.space'].with_user(self.owner).create({
            'name': 'Cabina de masajes 2', 'code': 'CAB2', 'capacity': 1, 'access_mode': 'slot',
            'slot_duration': 1.0, 'open_hour': 9.0, 'close_hour': 18.0, 'analytic_account_id': self.area_spa.id})
        massage2 = self.env['spa.service'].with_user(self.owner).create({
            'name': 'Masaje relajante 60 min (cabina 2)', 'space_id': cabin2.id,
            'product_id': self.massage.product_id.id, 'duration': 1.0, 'requires_staff': True,
            'skill_id': self.massage.skill_id.id, 'guest_allowed': False})
        with self._raises(UserError, 'No hay Masajista disponible'):
            self._book(self.bruno, massage2, WED, 10, payment_mode='single')
        single = self._book(self.bruno, massage2, WED, 11, payment_mode='single')
        self.assertEqual(single.state, 'confirmed')
        self.assertRecordValues(single.invoice_id, [{'state': 'draft', 'spa_invoice_kind': 'single',
                                                     'amount_total': 280.0}])
        self.assertEqual(single.invoice_id.invoice_line_ids.analytic_distribution, {str(self.area_spa.id): 100})
        # Tope de frecuencia del plan Premium: 1 masaje por semana.
        with self._raises(UserError, 'por semana'):
            self._book(self.ana, self.massage, THU, 10)
        b_next = self._book(self.ana, self.massage, NEXT_MON, 10)
        self.assertEqual(b_next.state, 'confirmed')
        self.assertEqual(self._remaining(m_ana, self.massage, NEXT_MON), 2)
        # Horario permitido por el plan (configurable): jacuzzi Premium solo hasta las 18:00.
        jac_line = self.plan_premium._line_for_service(self.jacuzzi)
        jac_line.with_user(self.owner).hour_to = 18.0
        with self._raises(UserError, 'solo en el horario'):
            self._book(self.ana, self.jacuzzi, WED, 18)
        self._book(self.ana, self.jacuzzi, WED, 17)

        # Jacuzzi con un invitado: free pass y prospecto referido por la socia.
        guest_booking = self._book(self.ana, self.jacuzzi, THU, 11,
                                   guests=[{'name': 'Lucía Paz', 'phone': '+591 76543210'}])
        self.assertEqual(guest_booking.seats, 2)
        guest = guest_booking.guest_ids
        self.assertEqual(guest.charge_type, 'free_pass')
        lead = guest.lead_id
        self.assertRecordValues(lead, [{'team_id': self.team_acq.id, 'referred_by_partner_id': self.ana.id,
                                        'source_id': self.env.ref('spa_crm.utm_source_member_guest').id,
                                        'partner_id': guest.partner_id.id}])
        self.assertEqual(lead.stage_id.spa_stage_code, 'visit')
        self.assertEqual(len(self._messages(guest.partner_id, 'guest_welcome')), 1)
        # Dos invitados en una reserva: el plan permite 1 por reserva.
        with self._raises(UserError, 'hasta 1 invitado'):
            self._book(self.ana, self.jacuzzi, FRI, 15, guests=[{'name': 'X Uno', 'phone': '+591 76500001'},
                                                                 {'name': 'X Dos', 'phone': '+591 76500002'}])
        # Segundo invitado del mes: aún free pass (cupo Premium = 2).
        second = self._book(self.ana, self.jacuzzi, FRI, 11, guests=[{'name': 'Diego Paz', 'phone': '+591 76543211'}])
        self.assertEqual(second.guest_ids.charge_type, 'free_pass')
        self.assertFalse(self._charges_invoice(self.ana))
        self.assertEqual(m_ana.guests_this_month, 2)
        # Tercer invitado: supera el cupo → tarifa de invitado en la factura de cargos del mes.
        third = self._book(self.ana, self.jacuzzi, SAT, 11, guests=[{'name': 'Elena Vaca', 'phone': '+591 76543212'}])
        self.assertEqual(third.guest_ids.charge_type, 'fee')
        charges = self._charges_invoice(self.ana)
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges.state, 'draft')
        self.assertEqual(charges.spa_membership_id, m_ana)
        self.assertEqual(charges.invoice_line_ids.product_id, self.plan_premium.guest_fee_product_id)
        self.assertAlmostEqual(charges.amount_total, 120.0)
        self.assertEqual(charges.invoice_line_ids.analytic_distribution, {str(self.area_wet.id): 100})
        self.assertEqual(self._remaining(m_ana, self.jacuzzi, SAT), 1, '5 sesiones de jacuzzi: quedan 1')
        # Si cancela (con tiempo) la reserva del tercer invitado, se quita la tarifa y vuelve la sesión.
        third.with_user(self.reception).action_cancel()
        self.assertEqual(third.guest_ids.state, 'cancelled')
        self.assertFalse(charges.exists(), 'La factura de cargos en borrador queda sin líneas y se elimina')
        self.assertEqual(self._remaining(m_ana, self.jacuzzi, SAT), 2)
        # Ausencia del masajista (permiso registrado por RR. HH.): no se puede reservar ese día.
        self.env['resource.calendar.leaves'].create({
            'name': 'Permiso médico', 'resource_id': self.therapist_employee.resource_id.id,
            'calendar_id': self.therapist_employee.resource_calendar_id.id,
            'date_from': self._dt(FRI, 0), 'date_to': self._dt(FRI, 23, 59)})
        self.assertTrue(all(slot['reason'] == 'Sin personal disponible'
                            for slot in self.massage.sudo()._get_slots(FRI, ignore_lead=True)))
        with self._raises(UserError, 'No hay Masajista disponible'):
            self._book(self.bruno, self.massage, FRI, 10)
        # Cierre programado del jacuzzi por mantenimiento (sin código): no se reserva ese día.
        self.space_jacuzzi.with_user(self.owner).write({'closure_ids': [Command.create({
            'date_from': NEXT_MON, 'date_to': NEXT_MON, 'reason': 'Cambio de filtros'})]})
        self.assertFalse(self.jacuzzi._get_slots(NEXT_MON, ignore_lead=True))
        with self._raises(UserError, 'fuera de la atención'):
            self._book(self.bruno, self.jacuzzi, NEXT_MON, 11)
        # Recordatorio 24 h antes (proceso horario): una sola vez por reserva.
        with self._at(DAY0, 12):
            self.Booking._cron_booking_reminders()
            self.Booking._cron_booking_reminders()
        reminders = self._messages(self.ana, 'booking_reminder')
        self.assertEqual(len(reminders), 1, 'Solo el masaje del miércoles 10:00 está a 20-28 h')
        self.assertIn('10:00', reminders.body)
        self.assertTrue(b1.reminder_sent)
        # Reserva en el pasado o en un espacio de acceso libre: rechazadas.
        with self._raises(UserError, 'pasado'):
            self._book(self.ana, self.pool, DAY0, 7)
        with self._raises(UserError, 'acceso libre'):
            self._book(self.ana, self.sauna, WED, 12)

    # ==================================================================
    # 5. Acceso con QR: aforo en vivo del sauna y cabina con reserva
    # ==================================================================
    def test_05_access_qr_capacity(self):
        members = [self._enroll(self._partner('Socio Sauna %s' % index, '+591 7100010%s' % index),
                                self.plan_premium) for index in range(6)]
        with self._at(DAY0, 11):
            logs = [self._check_in(self.space_sauna, member) for member in members[:5]]
            self.space_sauna.invalidate_recordset(['occupancy', 'free_now'])
            self.assertEqual(self.space_sauna.occupancy, 5)
            self.assertEqual(self.space_sauna.free_now, 0)
            with self._raises(UserError, 'está lleno'):
                self._check_in(self.space_sauna, members[5])
            logs[0].with_user(self.reception).action_check_out()
            self.space_sauna.invalidate_recordset(['occupancy', 'free_now'])
            self.assertEqual(self.space_sauna.occupancy, 4)
            sixth = self._check_in(self.space_sauna, members[5])
            self.assertEqual(sixth.membership_id, members[5])
            self.assertEqual(sum(members[5].consumption_ids.filtered(
                lambda c: c.service_id == self.sauna).mapped('qty')), 1, 'El ingreso queda en el libro de consumos')
            # Espacio en mantenimiento: no se registran ingresos.
            self.space_sauna.with_user(self.owner).state = 'maintenance'
            with self._raises(UserError, 'no está operativo'):
                self._check_in(self.space_sauna, members[2])
            self.space_sauna.with_user(self.owner).state = 'active'
            # Credencial desconocida.
            with self._raises(UserError, 'no reconocida'):
                self._check_in(self.space_sauna, token='NO-EXISTE')
            # Cabina de masajes: exige una reserva.
            with self._raises(UserError, 'no tiene una reserva'):
                self._check_in(self.space_massage, members[1])
            booking = self._book(members[1].partner_id, self.massage, DAY0, 12)
            with self._raises(UserError, 'no tiene una reserva'):
                self._check_in(self.space_massage, members[1])  # faltan más de 30 minutos
        with self._at(DAY0, 11, 45):
            log = self._check_in(self.space_massage, members[1])
            self.assertEqual(log.booking_id, booking)
            self.assertEqual(booking.state, 'checked_in')
        with self._at(DAY0, 13, 10):
            self.env['spa.access.log']._cron_auto_check_out()
            self.Booking._cron_booking_states()
            self.assertEqual(log.state, 'closed')
            self.assertEqual(booking.state, 'done')
            # Salida automática del sauna tras la permanencia máxima (1 h).
            self.assertTrue(all(entry.state == 'closed' for entry in logs[1:] + [sixth]))
            # Socia VIP entra con 2 invitados (su plan permite 2 por visita): ocupan aforo y usan free pass.
            with self._raises(UserError, 'hasta 1 invitado'):
                self._check_in(self.space_sauna, members[2], guests=2)  # Premium: 1 invitado por visita
            vip = self._enroll(self._partner('Valeria VIP', '+591 71000199'), self.plan_vip)
            group = self._check_in(self.space_sauna, vip, guests=2)
            self.assertEqual(group.people, 3)
            self.space_sauna.invalidate_recordset(['occupancy'])
            self.assertEqual(self.space_sauna.occupancy, 3)
            self.assertEqual(vip.guest_ids.mapped('charge_type'), ['free_pass', 'free_pass'])
            self.assertEqual(set(vip.guest_ids.mapped('state')), {'attended'})

    # ==================================================================
    # 6. Cancelaciones y no-show
    # ==================================================================
    def test_06_cancellations_and_no_show(self):
        m_ana = self._enroll(self.ana, self.plan_premium)      # Estándar: 12 h, pierde la sesión
        m_carla = self._enroll(self.carla, self.plan_vip)      # Flexible: 4 h, no-show con penalidad
        m_dario = self._enroll(self.dario, self.plan_premium)
        # Cancelación con anticipación: la sesión vuelve al saldo.
        early = self._book(self.ana, self.massage, THU, 10)
        self.assertEqual(self._remaining(m_ana, self.massage, THU), 3)
        early.with_user(self.reception).action_cancel()
        self.assertEqual(early.state, 'cancelled')
        self.assertEqual(self._remaining(m_ana, self.massage, THU), 4)
        # Cancelación tardía (6 h antes): según la política Estándar pierde la sesión.
        late = self._book(self.ana, self.massage, DAY0, 15)
        late.with_user(self.reception).action_cancel()
        self.assertEqual(late.state, 'late_cancel')
        self.assertEqual(self._remaining(m_ana, self.massage, DAY0), 3)
        # El gerente devuelve la sesión como gesto comercial (ajuste manual con motivo).
        adjust = self.env['spa.consumption.adjust'].with_user(self.manager).create({
            'membership_id': m_ana.id, 'service_id': self.massage.id, 'qty': 1,
            'reason': 'Reclamo atendido: la cabina estaba fría'})
        adjust.action_apply()
        self.assertEqual(self._remaining(m_ana, self.massage, DAY0), 4)
        adjustment = m_ana.consumption_ids.filtered(lambda c: c.reason == 'manual_adjust')
        self.assertRecordValues(adjustment, [{'qty': -1, 'user_id': self.manager.id}])
        with self._raises(AccessError):
            self.env['spa.consumption.adjust'].with_user(self.reception).create({
                'membership_id': m_ana.id, 'service_id': self.massage.id, 'qty': 1, 'reason': 'x'})
        with self._raises(UserError, 'no se modifica'):
            adjustment.with_user(self.manager).write({'qty': -5})
        with self._raises(UserError, 'no se borra'):
            adjustment.with_user(self.manager).unlink()
        # Tope de 3 cancelaciones al mes (Estándar): la cuarta cuenta como tardía aunque sea con tiempo.
        m_bruno = self._enroll(self.bruno, self.plan_premium)
        for day in (THU, FRI, SAT):
            self._book(self.bruno, self.jacuzzi, day, 12).with_user(self.reception).action_cancel()
        fourth = self._book(self.bruno, self.jacuzzi, SAT + timedelta(days=1), 12)
        fourth.with_user(self.reception).action_cancel()
        self.assertEqual(fourth.state, 'late_cancel')
        self.assertEqual(self._remaining(m_bruno, self.jacuzzi, SAT), 4, 'La cuarta cancelación pierde la sesión')
        # La política se configura con penalidad: se devuelve la sesión y se cobra la penalidad.
        penalty_late = self.env.ref('spa_membership.product_penalty_late_cancel')
        self.policy_standard.with_user(self.owner).write({
            'late_cancel_action': 'fee', 'late_cancel_fee_product_id': penalty_late.id})
        fee_booking = self._book(self.dario, self.massage, DAY0, 16)
        fee_booking.with_user(self.reception).action_cancel()
        self.assertEqual(fee_booking.state, 'late_cancel')
        self.assertEqual(self._remaining(m_dario, self.massage, DAY0), 4)
        charges = self._charges_invoice(self.dario)
        self.assertAlmostEqual(charges.amount_total, 80.0)
        self.assertEqual(charges.invoice_line_ids.analytic_distribution, {str(self.area_spa.id): 100})

        # No-show: el proceso automático marca las ausencias después de la franja.
        vip_massage = self._book(self.carla, self.massage, WED, 10)
        jacuzzi = self._book(self.dario, self.jacuzzi, WED, 10)
        with self._at(WED, 10, 10):
            self.Booking._cron_booking_states()  # dentro de la tolerancia: aún no
            self.assertEqual(vip_massage.state, 'confirmed')
        with self._at(WED, 11, 20):
            self.Booking._cron_booking_states()
        self.assertEqual(vip_massage.state, 'no_show')
        self.assertEqual(self._remaining(m_carla, self.massage, WED), 8, 'Flexible: se devuelve la sesión...')
        carla_charges = self._charges_invoice(self.carla)
        self.assertAlmostEqual(carla_charges.amount_total, 100.0, msg='... y se cobra la penalidad de no-show')
        self.assertEqual(jacuzzi.state, 'no_show')
        self.assertEqual(self._remaining(m_dario, self.jacuzzi, WED), 4, 'Estándar: pierde la sesión')
        # El terapeuta marca la ausencia de su propia sesión.
        own = self._book(self.carla, self.massage, WED, 15)
        with self._at(WED, 15, 20):
            own.with_user(self.therapist).action_no_show()
        self.assertEqual(own.state, 'no_show')
        self.assertAlmostEqual(carla_charges.amount_total, 200.0)
        # Una reserva ya pasada no se cancela.
        with self._raises(UserError, 'ya no se puede cancelar'):
            vip_massage.with_user(self.reception).action_cancel()

    # ==================================================================
    # 8. Plan anual en 3 cuotas y devengo mensual
    # ==================================================================
    def _annual_installments(self, partner):
        offer = self.env['spa.payment.offer'].with_user(self.owner).create({
            'name': 'Anual en 3 cuotas sin recargo (marzo)', 'offer_type': 'installments', 'installments': 3,
            'months': 12, 'plan_ids': [Command.set(self.plan_premium.ids)],
            'date_from': date(2027, 3, 1), 'date_to': date(2027, 3, 31)})
        period = self._period(self.plan_premium, 12)
        self.assertIn(offer, self.env['spa.payment.offer']._applicable_offers(period, partner))
        membership = self.Membership.with_user(self.reception).create({
            'partner_id': partner.id, 'plan_id': self.plan_premium.id, 'period_id': period.id})
        invoice = membership.with_user(self.cashier).action_create_invoice(offer=offer).sudo()
        first = invoice._get_invoice_next_payment_values()['next_amount_to_pay']
        request = self._register_payment(membership, amount=first, method='transfer', reference='TRF-ANUAL-1')
        request.with_user(self.cashier).action_validate()
        return membership.sudo(), invoice, first

    def test_08_annual_plan_installments_and_deferral(self):
        membership, invoice, first = self._annual_installments(self.carla)
        self.assertEqual(invoice.amount_total, 9070.0)
        self.assertEqual(len(invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')), 3)
        # Tres cuotas iguales al centavo: 3.023,33 + 3.023,33 + 3.023,34.
        self.assertAlmostEqual(first, 3023.33, places=2)
        self.assertEqual(membership.state, 'active')
        self.assertEqual(membership.date_start, DAY0)
        self.assertEqual(membership.date_end, date(2028, 3, 1))
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertEqual(len(membership.entitlement_ids.filtered(lambda e: e.period_start == date(2027, 3, 1))), 4)
        self.assertEqual(len(self._messages(self.carla, 'payment_validated')), 1)
        # Factura a ingresos diferidos (215100), no a ingresos del mes.
        deferred = self._acc('l10n_bo_spa_2151')
        income = self._acc('l10n_bo_spa_41011')
        deferred_credit = -sum(invoice.line_ids.filtered(lambda l: l.account_id == deferred).mapped('balance'))
        self.assertAlmostEqual(deferred_credit, 7890.9, places=2)
        self.assertFalse(invoice.line_ids.filtered(lambda l: l.account_id == income))
        lines = membership.deferral_line_ids
        self.assertEqual(len(lines), 12)
        self.assertAlmostEqual(sum(lines.mapped('amount')), deferred_credit, places=2)
        self.assertEqual(lines.mapped('date')[:3], [date(2027, 3, 2), date(2027, 4, 2), date(2027, 5, 2)])

        # Saldos: jacuzzi «traslada máx. 2»; masaje «se pierde». Usa 1 jacuzzi en marzo y reserva uno para abril.
        self._book(self.carla, self.jacuzzi, WED, 11)
        april_booking = self._book(self.carla, self.jacuzzi, date(2027, 4, 5), 11)
        self.assertEqual(april_booking.state, 'confirmed')
        # Proceso diario: devenga el primer mes (diario DIFE: Debe 215100 / Haber 410110).
        self.Membership._cron_billing_daily()
        posted = lines.filtered(lambda l: l.state == 'posted')
        self.assertEqual(len(posted), 1)
        move = posted.move_id
        self._assert_balanced(move)
        self.assertEqual(move.journal_id, self._acc('l10n_bo_spa_journal_deferred'))
        self.assertAlmostEqual(move.line_ids.filtered(lambda l: l.account_id == deferred).debit, 657.58, places=2)
        self.assertAlmostEqual(move.line_ids.filtered(lambda l: l.account_id == income).credit, 657.58, places=2)
        # Al mes siguiente, el segundo.
        with self._at(date(2027, 4, 2), 7):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()
        self.assertEqual(len(lines.filtered(lambda l: l.state == 'posted')), 2)
        april = membership.entitlement_ids.filtered(lambda e: e.period_start == date(2027, 4, 1))
        april_jacuzzi = april.filtered(lambda e: e.service_id == self.jacuzzi)
        self.assertRecordValues(april_jacuzzi, [{'granted': 5, 'carried_in': 2, 'used': 1, 'remaining': 6,
                                                 'carry_pending': False}])
        self.assertRecordValues(april.filtered(lambda e: e.service_id == self.massage),
                                [{'granted': 4, 'carried_in': 0, 'remaining': 4}])
        planned = sum(lines.filtered(lambda l: l.state == 'planned').mapped('amount'))
        self.assertAlmostEqual(self._balance(deferred, [('partner_id', '=', self.carla.id)]), -planned, places=2)
        # Segunda cuota: no vuelve a extender la membresía.
        with self._at(date(2027, 4, 1), 10):
            second = invoice._get_invoice_next_payment_values()['next_amount_to_pay']
            self._register_payment(membership, amount=second, method='qr').with_user(self.cashier).action_validate()
        self.assertEqual(membership.date_end, date(2028, 3, 1))
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertEqual(len(membership.deferral_line_ids), 12)

    # ==================================================================
    # 9. Mora: gracia, suspensión y recuperación
    # ==================================================================
    def test_09_delinquency_cycle(self):
        membership = self._enroll(self.dario, self.plan_premium)
        premium_pricelist = self.plan_premium.pricelist_id
        self.assertEqual(membership.date_end, date(2027, 4, 1))
        self.assertEqual(membership.grace_until, date(2027, 4, 6))
        self.assertEqual(self.dario.property_product_pricelist, premium_pricelist)
        # 5 días antes: factura de renovación y aviso.
        with self._at(date(2027, 3, 27), 6, 5):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertRecordValues(renewal, [{'spa_invoice_kind': 'renewal', 'state': 'draft', 'amount_total': 890.0}])
        self.assertEqual(len(self._messages(self.dario, 'renewal_notice')), 1)
        # Vence sin pago: gracia (sigue con acceso) y oportunidad de retención.
        with self._at(date(2027, 4, 2), 6, 5):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()
            self.Membership._cron_spa_retention()
        self.assertEqual(membership.state, 'grace')
        self.assertEqual(len(self._messages(self.dario, 'grace_notice')), 1)
        retention = self.Lead.search([('spa_membership_id', '=', membership.id), ('team_id', '=', self.team_ret.id)])
        self.assertEqual(len(retention), 1)
        self.assertEqual(retention.stage_id.spa_stage_code, 'at_risk')
        self.assertEqual(retention.spa_risk_reason, 'grace')
        self.assertTrue(retention.activity_ids)
        with self._at(date(2027, 4, 3), 10):
            self.assertEqual(self._book(self.dario, self.jacuzzi, date(2027, 4, 4), 11).state, 'confirmed')
        self.assertEqual(self._renewal_count(membership), 1, 'No se duplica la factura de renovación')
        # Fin de la gracia: suspendida, sin lista de precios de socio, sin reservas ni ingresos.
        with self._at(date(2027, 4, 7), 6, 5):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()
            self.Membership._cron_spa_retention()
        self.assertEqual(membership.state, 'suspended')
        self.assertEqual(len(self._messages(self.dario, 'suspended_notice')), 1)
        self.dario.invalidate_recordset()
        self.assertNotEqual(self.dario.property_product_pricelist, premium_pricelist)
        self.assertEqual(retention.spa_risk_reason, 'suspended')
        with self._at(date(2027, 4, 7), 11):
            with self._raises(UserError, 'no da acceso'):
                self._book(self.dario, self.jacuzzi, date(2027, 4, 7), 15)
            with self._raises(UserError, 'no da acceso'):
                self._check_in(self.space_sauna, membership)
            with self._raises(UserError, 'no tiene una membresía vigente'):
                restaurant = self.env['pos.config']._spa_get_config('restaurant')
                self._pos_order(restaurant, [(self.env.ref('spa_pos.product_coffee'), 1)], partner=self.dario,
                                payments=[(self.env.ref('spa_pos.pm_member_account'), 15.0)])
        # Paga la renovación (QR): se reactiva desde hoy y se recupera al socio.
        with self._at(date(2027, 4, 8), 10):
            request = self._register_payment(membership, method='qr', reference='QR-0408')
            self.assertEqual(request.invoice_id, renewal)
            request.with_user(self.cashier).action_validate()
        self.assertEqual(membership.state, 'active')
        self.assertEqual(membership.date_end, date(2027, 5, 7))
        self.assertEqual(self.dario.property_product_pricelist, premium_pricelist)
        self.assertEqual(retention.won_status, 'won')
        self.assertEqual(retention.stage_id.spa_stage_code, 'recovered')
        self.assertEqual(len(self._messages(self.dario, 'payment_validated')), 2)
        with self._at(date(2027, 4, 8), 11):
            self.assertEqual(self._book(self.dario, self.massage, date(2027, 4, 9), 10).state, 'confirmed')

    def test_09b_retention_pipeline(self):
        """Embudo de Retención: uso bajo → por vencer → en gracia → suspendida → ex-socio."""
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('spa_crm.retention_low_usage_pct', 25)
        icp.set_param('spa_crm.retention_low_usage_day', 15)
        icp.set_param('spa_crm.retention_expiry_days', 7)
        membership = self._enroll(self.ana, self.plan_premium)
        Membership = self.Membership

        def retention():
            return self.Lead.with_context(active_test=False).search(
                [('spa_membership_id', '=', membership.id), ('team_id', '=', self.team_ret.id)])

        with self._at(date(2027, 3, 16), 7):
            Membership._cron_spa_retention()
        lead = retention()
        self.assertEqual(len(lead), 1)
        self.assertEqual(lead.spa_risk_reason, 'low_usage', 'Sin uso de masajes ni jacuzzi a mitad de mes')
        self.assertEqual(lead.stage_id.spa_stage_code, 'at_risk')
        with self._at(date(2027, 3, 26), 7):
            Membership._cron_spa_retention()
        self.assertEqual(lead.spa_risk_reason, 'expiring')
        for day, state in ((date(2027, 4, 2), 'grace'), (date(2027, 4, 7), 'suspended'), (date(2027, 7, 1), 'expired')):
            with self._at(day, 6, 5):
                Membership._cron_membership_daily()
                Membership._cron_billing_daily()
                Membership._cron_spa_retention()
            self.assertEqual(membership.state, state)
        self.assertEqual(retention(), lead, 'Una sola oportunidad por vencimiento')
        self.assertEqual(lead.spa_risk_reason, 'expired')
        self.assertEqual(lead.stage_id.spa_stage_code, 'ex_member')
        self.assertEqual(lead.won_status, 'pending')

    def _renewal_count(self, membership):
        return len(membership.invoice_ids.filtered(lambda m: m.spa_invoice_kind == 'renewal'))

    # ==================================================================
    # 10. Compras con factura SIAT, sin factura con retención y fondo fijo
    # ==================================================================
    def _flow_purchase_with_invoice(self):
        supplier = self.supplier
        po = self.env['purchase.order'].with_user(self.buyer).create({
            'partner_id': supplier.id,
            'order_line': [Command.create({'product_id': self.chlorine.id, 'product_qty': 2, 'price_unit': 1130.0})],
        })
        # Aprobación por monto (doble validación estándar): sobre Bs 1.000 aprueba el dueño (el gerente del
        # spa no puede: ver test_bug_manager_cannot_approve_purchase).
        self.company.with_user(self.owner).write({'po_double_validation': 'two_step',
                                                  'po_double_validation_amount': 1000.0})
        po.button_confirm()
        self.assertEqual(po.state, 'to approve')
        po.with_user(self.owner).button_approve()
        self.assertEqual(po.state, 'purchase')
        po.action_create_invoice()
        bill = po.sudo().invoice_ids
        self.assertEqual(len(bill), 1)
        # El contador completa los datos SIAT (como si leyera el QR); el comprador no valida
        # documentos fiscales, el contador sí.
        bill.with_user(self.accountant).write({
            'invoice_date': DAY0, 'l10n_bo_invoice_number': '1234', 'l10n_bo_cuf': self._cuf('1020703023', 1234)})
        with self._raises(AccessError):
            bill.with_user(self.buyer).action_post()
        bill.with_user(self.accountant).action_post()
        return bill, supplier

    def _flow_plumber_without_invoice(self):
        plumber = self.plumber
        maintenance = self._acc('l10n_bo_spa_5124')
        bill = self.env['account.move'].with_user(self.accountant).create({
            'move_type': 'in_invoice', 'partner_id': plumber.id, 'invoice_date': DAY0,
            'l10n_bo_doc_type': 'none', 'l10n_bo_withholding_mode': 'supplier_bears',
            'l10n_bo_purchase_kind': 'eventual',
            'invoice_line_ids': [Command.create({'name': 'Reparación de fuga en sala de máquinas',
                                                 'account_id': maintenance.id, 'price_unit': 1000.0, 'quantity': 1,
                                                 'tax_ids': [Command.clear()]})],
        })
        bill.action_l10n_bo_apply_withholding()
        bill.action_post()
        return bill.sudo()

    def _flow_petty_cash(self):
        fund = self.env['l10n_bo.petty.cash.fund'].with_user(self.accountant).create({
            'name': 'Caja chica Recepción', 'custodian_id': self.custodian.id, 'amount_fixed': 1500.0,
            'max_expense': 1200.0, 'analytic_account_id': self.area_admin.id,
            'bank_journal_id': self.bank_journal.id})
        fund.action_open()
        bookstore = self.env['res.partner'].create({'name': 'Librería Illimani', 'vat': '3115970018'})
        Voucher = self.env['l10n_bo.petty.cash.voucher'].with_user(self.custodian)
        common = {'fund_id': fund.id, 'receipt': PNG_B64, 'receipt_filename': 'comprobante.png',
                  'account_id': self._acc('l10n_bo_spa_5118').id}
        with_invoice = Voucher.create(dict(common, description='Detergente y papel', partner_id=bookstore.id,
                                           l10n_bo_doc_type='siat_online', l10n_bo_invoice_number='777',
                                           l10n_bo_cuf=self._cuf('3115970018', 777), amount=113.0))
        without_invoice = Voucher.create(dict(common, description='Escoba y baldes (mercado)',
                                              supplier_name='Pedro Condori', l10n_bo_doc_type='none',
                                              l10n_bo_withholding_mode='supplier_bears',
                                              l10n_bo_purchase_kind='goods', amount=100.0))
        self.assertEqual(without_invoice.amount_paid, 92.0)
        report = self.env['l10n_bo.petty.cash.report'].with_user(self.custodian).create({
            'fund_id': fund.id, 'cash_counted': 1295.0})
        report.action_submit()
        self.assertEqual(report.state, 'submitted')
        with self._raises(AccessError):
            report.with_user(self.custodian).action_approve()
        report.with_user(self.accountant).action_approve()
        return fund.sudo(), report.sudo(), (with_invoice | without_invoice).sudo()

    def test_10_purchases_and_petty_cash(self):
        bill, supplier = self._flow_purchase_with_invoice()
        self.assertEqual(bill.state, 'posted')
        self.assertAlmostEqual(bill.amount_total, 2260.0)
        vat_credit = self._acc('l10n_bo_1141')
        self.assertAlmostEqual(sum(bill.line_ids.filtered(lambda l: l.account_id == vat_credit).mapped('balance')),
                               293.8, places=2)
        expense = bill.invoice_line_ids
        self.assertEqual(expense.account_id, self._acc('l10n_bo_spa_5116'))
        self.assertAlmostEqual(self._area_amount(expense, self.area_pool), -1572.96, places=2)
        self.assertAlmostEqual(self._area_amount(expense, self.area_wet), -393.24, places=2)
        self.env.flush_all()
        book = self.env['l10n_bo.purchase.book'].with_user(self.accountant).search([('move_id', '=', bill.id)])
        self.assertAlmostEqual(book.amount_credit, 293.8)
        # La misma factura no se registra dos veces.
        duplicate = self.env['account.move'].with_user(self.accountant).create({
            'move_type': 'in_invoice', 'partner_id': supplier.id, 'invoice_date': DAY0,
            'l10n_bo_doc_type': 'siat_online', 'l10n_bo_invoice_number': '1234',
            'l10n_bo_cuf': self._cuf('1020703023', 1234),
            'invoice_line_ids': [Command.create({'name': 'Cloro (duplicado)', 'account_id': self._acc('l10n_bo_spa_5116').id,
                                                 'price_unit': 2260.0, 'quantity': 1,
                                                 'analytic_distribution': {str(self.area_pool.id): 100},
                                                 'tax_ids': [Command.set(self._acc('l10n_bo_iva_13_purchase').ids)]})],
        })
        self.assertTrue(duplicate.l10n_bo_duplicate_warning)
        with self._raises(UserError, bill.name):
            duplicate.action_post()

        # Plomero sin factura: retención RC-IVA 13 % + IT 3 % (el proveedor recibe el neto).
        plumber_bill = self._flow_plumber_without_invoice()
        balances = {}
        for line in plumber_bill.line_ids:
            balances[line.account_id.code] = round(balances.get(line.account_id.code, 0.0) + line.balance, 2)
        self.assertEqual(balances, {'512400': 1000.0, '212100': -840.0, '213910': -130.0, '213700': -30.0})
        self.assertAlmostEqual(self._area_amount(plumber_bill.invoice_line_ids, self.area_pool), -600.0)
        self.env['account.payment.register'].with_user(self.accountant).with_context(
            active_model='account.move', active_ids=plumber_bill.ids).create({
                'journal_id': self.bank_journal.id})._create_payments()
        self.assertIn(plumber_bill.payment_state, ('paid', 'in_payment'))

        # Fondo fijo: comprobantes del custodio, rendición, aprobación y reposición.
        fund, report, vouchers = self._flow_petty_cash()
        self.assertEqual(report.state, 'approved')
        self.assertTrue(all(voucher.state == 'posted' for voucher in vouchers))
        self.assertTrue(all(voucher.move_id.payment_state == 'paid' for voucher in vouchers))
        self.assertAlmostEqual(report.replenish_amount, 205.0)
        self._assert_balanced(report.replenish_move_id)
        self.assertAlmostEqual(fund.balance, 1500.0, msg='La cuenta del fondo vuelve a su monto fijo')
        self.assertAlmostEqual(self._balance(fund.account_id), 1500.0)
        invoice_bill = vouchers.filtered(lambda v: v.l10n_bo_doc_type == 'siat_online').move_id
        self.assertAlmostEqual(sum(invoice_bill.line_ids.filtered(lambda l: l.account_id == vat_credit)
                                   .mapped('balance')), 14.69, places=2)
        # Un comprobante del fondo con una factura ya registrada se rechaza.
        with self._raises(UserError, 'ya está registrado'):
            self.env['l10n_bo.petty.cash.voucher'].with_user(self.custodian).create({
                'fund_id': fund.id, 'description': 'Cloro (otra vez)', 'partner_id': supplier.id,
                'account_id': self._acc('l10n_bo_spa_5116').id, 'amount': 2260.0,
                'l10n_bo_doc_type': 'siat_online', 'l10n_bo_invoice_number': '1234',
                'l10n_bo_cuf': self._cuf('1020703023', 1234), 'receipt': PNG_B64})

    # ==================================================================
    # 11. Cierre del mes: integridad contable
    # ==================================================================
    def _pay_with_request(self, invoice, amount, method='cash', membership=None):
        """Caja registra y valida el pago de una factura del spa."""
        request = self.env['spa.payment.request'].with_user(self.cashier).create({
            'partner_id': invoice.partner_id.id, 'membership_id': (membership or invoice.spa_membership_id).id,
            'invoice_id': invoice.id, 'amount': amount, 'method': method, 'reference': 'CAJA-%s' % invoice.id})
        request.with_user(self.cashier).action_validate()
        return request

    def _pay_bill(self, bill):
        self.env['account.payment.register'].with_user(self.accountant).with_context(
            active_model='account.move', active_ids=bill.ids).create({
                'journal_id': self.bank_journal.id})._create_payments()

    def test_11_month_close_accounting_integrity(self):
        company = self.company
        coffee, salad, trout = (self.env.ref('spa_pos.product_%s' % name) for name in ('coffee', 'salad', 'trout'))
        member_account = self.env.ref('spa_pos.pm_member_account')
        restaurant = self.env['pos.config']._spa_get_config('restaurant')
        # ---------------- Marzo ----------------
        m_ana = self._enroll(self.ana, self.plan_premium)
        _m_carla, annual_invoice, _first = self._annual_installments(self.carla)
        visitor = self._partner('Visitante de un día', '+591 70000150')
        pool_entry = self._book(visitor, self.pool, WED, 9, payment_mode='single')
        massage_single = self._book(self.bruno, self.massage, WED, 11, payment_mode='single')
        for booking in (pool_entry, massage_single):
            self._pay_with_request(booking.invoice_id, booking.invoice_id.amount_total)
        for day, name, phone in ((THU, 'Invitada Uno', '+591 76500011'), (FRI, 'Invitado Dos', '+591 76500012'),
                                 (SAT, 'Invitada Tres', '+591 76500013')):
            self._book(self.ana, self.jacuzzi, day, 11, guests=[{'name': name, 'phone': phone}])
        walk_in_order = self._pos_order(restaurant, [(trout, 1)])
        member_order = self._pos_order(restaurant, [(coffee, 2), (salad, 1)], partner=self.ana,
                                       payments=[(member_account, None)])
        charged = member_order._spa_member_account_amount()
        self.assertAlmostEqual(charged, 67.5, places=2)
        closing = self._pos_close(walk_in_order.session_id)
        self._assert_balanced(closing)
        self._pay_with_request(member_order.account_move, charged, method='qr', membership=m_ana)
        bill, _supplier = self._flow_purchase_with_invoice()
        plumber_bill = self._flow_plumber_without_invoice()
        self._pay_bill(bill | plumber_bill)
        fund, _report, _vouchers = self._flow_petty_cash()
        self.Membership._cron_billing_daily()  # devengo de marzo
        # ---------------- 1 y 2 de abril: procesos de cierre ----------------
        with self._at(date(2027, 4, 1), 6, 5):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()  # publica los cargos de marzo y la renovación de Ana
        charges = self._charges_invoice(self.ana)
        self.assertEqual(charges.state, 'posted', 'Los cargos del mes se facturan al cerrar el mes')
        self.assertAlmostEqual(charges.amount_total, 120.0)
        with self._at(date(2027, 4, 1), 10):
            self._pay_with_request(charges, 120.0)
        with self._at(date(2027, 4, 2), 6, 5):
            self.Membership._cron_membership_daily()
            self.Membership._cron_billing_daily()  # devengo de abril

        # ---------------- Verificaciones ----------------
        self.env.flush_all()
        # a) Todo asiento publicado cuadra.
        self.env.cr.execute("""
            SELECT m.name, SUM(l.debit) - SUM(l.credit)
              FROM account_move m JOIN account_move_line l ON l.move_id = m.id
             WHERE m.state = 'posted' AND m.company_id = %s
          GROUP BY m.id, m.name
            HAVING ABS(SUM(l.debit) - SUM(l.credit)) > 0.001
        """, [company.id])
        self.assertEqual(self.env.cr.fetchall(), [])
        posted = self.env['account.move'].search_count([('state', '=', 'posted'), ('company_id', '=', company.id)])
        self.assertGreater(posted, 20)
        # b) Balance de comprobación (OCA account_financial_report) del contador: suma cero.
        wizard = self.env['trial.balance.report.wizard'].with_user(self.accountant).create({
            'date_from': date(2027, 1, 1), 'date_to': date(2027, 4, 30), 'target_move': 'posted',
            'hide_account_at_0': True, 'company_id': company.id})
        data = wizard._prepare_report_data()
        report = self.env['report.account_financial_report.trial_balance'].with_user(
            self.accountant)._get_report_values(wizard, data)
        accounts = [row for row in report['trial_balance'] if row.get('type') == 'account_type']
        self.assertTrue(accounts)
        self.assertAlmostEqual(sum(row['ending_balance'] for row in accounts), 0.0, places=2)
        self.assertAlmostEqual(sum(row['debit'] for row in accounts), sum(row['credit'] for row in accounts), places=2)
        by_code = {row['code']: row['ending_balance'] for row in accounts}
        deferred = self._acc('l10n_bo_spa_2151')
        self.assertAlmostEqual(by_code[deferred.code], self._balance(deferred), places=2)
        # c) 215100 = devengo aún no reconocido.
        planned = self.env['spa.deferral.line'].search([('state', '=', 'planned'), ('company_id', '=', company.id)])
        self.assertAlmostEqual(self._balance(deferred), -round(sum(planned.mapped('amount')), 2), places=2)
        self.assertEqual(len(planned), 10, '12 meses, 2 ya devengados (marzo y abril)')
        # d) Analítica por área: ingresos de piscina, masajes y restaurante; costos de piscina.
        Analytic = self.env['account.analytic.line']

        def area_total(area, account_xmlid):
            column = area.plan_id._column_name()
            lines = Analytic.search([('general_account_id', '=', self._acc(account_xmlid).id)])
            return round(sum(lines.filtered(lambda line: line[column] == area).mapped('amount')), 2)

        self.assertAlmostEqual(area_total(self.area_pool, 'l10n_bo_spa_41012'), 78.3, places=2)  # 90 sin IVA
        self.assertAlmostEqual(area_total(self.area_spa, 'l10n_bo_spa_41013'), 243.6, places=2)  # 280 sin IVA
        self.assertAlmostEqual(area_total(self.area_restaurant, 'l10n_bo_spa_41015'), 132.67, places=2)  # 73,95 + 23,49 + 35,23
        self.assertAlmostEqual(area_total(self.area_wet, 'l10n_bo_spa_41014'), 104.4, places=2)  # invitado
        self.assertLess(area_total(self.area_pool, 'l10n_bo_spa_5116'), 0)
        self.assertLess(area_total(self.area_pool, 'l10n_bo_spa_5124'), 0)
        self.assertLess(area_total(self.area_admin, 'l10n_bo_spa_5118'), 0)  # gastos del fondo fijo
        # e) Ninguna factura queda con 0,01 de saldo por redondeo; las cobradas quedan en cero.
        customer = self.env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                                                    ('company_id', '=', company.id)])
        dust = customer.filtered(lambda inv: 0 < inv.amount_residual <= 0.011)
        self.assertFalse(dust, 'Saldos de redondeo: %s' % dust.mapped('name'))
        for invoice in (pool_entry.invoice_id, massage_single.invoice_id, member_order.account_move, charges):
            self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual), invoice.name)
        for bill_paid in (bill, plumber_bill):
            self.assertIn(bill_paid.payment_state, ('paid', 'in_payment'))
        self.assertEqual(annual_invoice.payment_state, 'partial')
        self.assertAlmostEqual(fund.balance, fund.amount_fixed)
        # f) IVA: débito fiscal (ventas) y crédito fiscal (compras) en sus cuentas.
        self.assertLess(self._balance(self._acc('l10n_bo_2135')), 0)
        self.assertGreater(self._balance(self._acc('l10n_bo_1141')), 0)

    # ==================================================================
    # 12. Seguridad (permisos internos)
    # ==================================================================
    def test_12_security_spot_checks(self):
        bill, _supplier = self._flow_purchase_with_invoice()
        fund, _report, _vouchers = self._flow_petty_cash()
        # Recepción no ve facturas de proveedor ni fondos fijos.
        with self._raises(AccessError):
            bill.with_user(self.reception).read(['amount_total'])
        with self._raises(AccessError):
            self.env['account.move'].with_user(self.reception).search([('move_type', '=', 'in_invoice')])
        with self._raises(AccessError):
            self.env['l10n_bo.petty.cash.fund'].with_user(self.reception).search([])
        # Otro custodio no ve el fondo ni los comprobantes ajenos.
        other_custodian = self.env['res.users'].create({
            'name': 'Custodio cocina E2E', 'login': 'e2e_custodian_kitchen',
            'group_ids': [Command.set([self.env.ref('l10n_bo_petty_cash.group_petty_cash_custodian').id])]})
        self.assertFalse(self.env['l10n_bo.petty.cash.fund'].with_user(other_custodian).search([]))
        self.assertFalse(self.env['l10n_bo.petty.cash.voucher'].with_user(other_custodian).search([]))
        with self._raises(AccessError):
            fund.with_user(other_custodian).read(['name'])
        self.assertEqual(self.env['l10n_bo.petty.cash.fund'].with_user(self.custodian).search([]), fund)
        # Marketing no cambia precios de planes.
        with self._raises(AccessError):
            self._period(self.plan_premium, 1).with_user(self.marketing).write({'price': 1.0})
        # Caja valida pagos; recepción no.
        m_ana = self.Membership.with_user(self.reception).create({
            'partner_id': self.ana.id, 'plan_id': self.plan_premium.id,
            'period_id': self._period(self.plan_premium, 1).id})
        m_ana.with_user(self.cashier).action_create_invoice()
        request = self._register_payment(m_ana)
        with self._raises(UserError, 'Solo caja'):
            request.with_user(self.reception).action_validate()
        request.with_user(self.cashier).action_validate()
        # Terapeuta: solo ve sus sesiones (regla de registro).
        self._book(self.ana, self.massage, WED, 10)
        self._book(self.ana, self.pool, WED, 13)
        therapist2_user = self.env['res.users'].create({
            'name': 'Masajista 2 E2E', 'login': 'e2e_therapist2',
            'group_ids': [Command.set([self.env.ref('spa_base.group_spa_therapist').id])]})
        employee2 = self.env['hr.employee'].create({
            'name': 'Masajista 2', 'user_id': therapist2_user.id,
            'resource_calendar_id': self.therapist_employee.resource_calendar_id.id,
            'spa_skill_ids': [Command.set(self.massage.skill_id.ids)]})
        other = self.env['spa.booking'].with_user(self.reception).create({
            'partner_id': self.ana.id, 'payment_mode': 'single', 'service_id': self.massage.id,
            'employee_id': employee2.id, 'start': self._dt(THU, 15)})
        other.action_confirm()
        self.assertEqual(other.employee_id, employee2)
        visible = self.env['spa.booking'].with_user(self.therapist).search([])
        self.assertTrue(visible)
        self.assertEqual(visible.employee_id, self.therapist_employee)
        self.assertNotIn(other, visible)
        self.assertEqual(self.env['spa.booking'].with_user(therapist2_user).search([]), other)
        self.assertGreaterEqual(self.env['spa.booking'].with_user(self.reception).search_count([]), 3)
        # El terapeuta no ve datos financieros.
        with self._raises(AccessError):
            self.env['account.move'].with_user(self.therapist).search([])
        # Un usuario del portal no accede a los modelos del spa por el ORM.
        portal = self._portal_member('e2e_portal_orm', 'Socio Portal ORM')
        for model in ('spa.membership', 'spa.booking', 'spa.payment.request', 'crm.lead'):
            with self._raises(AccessError):
                self.env[model].with_user(portal).search([])
