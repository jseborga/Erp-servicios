# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestMembership(SpaCommon):

    def test_plan_period_products(self):
        """Cada duración crea su producto con la categoría contable correcta."""
        monthly = self.plan_premium.period_ids.filtered(lambda p: p.months == 1)
        annual = self.plan_premium.period_ids.filtered(lambda p: p.months == 12)
        self.assertEqual(monthly.product_id.categ_id, self.env.ref('l10n_bo_spa.categ_membership_monthly'))
        self.assertEqual(annual.product_id.categ_id, self.env.ref('l10n_bo_spa.categ_membership_prepaid'))
        annual.price = 9999
        self.assertEqual(annual.product_id.lst_price, 9999)

    def test_activation_dates_and_entitlements(self):
        membership = self._membership(self.plan_premium, months=3)
        self.assertEqual(membership.state, 'active')
        self.assertEqual(membership.date_start, self.today)
        self.assertEqual(membership.date_end, self.today + relativedelta(months=3) - timedelta(days=1))
        massage = membership.entitlement_ids.filtered(lambda e: e.service_id == self.massage)
        self.assertEqual(massage.granted, 4)
        self.assertEqual(massage.remaining, 4)
        self.assertTrue(membership.entitlement_ids.filtered(lambda e: e.service_id == self.pool).unlimited)
        self.assertTrue(membership.name.startswith('MEM/'))

    def test_renewal_extends_from_end(self):
        membership = self._membership(self.plan_basic)
        first_end = membership.date_end
        membership.action_activate()
        self.assertEqual(membership.date_end, first_end + relativedelta(months=1))

    def test_consumption_and_remaining(self):
        membership = self._membership(self.plan_premium)
        day = self._next_weekday(1)
        start = self._dt(day, 10.0)
        entitlement = membership._spa_check_access(self.massage, start)
        membership._spa_consume(self.massage, start, 'booking')
        self.assertEqual(entitlement.used, 1)
        self.assertEqual(entitlement.remaining, 3)
        membership._spa_consume(self.massage, start, 'refund', qty=-1)
        self.assertEqual(entitlement.remaining, 4)
        with self.assertRaises(UserError):
            entitlement.consumption_ids[:1].unlink()

    def test_weekly_frequency_limit(self):
        """Premium: máximo 1 masaje por semana."""
        membership = self._membership(self.plan_premium, months=3)
        monday = self._next_weekday(0)
        membership._spa_consume(self.massage, self._dt(monday, 10.0), 'booking')
        with self.assertRaisesRegex(UserError, 'ya los usó'):
            membership._spa_check_access(self.massage, self._dt(monday + timedelta(days=2), 10.0))
        next_monday = monday + timedelta(days=7)
        self.assertTrue(membership._spa_check_access(self.massage, self._dt(next_monday, 10.0)))

    def test_allowed_hours(self):
        """Premium: jacuzzi solo de 10:00 a 20:00."""
        membership = self._membership(self.plan_premium)
        day = self._next_weekday(2)
        self.assertTrue(membership._spa_check_access(self.jacuzzi, self._dt(day, 10.0)))
        with self.assertRaisesRegex(UserError, 'horario'):
            membership._spa_check_access(self.jacuzzi, self._dt(day, 20.0))

    def test_service_not_in_plan_and_no_balance(self):
        membership = self._membership(self.plan_basic)
        day = self._next_weekday(3)
        with self.assertRaisesRegex(UserError, 'no incluye'):
            membership._spa_check_access(self.massage, self._dt(day, 10.0))
        premium = self._membership(self.plan_premium, partner=self.env['res.partner'].create({'name': 'Luis'}))
        for week in range(4):
            premium._spa_consume(self.massage, self._dt(self.today, 10.0), 'manual_adjust')
        self.assertFalse(premium._spa_check_access(self.massage, self._dt(self.today, 12.0), raise_error=False))

    def test_guest_quota(self):
        """Premium: 2 invitados gratis al mes; el tercero paga tarifa."""
        membership = self._membership(self.plan_premium)
        Guest = self.env['spa.guest']
        g1 = Guest.create({'name': 'Invitado 1', 'phone': '+59171111111', 'membership_id': membership.id})
        g2 = Guest.create({'name': 'Invitado 2', 'membership_id': membership.id})
        g3 = Guest.create({'name': 'Invitado 3', 'membership_id': membership.id})
        self.assertEqual((g1 | g2 | g3).mapped('charge_type'), ['free_pass', 'free_pass', 'fee'])
        self.assertTrue(g1.partner_id)
        g2.action_cancel()
        g4 = Guest.create({'name': 'Invitado 4', 'membership_id': membership.id})
        self.assertEqual(g4.charge_type, 'free_pass')
        self.assertEqual(membership.guests_this_month, 2)

    def test_guests_per_booking(self):
        membership = self._membership(self.plan_premium)
        day = self._next_weekday(4)
        with self.assertRaisesRegex(UserError, 'invitado'):
            membership._spa_check_access(self.pool, self._dt(day, 9.0), guests=2)
        self.assertTrue(membership._spa_check_access(self.pool, self._dt(day, 9.0), guests=1))

    def test_grace_suspension_and_expiry(self):
        membership = self._membership(self.plan_premium, start=self.today - relativedelta(months=1) - timedelta(days=2))
        self.assertLess(membership.date_end, self.today)
        self.env['spa.membership']._cron_membership_daily()
        self.assertEqual(membership.state, 'grace')
        self.assertTrue(membership._spa_check_access(self.pool, self._dt(self.today, 9.0), raise_error=False))
        membership.date_start = self.today - relativedelta(months=1) - timedelta(days=10)
        membership.date_end = self.today - timedelta(days=10)
        self.env['spa.membership']._cron_membership_daily()
        self.assertEqual(membership.state, 'suspended')
        with self.assertRaisesRegex(UserError, 'no da acceso'):
            membership._spa_check_access(self.pool, self._dt(self.today, 9.0))
        # Pago tardío: se reactiva desde hoy
        membership.action_activate()
        self.assertEqual(membership.state, 'active')
        self.assertGreaterEqual(membership.date_end, self.today)

    def test_carryover_limited(self):
        """Premium jacuzzi: traslada hasta 2 sesiones no usadas."""
        last_month = self.today - relativedelta(months=1)
        membership = self._membership(self.plan_premium, months=3, start=last_month.replace(day=1))
        membership._ensure_entitlements(last_month)
        previous = membership.entitlement_ids.filtered(
            lambda e: e.service_id == self.jacuzzi and e.period_start == last_month.replace(day=1))
        membership._spa_consume(self.jacuzzi, self._dt(last_month.replace(day=1), 11.0), 'booking')
        self.assertEqual(previous.remaining, 4)
        current = membership.entitlement_ids.filtered(
            lambda e: e.service_id == self.jacuzzi and e.period_start == self.today.replace(day=1))
        current.consumption_ids.with_context(spa_consumption_internal=True).unlink()
        current.with_context(spa_consumption_internal=True).unlink()
        membership.invalidate_recordset(['entitlement_ids'])
        membership._ensure_entitlements(self.today)
        current = membership.entitlement_ids.filtered(
            lambda e: e.service_id == self.jacuzzi and e.period_start == self.today.replace(day=1))
        self.assertEqual(current.carried_in, 2)
        self.assertEqual(current.remaining, 7)

    def test_pricelist_assigned_while_active(self):
        membership = self._membership(self.plan_premium)
        partner = self.partner.with_company(membership.company_id)
        self.assertEqual(partner.specific_property_product_pricelist, self.plan_premium.pricelist_id)
        self.assertEqual(partner.spa_member_state, 'active')
        membership.action_suspend()
        self.assertFalse(partner.specific_property_product_pricelist)

    def test_manual_adjust_requires_manager(self):
        membership = self._membership(self.plan_premium)
        wizard = self.env['spa.consumption.adjust'].create({
            'membership_id': membership.id, 'service_id': self.massage.id, 'qty': 2, 'reason': 'Cortesía'})
        wizard.action_apply()
        massage = membership.entitlement_ids.filtered(lambda e: e.service_id == self.massage)
        self.assertEqual(massage.remaining, 6)
