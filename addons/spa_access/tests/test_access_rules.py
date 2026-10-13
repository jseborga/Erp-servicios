# Part of ERP Servicios Spa. License LGPL-3.
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, freeze_time, new_test_user, tagged

from odoo.addons.spa_membership.tests.common import SpaCommon

NOW = datetime(2027, 3, 2, 15, 0, 0)  # martes 2 de marzo de 2027, 11:00 en La Paz


@tagged('post_install', '-at_install', 'spa')
@freeze_time(NOW)
class TestAccessRules(SpaCommon):
    """Horario de espacios libres, invitados pre-registrados, socios suspendidos, ingresos sin
    reserva en el aforo por franja y pase diario."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['spa.access.log']
        cls.sauna_space = cls.env.ref('spa_base.space_sauna')  # 10:00-20:00, aforo 5
        cls.pool_space = cls.env.ref('spa_base.space_pool')  # 07:00-21:00, franjas de 2 h
        cls.reception = new_test_user(cls.env, login='spa_access_reception', groups='spa_base.group_spa_reception')
        cls.visitor = cls.env['res.partner'].create({'name': 'Visitante del día', 'phone': '70000301'})

    def test_free_space_respects_opening_hours_and_closures(self):
        member = self._membership(self.plan_premium)
        with freeze_time(NOW - timedelta(hours=3)), self.assertRaisesRegex(UserError, 'cerrado'):  # 08:00
            self.Log.do_check_in(self.sauna_space, token=member.qr_token)
        self.sauna_space.write({'closure_ids': [Command.create({
            'date_from': self.today, 'date_to': self.today, 'reason': 'Mantenimiento'})]})
        with self.assertRaisesRegex(UserError, 'cerrado'):
            self.Log.do_check_in(self.sauna_space, token=member.qr_token)
        self.assertFalse(member.consumption_ids, 'No se descuenta el saldo si no ingresa')
        self.sauna_space.closure_ids.unlink()
        self.assertTrue(self.Log.do_check_in(self.sauna_space, token=member.qr_token))

    def test_preregistered_guest_enters_without_second_free_pass(self):
        member = self._membership(self.plan_basic)  # 1 free pass al mes
        guest = self.env['spa.guest'].sudo().create({
            'name': 'Carla Invitada', 'phone': '76543210', 'membership_id': member.id,
            'date': self.today, 'service_id': self.sauna.id})
        self.assertEqual(guest.charge_type, 'free_pass')
        log = self.Log.with_user(self.reception).do_check_in(self.sauna_space, token=member.qr_token, guests=1)
        self.assertEqual(log.people, 2)
        self.assertEqual(member.guest_ids, guest, 'Ingresa el invitado ya registrado')
        self.assertEqual(guest.state, 'attended')
        self.assertEqual(member.guests_this_month, 1)

    def test_suspended_member_cannot_use_previous_booking(self):
        member = self._membership(self.plan_premium)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.pool.id, 'start': NOW + timedelta(minutes=20)})
        booking.action_confirm()
        member.action_suspend()
        with self.assertRaisesRegex(UserError, 'no da acceso'):
            self.Log.with_user(self.reception).do_check_in(self.pool_space, token=member.qr_token)
        self.assertEqual(booking.state, 'confirmed')
        member.action_activate()
        log = self.Log.with_user(self.reception).do_check_in(self.pool_space, token=member.qr_token)
        self.assertEqual(log.booking_id, booking)

    def test_people_inside_without_booking_use_slot_capacity(self):
        self.pool_space.capacity = 2
        walk_in = self.Log.create({'partner_id': self.visitor.id, 'space_id': self.pool_space.id, 'people': 1})
        # Dentro desde las 11:00; salida estimada 13:00 (permanencia máxima 2 h).
        self.assertEqual(self.pool_space._seats_taken(NOW + timedelta(minutes=30), NOW + timedelta(hours=2)), 1)
        self.assertEqual(self.pool_space._seats_taken(NOW + timedelta(hours=2), NOW + timedelta(hours=4)), 0)
        slot = next(s for s in self.pool._get_slots(self.today, ignore_lead=True)
                    if s['start'] == self.tools.local_combine(self.today, 13.0))
        self.assertEqual(slot['free'], 2)
        member = self._membership(self.plan_premium)
        first = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.pool.id, 'start': NOW + timedelta(minutes=30)})
        first.action_confirm()
        other = self.env['res.partner'].create({'name': 'Otro cliente', 'phone': '70000302'})
        second = self.env['spa.booking'].create({
            'partner_id': other.id, 'payment_mode': 'single', 'service_id': self.pool.id,
            'start': NOW + timedelta(minutes=30)})
        with self.assertRaisesRegex(UserError, 'No hay cupo'):
            second.action_confirm()
        walk_in.action_check_out()
        second.action_confirm()
        self.assertEqual(second.state, 'confirmed')

    def test_day_pass(self):
        with self.assertRaisesRegex(UserError, 'pase diario'):
            self.Log.do_check_in(self.sauna_space, partner=self.visitor)
        Log = self.Log.with_user(self.reception)
        with patch.object(type(self.Log), '_after_day_pass', autospec=True, return_value=True) as hook:
            log = Log.do_check_in(self.sauna_space, partner=self.visitor, guests=1, day_pass=True)
        hook.assert_called_once()
        self.assertRecordValues(log, [{'day_pass': True, 'people': 2, 'membership_id': False,
                                       'service_id': self.sauna.id, 'partner_id': self.visitor.id}])
        self.sauna_space.invalidate_recordset(['occupancy'])
        self.assertEqual(self.sauna_space.occupancy, 2)
        with self.assertRaisesRegex(UserError, 'ya está dentro'):
            Log.do_check_in(self.sauna_space, partner=self.visitor, day_pass=True)
        group = self.env['res.partner'].create({'name': 'Grupo', 'phone': '70000303'})
        with self.assertRaisesRegex(UserError, 'lleno'):
            Log.do_check_in(self.sauna_space, partner=group, guests=3, day_pass=True)  # 2 + 4 > 5
        Log.do_check_in(self.sauna_space, partner=group, guests=2, day_pass=True)  # 5 de 5
        # Un socio también puede pagar un pase diario: no descuenta su saldo.
        member = self._membership(self.plan_basic, partner=self.env['res.partner'].create({'name': 'Socio'}))
        self.sauna_space.capacity = 10
        member_log = Log.do_check_in(self.sauna_space, partner=member.partner_id, day_pass=True)
        self.assertTrue(member_log.day_pass)
        self.assertFalse(member.consumption_ids)
        # Solo espacios libres y en horario.
        with self.assertRaisesRegex(UserError, 'reserva'):
            Log.do_check_in(self.pool_space, partner=self.visitor, day_pass=True)
        late = self.env['res.partner'].create({'name': 'Tarde', 'phone': '70000304'})
        with freeze_time(NOW + timedelta(hours=10)), self.assertRaisesRegex(UserError, 'cerrado'):  # 21:00
            Log.do_check_in(self.sauna_space, partner=late, day_pass=True)

    def test_checkin_wizard_day_pass(self):
        wizard_form = Form(self.env['spa.checkin.wizard'].with_user(self.reception).with_context(
            default_space_id=self.sauna_space.id))
        wizard_form.partner_id = self.visitor
        self.assertTrue(wizard_form.day_pass, 'Sin membresía vigente se propone el pase diario')
        wizard_form.guests = 1
        wizard = wizard_form.save()
        action = wizard.action_check_in()
        self.assertIn('pase diario', action['params']['message'])
        log = self.Log.search([('partner_id', '=', self.visitor.id)])
        self.assertTrue(log.day_pass)
        self.assertEqual(log.people, 2)
        member = self._membership(self.plan_premium)
        wizard_form = Form(self.env['spa.checkin.wizard'].with_user(self.reception).with_context(
            default_space_id=self.sauna_space.id))
        wizard_form.partner_id = member.partner_id
        self.assertFalse(wizard_form.day_pass, 'Un socio vigente usa su membresía')
