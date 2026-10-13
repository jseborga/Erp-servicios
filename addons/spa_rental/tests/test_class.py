# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import freeze_time, tagged

from .common import MON, NOW, TUE, WED, SpaRentalCommon, utc_at


@tagged('post_install', '-at_install', 'spa')
@freeze_time(NOW)
class TestSpaClass(SpaRentalCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Enrollment = cls.env['spa.class.enrollment']
        cls.Session = cls.env['spa.class.session']

    def _sessions(self, template=None):
        return self.Session.search([('template_id', '=', (template or self.template).id)], order='start')

    def _expected_days(self, start_day, weeks=5, weekdays=(0, 2, 4)):
        last = start_day + timedelta(weeks=weeks)
        return [day for day in (start_day + timedelta(days=i) for i in range((last - start_day).days + 1))
                if day.weekday() in weekdays]

    def _enroll(self, session, partner, membership=None, user=None):
        enrollment = self.Enrollment.with_user(user or self.reception).create({
            'session_id': session.id, 'partner_id': partner.id,
            'membership_id': membership.id if membership else False,
            'payment_mode': 'membership' if membership else 'invoice'})
        enrollment.action_enroll()
        return self.Enrollment.browse(enrollment.id)

    def _add_class_to_plan(self, plan, quantity=4):
        plan.write({'line_ids': [Command.create({'service_id': self.class_service.id, 'quantity': quantity})]})

    # ------------------------------------------------------------------
    # Generación de sesiones
    # ------------------------------------------------------------------
    def test_generation_is_idempotent(self):
        self.assertFalse(self._sessions(), 'El horario de ejemplo viene inactivo')
        self._activate_template()
        sessions = self._sessions()
        expected = self._expected_days(MON)
        self.assertEqual(sessions.mapped('start'), [self._dt(day, 18) for day in expected])
        self.assertEqual(set(sessions.mapped('state')), {'planned'})
        self.assertEqual(set(sessions.mapped('capacity')), {8})
        self.assertEqual(sessions.instructor_id, self.instructor)
        self.assertEqual(sessions[0].stop, self._dt(MON, 19))
        # Repetir la generación (botón y proceso diario) no duplica.
        self.template._generate_sessions()
        self.env['spa.class.template']._cron_generate_sessions()
        self.assertEqual(self._sessions(), sessions)
        # Al día siguiente el horizonte avanza un día.
        thursday = MON + timedelta(days=3)
        with freeze_time(utc_at(thursday, 8)):
            self.env['spa.class.template']._cron_generate_sessions()
        self.assertEqual(len(self._sessions()), len(set(expected) | set(self._expected_days(thursday))))
        # Cambiar la hora rehace las sesiones futuras sin alumnos.
        self.template.start_hour = 19.0
        future = self._sessions()
        self.assertTrue(future)
        self.assertTrue(all(self.tools.to_local(s.start).hour == 19 for s in future))
        # Una sesión con alumnos se conserva; el resto se mueve.
        kept = future[0]
        self._enroll(kept, self.walk_in)
        self.template.start_hour = 20.0
        self.assertTrue(kept.exists())
        self.assertEqual(kept.state, 'planned')
        others = self._sessions() - kept
        self.assertTrue(all(self.tools.to_local(s.start).hour == 20 for s in others))
        self.assertIn('tienen alumnos inscritos', self.template.message_ids[:1].body)
        # El cupo nuevo llega a todas las sesiones futuras.
        self.template.capacity = 6
        self.assertEqual(set(self._sessions().mapped('capacity')), {6})
        # Al desactivar el horario se quitan las sesiones vacías.
        self.template.active = False
        self.assertEqual(self._sessions(), kept)

    def test_generation_skips_conflicts_and_rental_respects_classes(self):
        rental = self._rental(WED, 17, 20, event='Fiesta de fin de año')
        rental.action_confirm()
        self._activate_template()
        sessions = self._sessions()
        wednesday = sessions.filtered(lambda s: s.start == self._dt(WED, 18))
        self.assertEqual(wednesday.state, 'cancelled')
        self.assertIn('Reservado para evento: Fiesta de fin de año', wednesday.cancel_reason)
        self.assertEqual(sessions.filtered(lambda s: s.start == self._dt(MON, 18)).state, 'planned')
        # Un evento exclusivo no se confirma sobre una clase programada.
        friday = self._rental(MON + timedelta(days=4), 17, 20, event='Otra fiesta')
        with self._raises(UserError, 'La clase'):
            friday.action_confirm()
        # Al cancelar el evento, la sesión se vuelve a programar.
        rental.with_user(self.manager).action_cancel()
        wednesday.with_user(self.manager).action_replan()
        self.assertEqual(wednesday.state, 'planned')

    # ------------------------------------------------------------------
    # Aforo e instructor
    # ------------------------------------------------------------------
    def test_pool_seats_reduced_while_class_runs(self):
        self._activate_template()
        slots = {s['start']: s for s in self.pool._get_slots(MON)}
        self.assertEqual(slots[self._dt(MON, 17)]['free'], 15 - 8)
        self.assertEqual(slots[self._dt(MON, 9)]['free'], 15)
        self.assertEqual(self.space_pool._seats_taken(self._dt(MON, 18), self._dt(MON, 19)), 8)
        self.space_pool.capacity = 9
        ana = self._membership(self.plan_premium)
        bruno = self._membership(self.plan_premium, partner=self.env['res.partner'].create({'name': 'Bruno'}))
        self._booking(ana, self.pool, MON, 17)
        with self._raises(UserError, 'clase «Natación'):
            self._booking(bruno, self.pool, MON, 17)

    def test_class_service_is_not_booked_by_slot(self):
        member = self._membership(self.plan_premium)
        self._add_class_to_plan(self.plan_premium)
        booking = self.env['spa.booking'].create({
            'partner_id': member.partner_id.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.class_service.id, 'start': self._dt(TUE, 18)})
        with self._raises(UserError, 'clase grupal'):
            booking.action_confirm()
        self.assertFalse(any(s['available'] for s in self.class_service._get_slots(TUE)))
        self.assertNotEqual(self.space_pool._free_mode_service(), self.class_service)

    def test_instructor_not_double_booked(self):
        employee = self.env['hr.employee'].create({
            'name': 'Instructora y masajista', 'resource_calendar_id': self.env.ref('spa_base.calendar_spa_staff').id,
            'spa_skill_ids': [Command.set((self.env.ref('spa_base.skill_instructor')
                                           | self.env.ref('spa_base.skill_massage')).ids)]})
        template = self.env['spa.class.template'].create({
            'name': 'Aquagym martes 10:00', 'service_id': self.class_service.id, 'instructor_id': employee.id,
            'tue': True, 'start_hour': 10.0, 'duration': 1.0, 'capacity': 4})
        session = self._sessions(template)[0]
        self.assertEqual(session.start, self._dt(TUE, 10))
        start, stop = self._dt(TUE, 10), self._dt(TUE, 11)
        self.assertFalse(self.massage._free_employee(start, stop, preferred=employee))
        self.assertEqual(self.massage._free_employee(start, stop), self.env.ref('spa_base.employee_massage_therapist'))
        member = self._membership(self.plan_premium)
        booking = self.env['spa.booking'].create({
            'partner_id': member.partner_id.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.massage.id, 'start': start, 'employee_id': employee.id})
        with self._raises(UserError, 'No hay Masajista disponible'):
            booking.action_confirm()
        # Al revés: una clase no se programa sobre un masaje ya reservado.
        massage = self.env['spa.booking'].create({
            'partner_id': member.partner_id.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.massage.id, 'start': self._dt(TUE, 15), 'employee_id': employee.id})
        massage.action_confirm()
        self.assertEqual(massage.employee_id, employee)
        with self._raises(UserError, 'tiene una reserva'):
            self.Session.create({'service_id': self.class_service.id, 'instructor_id': employee.id,
                                 'start': self._dt(TUE, 15), 'capacity': 4})
        with self._raises(UserError, 'ya dicta'):
            self.Session.create({'service_id': self.class_service.id, 'instructor_id': employee.id,
                                 'start': self._dt(TUE, 10, ) + timedelta(minutes=30), 'capacity': 4})
        # Sin turno (el turno termina a las 18:00).
        with self._raises(UserError, 'no tiene turno'):
            self.Session.create({'service_id': self.class_service.id, 'instructor_id': employee.id,
                                 'start': self._dt(TUE, 19), 'capacity': 4})

    # ------------------------------------------------------------------
    # Inscripciones
    # ------------------------------------------------------------------
    def test_enrollment_capacity_with_lock(self):
        self._activate_template(capacity=2)
        session = self._sessions()[0]
        self.assertEqual(session.capacity, 2)
        students = self.env['res.partner'].create([{'name': f'Alumno {i}', 'phone': f'+591 7500000{i}'}
                                                   for i in range(3)])
        calls = []
        Session = type(session)
        original = Session._spa_lock

        def spy(records):
            calls.append(records.ids)
            return original(records)

        with patch.object(Session, '_spa_lock', spy):
            for student in students[:2]:
                self._enroll(session, student)
        self.assertEqual(calls, [session.ids, session.ids], 'Cada inscripción bloquea la fila de la sesión')
        self.assertEqual(session.enrolled_count, 2)
        self.assertEqual(session.seats_left, 0)
        with self._raises(UserError, r'está llena \(2 de 2\)'):
            self._enroll(session, students[2])
        with self._raises(ValidationError):
            session.capacity = 1
        second = self._sessions()[1]
        self._enroll(second, students[0])
        with self._raises(UserError, 'ya está inscrito'):
            self._enroll(second, students[0])

    def test_member_enrollment_consumes_entitlement(self):
        self._add_class_to_plan(self.plan_premium, quantity=4)
        member = self._membership(self.plan_premium)
        self._activate_template()
        sessions = self._sessions()
        wednesday = sessions.filtered(lambda s: s.start == self._dt(WED, 18))
        enrollment = self._enroll(wednesday, self.partner, membership=member)
        entitlement = member._entitlement_for(self.class_service, WED)
        self.assertEqual(entitlement.used, 1)
        self.assertEqual(entitlement.remaining, 3)
        self.assertEqual(enrollment.consumption_ids.qty, 1)
        self.assertFalse(enrollment.invoice_id)
        self.assertEqual(enrollment.price, 0.0)
        # Cancelación con anticipación: vuelve la sesión al saldo.
        enrollment.action_cancel()
        self.assertEqual(entitlement.used, 0)
        # Cancelación tardía: la sesión se considera usada.
        monday = sessions.filtered(lambda s: s.start == self._dt(MON, 18))
        late = self._enroll(monday, self.partner, membership=member)
        with freeze_time(utc_at(MON, 17)):
            late.action_cancel()
        self.assertEqual(late.state, 'cancelled')
        self.assertEqual(member._entitlement_for(self.class_service, MON).used, 1)
        # Sin saldo no se inscribe.
        self.plan_premium.line_ids.filtered(lambda l: l.service_id == self.class_service).quantity = 1
        member.entitlement_ids.filtered(lambda e: e.service_id == self.class_service).granted = 1
        friday = sessions.filtered(lambda s: s.start == self._dt(MON + timedelta(days=4), 18))
        with self._raises(UserError, 'No le quedan sesiones'):
            self._enroll(friday, self.partner, membership=member)

    def test_member_check_in_marks_attendance(self):
        self._add_class_to_plan(self.plan_premium)
        member = self._membership(self.plan_premium)
        self._activate_template()
        session = self._sessions()[0]
        enrollment = self._enroll(session, self.partner, membership=member)
        Log = self.env['spa.access.log']
        with freeze_time(utc_at(MON, 17, 20)):
            with self._raises(UserError, 'no tiene una reserva'):
                Log.do_check_in(self.space_pool, token=member.qr_token)  # demasiado temprano: no es la clase
        with freeze_time(utc_at(MON, 17, 45)):
            log = Log.with_user(self.reception).do_check_in(self.space_pool, token=member.qr_token)
            self.assertEqual(log.class_session_id, session)
            self.assertEqual(log.people, 0, 'El cupo ya está reservado por la clase')
            self.assertEqual(enrollment.state, 'attended')
            self.assertEqual(self.space_pool.occupancy, 0)
            # Un alumno sin membresía ingresa eligiéndolo por nombre.
            payer = self._enroll(session, self.walk_in)
            Log.do_check_in(self.space_pool, partner=self.walk_in)
            self.assertEqual(payer.state, 'attended')
        with freeze_time(utc_at(MON, 19, 5)):
            Log._cron_auto_check_out()
            self.assertEqual(log.state, 'closed')

    def test_non_member_enrollment_is_invoiced(self):
        self._activate_template()
        sessions = self._sessions()
        enrollment = self._enroll(sessions[0], self.walk_in)
        invoice = enrollment.invoice_id
        self.assertEqual(invoice.state, 'draft', 'Se valida al cobrar o al dictar la clase')
        self.assertEqual(invoice.spa_invoice_kind, 'class')
        self.assertEqual(invoice.amount_total, 80.0)
        self.assertEqual(invoice.invoice_line_ids.account_id, self.acc_class)
        self.assertEqual(invoice.invoice_line_ids.analytic_distribution, {str(self.area_events.id): 100.0})
        with self._raises(UserError, 'Solo el gerente'):
            self.Enrollment.with_user(self.reception).create({
                'session_id': sessions[2].id, 'partner_id': self.walk_in.id, 'price': 0.0})
        self._pay(enrollment, 80.0)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertEqual(enrollment.invoice_status, 'paid')
        # Sin pago: la factura se valida al dictarse la clase.
        unpaid = self._enroll(sessions[1], self.customer)
        self.assertEqual(unpaid.invoice_id.state, 'draft')
        with freeze_time(utc_at(WED, 19, 5)):
            self.Session._cron_sessions()
        self.assertEqual(sessions[1].state, 'done')
        self.assertEqual(unpaid.state, 'absent')
        self.assertEqual(unpaid.invoice_id.state, 'posted')
        self.assertEqual(unpaid.invoice_id.invoice_date, WED)

    def test_session_cancellation_notifies_and_refunds(self):
        self._add_class_to_plan(self.plan_premium)
        member = self._membership(self.plan_premium)
        self._activate_template()
        session = self._sessions().filtered(lambda s: s.start == self._dt(WED, 18))
        by_plan = self._enroll(session, self.partner, membership=member)
        unpaid = self._enroll(session, self.walk_in)
        paid = self._enroll(session, self.customer)
        self._pay(paid, 80.0)
        paid_invoice = paid.invoice_id
        self.assertEqual(paid_invoice.payment_state, 'paid')
        unpaid_invoice = unpaid.invoice_id
        wizard = self.env['spa.class.session.cancel.wizard'].with_user(self.reception).create({
            'session_ids': [Command.set(session.ids)], 'reason': 'El instructor está enfermo'})
        wizard.action_confirm()
        self.assertEqual(session.state, 'cancelled')
        self.assertEqual(set((by_plan | unpaid | paid).mapped('state')), {'cancelled'})
        self.assertEqual(member._entitlement_for(self.class_service, WED).used, 0, 'Sesión devuelta al plan')
        self.assertEqual(unpaid_invoice.state, 'cancel', 'No se cobra la clase que no se dictó')
        credit = paid.refund_move_id
        self.assertEqual(credit.move_type, 'out_refund')
        self.assertEqual(credit.state, 'draft')
        self.assertEqual(credit.amount_total, 80.0)
        self.assertEqual(credit.reversed_entry_id, paid_invoice)
        for partner in (self.partner, self.walk_in, self.customer):
            message = self._messages(partner, 'class_cancelled')
            self.assertEqual(len(message), 1)
            self.assertIn('El instructor está enfermo', message.body)
        self.assertEqual(self.space_pool._seats_taken(self._dt(WED, 18), self._dt(WED, 19)), 0, 'Se libera el cupo')

    def test_package_enrollment(self):
        self._activate_template()
        wizard = self.env['spa.class.package.wizard'].with_user(self.reception).create({
            'template_id': self.template.id, 'partner_id': self.walk_in.id})
        self.assertEqual(wizard.sessions, 12)
        self.assertEqual(wizard.price, 840.0)
        wizard.action_confirm()
        enrollments = self.Enrollment.search([('partner_id', '=', self.walk_in.id)], order='start')
        self.assertEqual(len(enrollments), 12)
        self.assertEqual(set(enrollments.mapped('state')), {'enrolled'})
        self.assertEqual(len(enrollments.invoice_id), 1)
        self.assertEqual(enrollments.invoice_id.amount_total, 840.0)
        self.assertAlmostEqual(sum(enrollments.mapped('price')), 840.0)
        self.assertEqual(enrollments.invoice_id.state, 'draft')
        # Cancelar una sesión del paquete con anticipación la descuenta de la factura en borrador.
        enrollments[-1].action_cancel()
        self.assertEqual(enrollments.invoice_id.amount_total, 770.0)

    # ------------------------------------------------------------------
    # Seguridad
    # ------------------------------------------------------------------
    def test_instructor_sees_own_sessions(self):
        self._activate_template()
        other = self.env['hr.employee'].create({
            'name': 'Otra instructora', 'resource_calendar_id': self.env.ref('spa_rental.calendar_spa_instructor').id,
            'spa_skill_ids': [Command.set(self.env.ref('spa_base.skill_instructor').ids)]})
        self.env['spa.class.template'].create({
            'name': 'Baile acuático martes', 'service_id': self.class_service.id, 'instructor_id': other.id,
            'tue': True, 'start_hour': 16.0, 'capacity': 4})
        self.assertGreater(len(self.Session.search([('instructor_id', '=', other.id)])), 0)
        own = self.Session.with_user(self.therapist).search([])
        self.assertTrue(own)
        self.assertEqual(own.instructor_id, self.instructor)
        session = own[0]
        self._enroll(session, self.walk_in)
        # El instructor abre su sesión (como el cliente web) y marca la asistencia.
        self.env.invalidate_all()
        record = session.with_user(self.therapist)
        for view_type in ('list', 'form', 'calendar'):
            self._web_read_view(self.therapist, session, view_type)
        self._web_read_view(self.therapist, session.enrollment_ids, 'form')
        for user in (self.reception, self.cashier):
            for view_type in ('list', 'form', 'calendar'):
                self._web_read_view(user, session, view_type)
            self._web_read_view(user, session.enrollment_ids, 'form')
            self._web_read_view(user, session.enrollment_ids, 'list')
            self._web_read_view(user, self.template, 'form')
        with freeze_time(utc_at(MON, 18, 5)):
            record.enrollment_ids.action_attend()
        self.assertEqual(session.attended_count, 1)
        # Recepción inscribe pero no crea horarios.
        with self._raises(Exception):
            self.env['spa.class.template'].with_user(self.reception).create({
                'name': 'X', 'service_id': self.class_service.id, 'instructor_id': self.instructor.id,
                'mon': True, 'capacity': 2})

    def test_template_validations(self):
        with self._raises(ValidationError, 'supera el aforo'):
            self.template.capacity = 20
        with self._raises(ValidationError, 'al menos un día'):
            self.template.write({'mon': False, 'wed': False, 'fri': False})
        self.env.invalidate_all()
        employee = self.env['hr.employee'].create({'name': 'Sin especialidad'})
        with self._raises(ValidationError, 'no tiene la especialidad'):
            self.template.instructor_id = employee
        self.assertEqual(fields.Datetime.now(), NOW)
