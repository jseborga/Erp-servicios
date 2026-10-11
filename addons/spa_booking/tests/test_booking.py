# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestBooking(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day = cls.today + timedelta(days=3)
        cls.member = cls._membership(cls.plan_premium, months=3)

    def _book(self, service, hour, partner=None, membership=None, day=None, guests=None, channel='reception',
              confirm=True):
        membership = membership if membership is not None else self.member
        booking = self.env['spa.booking'].create({
            'partner_id': (partner or membership.partner_id or self.partner).id,
            'membership_id': membership.id if membership else False,
            'payment_mode': 'membership' if membership else 'single',
            'service_id': service.id,
            'start': self._dt(day or self.day, hour),
            'channel': channel,
            'guest_ids': [(0, 0, {'name': name}) for name in (guests or [])],
        })
        if confirm:
            booking.action_confirm()
        return booking

    def _walk_in(self, name):
        return self.env['res.partner'].create({'name': name})

    def test_slots_reflect_capacity(self):
        slots = self.jacuzzi._get_slots(self.day)
        ten = next(s for s in slots if s['label'].startswith('10:00'))
        self.assertEqual(ten['free'], 5)
        self._book(self.jacuzzi, 10.0, partner=self._walk_in('Cliente 1'), membership=False)
        slots = self.jacuzzi._get_slots(self.day)
        ten = next(s for s in slots if s['label'].startswith('10:00'))
        self.assertEqual(ten['free'], 4)

    def test_capacity_limit(self):
        for i in range(5):
            self._book(self.jacuzzi, 11.0, partner=self._walk_in(f'Cliente {i}'), membership=False)
        with self.assertRaisesRegex(UserError, 'No hay cupo'):
            self._book(self.jacuzzi, 11.0, partner=self._walk_in('Cliente 6'), membership=False)
        # Una cancelación libera el cupo
        booking = self.env['spa.booking'].search([('service_id', '=', self.jacuzzi.id), ('state', '=', 'confirmed')], limit=1)
        booking.action_cancel()
        self._book(self.jacuzzi, 11.0, partner=self._walk_in('Cliente 7'), membership=False)

    def test_staff_assignment_and_availability(self):
        booking = self._book(self.massage, 10.0)
        self.assertTrue(booking.employee_id)
        self.massage.space_id.capacity = 2
        with self.assertRaisesRegex(UserError, 'Masajista'):
            self._book(self.massage, 10.0, partner=self._walk_in('Otro'), membership=False)

    def test_membership_consumption_and_refund(self):
        booking = self._book(self.massage, 11.0)
        entitlement = self.member._entitlement_for(self.massage, self.day)
        self.assertEqual(entitlement.used, 1)
        booking.action_cancel()
        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(entitlement.used, 0)

    def test_late_cancel_loses_session(self):
        self.plan_premium.cancel_policy_id.free_cancel_hours = 1000
        booking = self._book(self.massage, 12.0)
        entitlement = self.member._entitlement_for(self.massage, self.day)
        booking.action_cancel()
        self.assertEqual(booking.state, 'late_cancel')
        self.assertEqual(entitlement.used, 1, 'La sesión se pierde por cancelación tardía')

    def test_no_show_lose_session(self):
        booking = self._book(self.massage, 13.0)
        past = fields.Datetime.now() - timedelta(hours=3)
        booking.write({'start': past, 'stop': past + timedelta(hours=1)})
        self.env['spa.booking']._cron_booking_states()
        self.assertEqual(booking.state, 'no_show')
        self.assertEqual(sum(booking.consumption_ids.mapped('qty')), 1)

    def test_check_in_and_done(self):
        booking = self._book(self.pool, 9.0, guests=['Laura'])
        self.assertEqual(booking.seats, 2)
        self.assertEqual(booking.guest_ids.charge_type, 'free_pass')
        self.assertEqual(booking.guest_ids.date, self.day)
        booking.action_check_in()
        self.assertEqual(booking.guest_ids.state, 'attended')
        past = fields.Datetime.now() - timedelta(hours=3)
        booking.write({'start': past, 'stop': past + timedelta(hours=2)})
        self.env['spa.booking']._cron_booking_states()
        self.assertEqual(booking.state, 'done')

    def test_weekly_limit_through_bookings(self):
        monday = self._next_weekday(0, weeks_ahead=2)
        self._book(self.massage, 10.0, day=monday)
        with self.assertRaisesRegex(UserError, 'ya los usó'):
            self._book(self.massage, 10.0, day=monday + timedelta(days=1))

    def test_plan_hours_and_guest_rules(self):
        with self.assertRaisesRegex(UserError, 'horario'):
            self._book(self.jacuzzi, 19.5)  # Premium jacuzzi hasta 20:00; 19:30-20:30 se pasa
        with self.assertRaisesRegex(UserError, 'invitado'):
            self._book(self.pool, 11.0, guests=['A', 'B'])
        with self.assertRaisesRegex(UserError, 'no admite invitados'):
            self._book(self.massage, 14.0, guests=['A'])

    def test_free_access_space_needs_no_booking(self):
        with self.assertRaisesRegex(UserError, 'acceso libre'):
            self._book(self.sauna, 11.0)

    def test_outside_opening_hours_and_past(self):
        with self.assertRaisesRegex(UserError, 'fuera de la atención'):
            self._book(self.massage, 19.0, membership=False, partner=self._walk_in('Tarde'))
        with self.assertRaisesRegex(UserError, 'pasado'):
            self._book(self.pool, 9.0, day=self.today - timedelta(days=1))

    def test_double_booking_same_person(self):
        self._book(self.pool, 15.0)
        with self.assertRaisesRegex(UserError, 'otra reserva'):
            self._book(self.jacuzzi, 15.0)

    def test_max_cancellations_month(self):
        """Política estándar: a partir de la 4.ª cancelación del mes, cuenta como tardía."""
        policy = self.plan_premium.cancel_policy_id
        policy.free_cancel_hours = 0
        vip_day = self.day
        for hour in (9.0, 11.0, 13.0):
            self._book(self.pool, hour, day=vip_day).action_cancel()
        booking = self._book(self.pool, 15.0, day=vip_day)
        booking.action_cancel()
        self.assertEqual(booking.state, 'late_cancel')

    def test_slot_wizard_books(self):
        wizard = self.env['spa.booking.slot.wizard'].create({
            'partner_id': self.partner.id, 'membership_id': self.member.id,
            'service_id': self.jacuzzi.id, 'date': self.day, 'guest_names': 'Mario Rojas, +59170001111'})
        wizard.action_search()
        line = wizard.line_ids.filtered(lambda l: l.available)[:1]
        self.assertTrue(line)
        action = line.action_book()
        booking = self.env['spa.booking'].browse(action['res_id'])
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.seats, 2)
        self.assertEqual(booking.guest_ids.phone, '+59170001111')

    def test_portal_lead_time(self):
        soon = fields.Datetime.now() + timedelta(minutes=30)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': self.member.id, 'payment_mode': 'membership',
            'service_id': self.massage.id, 'start': soon, 'channel': 'portal'})
        with self.assertRaises(UserError):
            booking.action_confirm()
