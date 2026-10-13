# Part of ERP Servicios Spa. License LGPL-3.
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import freeze_time, new_test_user, tagged

from .common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
@freeze_time('2027-03-02 14:00:00')  # martes 2 de marzo de 2027, 10:00 en La Paz
class TestMembershipFreeze(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='spa_freeze_manager', groups='spa_base.group_spa_manager')
        cls.reception = new_test_user(cls.env, login='spa_freeze_reception', groups='spa_base.group_spa_reception')
        cls.plan_premium.freeze_max_days = 30
        cls.member = cls._membership(cls.plan_premium, months=3)  # 02/03/2027 - 01/06/2027

    def _freeze(self, date_from, date_to, reason='Viaje', user=None):
        return self.member.with_user(user or self.manager)._spa_freeze(date_from, date_to, reason)

    def test_freeze_extends_end_and_blocks_access(self):
        self.assertEqual(self.member.date_end, date(2027, 6, 1))
        freeze = self._freeze(date(2027, 3, 10), date(2027, 3, 19))
        self.assertEqual(freeze.days, 10)
        self.assertEqual(freeze.date_end_before, date(2027, 6, 1))
        self.assertEqual(self.member.date_end, date(2027, 6, 11))
        self.assertEqual(self.member.grace_until, date(2027, 6, 16))
        with self.assertRaisesRegex(UserError, 'congelada del 10/03/2027 al 19/03/2027'):
            self.member._spa_check_access(self.sauna, self._dt(date(2027, 3, 15), 11.0))
        self.assertFalse(self.member._spa_check_access(self.sauna, self._dt(date(2027, 3, 19), 11.0),
                                                       raise_error=False))
        self.assertTrue(self.member._spa_check_access(self.sauna, self._dt(date(2027, 3, 20), 11.0)))
        self.assertTrue(self.member._spa_check_access(self.sauna, self._dt(date(2027, 3, 9), 11.0)))
        self.assertFalse(self.member.frozen_until, 'Hoy no está congelada')
        with freeze_time('2027-03-12 14:00:00'):
            self.member.invalidate_recordset(['frozen_until'])
            self.assertEqual(self.member.frozen_until, date(2027, 3, 19))

    def test_freeze_rules(self):
        self.plan_premium.freeze_max_days = 0
        with self.assertRaisesRegex(UserError, 'no permite congelar'):
            self._freeze(date(2027, 3, 10), date(2027, 3, 12))
        self.plan_premium.freeze_max_days = 30
        with self.assertRaisesRegex(UserError, 'Solo el gerente'):
            self._freeze(date(2027, 3, 10), date(2027, 3, 12), user=self.reception)
        with self.assertRaisesRegex(UserError, 'pasado'):
            self._freeze(date(2027, 3, 1), date(2027, 3, 5))
        with self.assertRaisesRegex(UserError, 'vencimiento'):
            self._freeze(date(2027, 5, 25), date(2027, 6, 5))
        self._freeze(date(2027, 3, 10), date(2027, 3, 29))  # 20 días
        with self.assertRaisesRegex(UserError, 'Ya hay un congelamiento'):
            self._freeze(date(2027, 3, 25), date(2027, 4, 2))
        with self.assertRaisesRegex(UserError, 'Quedan 10 días'):
            self._freeze(date(2027, 4, 10), date(2027, 4, 24))  # 15 > 10 disponibles
        self._freeze(date(2027, 4, 10), date(2027, 4, 19))  # los 10 restantes
        self.assertEqual(self.member._spa_frozen_days(2027), 30)
        self.member.action_suspend()
        with self.assertRaisesRegex(UserError, 'activa'):
            self._freeze(date(2027, 5, 1), date(2027, 5, 2))

    def test_freeze_wizard_and_cancel(self):
        action = self.member.with_user(self.manager).action_open_freeze_wizard()
        wizard = self.env['spa.membership.freeze.wizard'].with_user(self.manager).with_context(
            **action['context']).create({'date_from': date(2027, 3, 20), 'date_to': date(2027, 3, 26),
                                         'reason': 'Certificado médico'})
        self.assertEqual(wizard.days, 7)
        self.assertEqual(wizard.days_left, 30)
        self.assertEqual(wizard.date_end_new, date(2027, 6, 8))
        wizard.action_apply()
        self.assertEqual(self.member.date_end, date(2027, 6, 8))
        freeze = self.member.freeze_ids
        self.assertEqual(freeze.reason, 'Certificado médico')
        # Anular antes de que empiece: vuelve el vencimiento.
        with self.assertRaisesRegex(UserError, 'gerente'):
            freeze.with_user(self.reception).action_cancel()
        freeze.with_user(self.manager).action_cancel()
        self.assertEqual(freeze.state, 'cancelled')
        self.assertEqual(self.member.date_end, date(2027, 6, 1))
        self.assertEqual(self.member._spa_frozen_days(2027), 0)
        # Ya empezado: no se anula.
        started = self._freeze(date(2027, 3, 2), date(2027, 3, 4))
        with self.assertRaisesRegex(UserError, 'ya empezó'):
            started.with_user(self.manager).action_cancel()

    def test_freeze_counts_days_per_calendar_year(self):
        member = self._membership(self.plan_premium, months=12, partner=self.env['res.partner'].create(
            {'name': 'Socio anual', 'phone': '70000991'}))
        member.with_user(self.manager)._spa_freeze(date(2027, 12, 20), date(2028, 1, 10), 'Vacaciones')
        self.assertEqual(member._spa_frozen_days(2027), 12)
        self.assertEqual(member._spa_frozen_days(2028), 10)
        self.assertEqual(member.date_end, date(2028, 3, 1) + timedelta(days=22))
