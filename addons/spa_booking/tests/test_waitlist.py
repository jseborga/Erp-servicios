# Part of ERP Servicios Spa. License LGPL-3.
from datetime import date, datetime, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import freeze_time, new_test_user, tagged

from odoo.addons.spa_membership.tests.common import SpaCommon

NOW = datetime(2027, 3, 2, 13, 0, 0)  # martes 2 de marzo de 2027, 09:00 en La Paz
WED = date(2027, 3, 3)


@tagged('post_install', '-at_install', 'spa')
@freeze_time(NOW)
class TestBookingWaitlist(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Waitlist = cls.env['spa.booking.waitlist']
        cls.member = cls._membership(cls.plan_premium, months=3)
        cls.jacuzzi_space = cls.jacuzzi.space_id
        cls.jacuzzi_space.capacity = 1
        cls.start = cls.tools.local_combine(WED, 11.0)
        cls.reception = new_test_user(cls.env, login='spa_wl_reception', groups='spa_base.group_spa_reception')
        cls.manager = new_test_user(cls.env, login='spa_wl_manager', groups='spa_base.group_spa_manager')
        cls.env['ir.config_parameter'].sudo().set_param('spa_booking.waitlist_priority_minutes', '30')
        cls.env.ref('spa_messaging.tpl_waitlist_available').active = True

    def _walk_in(self, name, phone):
        return self.env['res.partner'].create({'name': name, 'phone': phone})

    def _book(self, partner, start=None, service=None, membership=None, user=None, guests=()):
        booking = self.env['spa.booking'].with_user(user or self.env.user).create({
            'partner_id': partner.id,
            'membership_id': membership.id if membership else False,
            'payment_mode': 'membership' if membership else 'single',
            'service_id': (service or self.jacuzzi).id,
            'start': start or self.start,
            'guest_ids': [Command.create({'name': name}) for name in guests],
        })
        booking.action_confirm()
        return booking

    def _slot(self, service=None, partner=None, day=WED, hour=11.0):
        service = (service or self.jacuzzi)
        if partner:
            service = service.with_context(spa_waitlist_partner_id=partner.id)
        start = self.tools.local_combine(day, hour)
        return next(slot for slot in service._get_slots(day, ignore_lead=True) if slot['start'] == start)

    def test_waitlist_fifo_notification_and_priority(self):
        ana = self._walk_in('Ana Espera', '70000201')
        booking_a = self._book(ana)
        slot = self._slot()
        self.assertFalse(slot['available'])
        self.assertTrue(slot['waitlist'])
        self.assertEqual(slot['code'], 'full')

        bruno = self._walk_in('Bruno Espera', '70000202')
        carla = self._walk_in('Carla Espera', '70000203')
        entry_b = self.Waitlist._spa_join(bruno, self.jacuzzi, self.start, channel='phone')
        entry_c = self.Waitlist._spa_join(carla, self.jacuzzi, fields.Datetime.to_string(self.start))
        self.assertEqual((entry_b.state, entry_b.position, entry_b.seats), ('waiting', 1, 1))
        self.assertEqual((entry_c.state, entry_c.position, entry_c.channel), ('waiting', 2, 'portal'))
        self.assertEqual(self.Waitlist._spa_join(bruno, self.jacuzzi, self.start), entry_b, 'Sin duplicados')

        # Se libera el cupo: se avisa solo al primero y se le guarda el cupo 30 minutos.
        booking_a.action_cancel()
        self.assertEqual(entry_b.state, 'notified')
        self.assertEqual(entry_c.state, 'waiting')
        self.assertEqual(entry_b.priority_until, NOW + timedelta(minutes=30))
        message = entry_b.spa_message_id
        self.assertEqual(message.template_id.code, 'waitlist_available')
        self.assertEqual(message.phone, '59170000202')
        self.assertIn('30 minutos', message.body)
        self.assertIn('11:00', message.body)

        # Nadie más toma el cupo guardado...
        self.assertEqual(self._slot()['free'], 0)
        diego = self._walk_in('Diego Apurado', '70000204')
        with self.assertRaisesRegex(UserError, 'No hay cupo'):
            self._book(diego)
        # ...salvo la persona avisada, que lo ve libre y reserva.
        self.assertEqual(self._slot(partner=bruno)['free'], 1)
        booking_b = self._book(bruno)
        self.assertEqual(booking_b.state, 'confirmed')
        self.assertEqual(entry_b.state, 'booked')
        self.assertEqual(entry_b.booking_id, booking_b)
        entry_c.invalidate_recordset(['position'])
        self.assertEqual(entry_c.position, 1)

    def test_priority_expires_and_next_is_notified(self):
        booking_a = self._book(self._walk_in('Ana', '70000211'))
        entry_b = self.Waitlist._spa_join(self._walk_in('Bruno', '70000212'), self.jacuzzi, self.start)
        entry_c = self.Waitlist._spa_join(self._walk_in('Carla', '70000213'), self.jacuzzi, self.start)
        booking_a.action_cancel()
        self.assertEqual(entry_b.state, 'notified')
        with freeze_time(NOW + timedelta(minutes=31)):
            self.Waitlist._cron_waitlist()
        self.assertEqual(entry_b.state, 'expired')
        self.assertEqual(entry_c.state, 'notified')
        # Se retira: el cupo pasa a la lista (vacía) y queda libre.
        entry_c.action_cancel()
        self.assertEqual(entry_c.state, 'cancelled')
        self.assertEqual(self._slot()['free'], 1)

    def test_entries_fit_by_seats_and_expire_after_start(self):
        self.jacuzzi_space.capacity = 2
        booking_a = self._book(self.partner, membership=self.member, guests=['Invitada'])  # 2 cupos
        group = self.Waitlist._spa_join(self._walk_in('Grupo', '70000221'), self.jacuzzi, self.start, guests=1)
        single = self.Waitlist._spa_join(self._walk_in('Solo', '70000222'), self.jacuzzi, self.start)
        self.assertEqual(group.seats, 2)
        # Se cancela el invitado (se libera 1 cupo): el grupo no cabe, se avisa al siguiente que sí.
        booking_a.guest_ids.action_cancel()
        self.Waitlist._cron_waitlist()
        self.assertEqual(group.state, 'waiting')
        self.assertEqual(single.state, 'notified')
        # La franja empieza: lo pendiente vence.
        with freeze_time(self.start + timedelta(minutes=1)):
            self.Waitlist._cron_waitlist()
        self.assertEqual(group.state, 'expired')

    def test_join_validations(self):
        partner = self._walk_in('Valida', '70000231')
        with self.assertRaisesRegex(UserError, 'Todavía hay cupo'):
            self.Waitlist._spa_join(partner, self.jacuzzi, self.start)
        with self.assertRaisesRegex(UserError, 'acceso libre'):
            self.Waitlist._spa_join(partner, self.sauna, self.start)
        with self.assertRaisesRegex(UserError, 'ya empezó'):
            self.Waitlist._spa_join(partner, self.jacuzzi, NOW - timedelta(hours=1))
        with self.assertRaisesRegex(UserError, 'fuera de la atención'):
            self.Waitlist._spa_join(partner, self.jacuzzi, self.tools.local_combine(WED, 21.0))
        self._book(partner)
        with self.assertRaisesRegex(UserError, 'ya tiene una reserva'):
            self.Waitlist._spa_join(partner, self.jacuzzi, self.start)
        # Con membresía: se validan las reglas del plan (Premium: jacuzzi 10:00-20:00, 1 invitado).
        with self.assertRaisesRegex(UserError, 'invitado'):
            self.Waitlist._spa_join(self.partner, self.jacuzzi, self.start, membership=self.member, guests=2)

    def test_reception_wizard_joins_waitlist(self):
        self._book(self._walk_in('Ocupa', '70000241'))
        wizard = self.env['spa.booking.slot.wizard'].with_user(self.reception).create({
            'partner_id': self.partner.id, 'membership_id': self.member.id, 'service_id': self.jacuzzi.id,
            'date': WED, 'channel': 'whatsapp'})
        wizard.action_search()
        line = wizard.line_ids.filtered(lambda l: l.start == self.start)
        self.assertFalse(line.available)
        self.assertTrue(line.can_wait)
        action = line.action_waitlist()
        entry = self.Waitlist.browse(action['res_id'])
        self.assertRecordValues(entry, [{'partner_id': self.partner.id, 'membership_id': self.member.id,
                                         'channel': 'whatsapp', 'state': 'waiting'}])
        self.assertEqual(entry.with_user(self.reception).action_book()['context']['default_service_id'],
                         self.jacuzzi.id)

    # ------------------------------------------------------------------
    # Permisos (regresión de las pruebas de punta a punta)
    # ------------------------------------------------------------------
    def test_reception_books_massage_with_staff(self):
        """Recepción busca franjas y confirma un masaje: el sistema asigna al masajista."""
        self.env.invalidate_all()
        wizard = self.env['spa.booking.slot.wizard'].with_user(self.reception).create({
            'partner_id': self.partner.id, 'membership_id': self.member.id, 'service_id': self.massage.id,
            'date': WED})
        wizard.action_search()
        line = wizard.line_ids.filtered('available')[:1]
        self.assertTrue(line)
        action = line.action_book()
        booking = self.env['spa.booking'].browse(action['res_id'])
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.employee_id, self.env.ref('spa_base.employee_massage_therapist'))

    def test_therapist_reads_own_session_and_its_guests(self):
        therapist = new_test_user(self.env, login='spa_wl_therapist', groups='spa_base.group_spa_therapist')
        employee = self.env.ref('spa_base.employee_massage_therapist')
        employee.user_id = therapist
        self.massage.guest_allowed = True
        self.massage.space_id.capacity = 2
        self.plan_premium._line_for_service(self.massage).guests_per_booking = 1
        session = self._book(self.partner, service=self.massage, membership=self.member,
                             start=self.tools.local_combine(WED, 10.0), guests=['Acompañante'])
        other = self._book(self._walk_in('Otro', '70000251'), start=self.tools.local_combine(WED, 15.0),
                           service=self.pool)
        self.assertEqual(session.employee_id, employee)
        self.env.invalidate_all()
        Booking = self.env['spa.booking'].with_user(therapist)
        fields_info = Booking.get_views([(False, 'form')])['models']['spa.booking']['fields']
        spec = {name: ({'fields': {'display_name': {}}} if info['type'] in ('many2one', 'one2many', 'many2many')
                       else {}) for name, info in fields_info.items()}
        values = session.with_user(therapist).web_read(spec)[0]
        self.assertEqual(len(values['guest_ids']), 1)
        guests = self.env['spa.guest'].with_user(therapist).search([])
        self.assertEqual(guests, session.guest_ids, 'Solo ve los invitados de sus sesiones')
        self.assertFalse(Booking.search([('id', '=', other.id)]))

    def test_freeze_requires_cancelling_bookings(self):
        self.plan_premium.freeze_max_days = 30
        booking = self._book(self.partner, membership=self.member)
        with self.assertRaisesRegex(UserError, 'Cancele primero'):
            self.member.with_user(self.manager)._spa_freeze(WED, WED + timedelta(days=4), 'Viaje')
        booking.action_cancel()
        self.member.with_user(self.manager)._spa_freeze(WED, WED + timedelta(days=4), 'Viaje')
        with self.assertRaisesRegex(UserError, 'congelada'):
            self._book(self.partner, membership=self.member, start=self.tools.local_combine(WED, 12.0))
