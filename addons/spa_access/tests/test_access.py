# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestAccess(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sauna_space = cls.env.ref('spa_base.space_sauna')
        cls.pool_space = cls.env.ref('spa_base.space_pool')
        cls.sauna_space.write({'open_hour': 0.0, 'close_hour': 24.0})
        cls.Log = cls.env['spa.access.log']

    def test_free_space_check_in_consumes_balance(self):
        member = self._membership(self.plan_basic)
        log = self.Log.do_check_in(self.sauna_space, token=member.qr_token)
        self.assertEqual(log.method, 'qr')
        self.assertEqual(self.sauna_space.occupancy, 1)
        sauna = member._entitlement_for(self.sauna, self.today)
        self.assertEqual(sauna.used, 1)
        with self.assertRaisesRegex(UserError, 'ya está dentro'):
            self.Log.do_check_in(self.sauna_space, token=member.qr_token)
        log.action_check_out()
        self.assertEqual(self.sauna_space.occupancy, 0)

    def test_free_space_capacity(self):
        for i in range(5):
            partner = self.env['res.partner'].create({'name': f'Socio {i}'})
            member = self._membership(self.plan_premium, partner=partner)
            self.Log.do_check_in(self.sauna_space, partner=partner)
        partner = self.env['res.partner'].create({'name': 'Socio 6'})
        self._membership(self.plan_premium, partner=partner)
        with self.assertRaisesRegex(UserError, 'lleno'):
            self.Log.do_check_in(self.sauna_space, partner=partner)

    def test_check_in_with_guest_counts_quota(self):
        member = self._membership(self.plan_premium)
        log = self.Log.do_check_in(self.sauna_space, token=member.qr_token, guests=1)
        self.assertEqual(log.people, 2)
        self.assertEqual(member.guests_this_month, 1)

    def test_unknown_or_suspended_credential(self):
        with self.assertRaisesRegex(UserError, 'no reconocida'):
            self.Log.do_check_in(self.sauna_space, token='no-existe')
        member = self._membership(self.plan_premium)
        member.action_suspend()
        with self.assertRaisesRegex(UserError, 'no da acceso'):
            self.Log.do_check_in(self.sauna_space, token=member.qr_token)

    def test_slot_space_requires_booking(self):
        member = self._membership(self.plan_premium)
        with self.assertRaisesRegex(UserError, 'no tiene una reserva'):
            self.Log.do_check_in(self.pool_space, token=member.qr_token)
        # Reserva que empieza en 20 minutos (creada directamente para no depender de la hora del día)
        start = fields.Datetime.now() + timedelta(minutes=20)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.pool.id, 'start': start, 'state': 'confirmed'})
        log = self.Log.do_check_in(self.pool_space, token=member.qr_token)
        self.assertEqual(log.booking_id, booking)
        self.assertEqual(booking.state, 'checked_in')

    def test_auto_check_out(self):
        member = self._membership(self.plan_premium)
        log = self.Log.do_check_in(self.sauna_space, token=member.qr_token)
        log.check_in = fields.Datetime.now() - timedelta(hours=3)
        self.Log._cron_auto_check_out()
        self.assertEqual(log.state, 'closed')

    def test_wizard(self):
        member = self._membership(self.plan_premium)
        wizard = self.env['spa.checkin.wizard'].create({'space_id': self.sauna_space.id, 'token': member.qr_token})
        action = wizard.action_check_in()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(self.sauna_space.occupancy, 1)
