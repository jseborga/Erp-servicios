# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo.tests import TransactionCase


class SpaCommon(TransactionCase):
    """Base de pruebas del spa: usa los planes y servicios de los datos iniciales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tools = cls.env['spa.tools']
        cls.today = cls.tools.local_today()
        cls.pool = cls.env.ref('spa_base.service_pool')
        cls.sauna = cls.env.ref('spa_base.service_sauna')
        cls.jacuzzi = cls.env.ref('spa_base.service_jacuzzi')
        cls.massage = cls.env.ref('spa_base.service_massage')
        cls.plan_basic = cls.env.ref('spa_membership.plan_basic')
        cls.plan_premium = cls.env.ref('spa_membership.plan_premium')
        cls.plan_vip = cls.env.ref('spa_membership.plan_vip')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Ana Pérez (prueba)', 'phone': '+59170000001', 'email': 'ana.prueba@example.com'})

    @classmethod
    def _membership(cls, plan, months=1, partner=None, activate=True, start=None):
        period = plan.period_ids.filtered(lambda p: p.months == months)
        membership = cls.env['spa.membership'].create({
            'partner_id': (partner or cls.partner).id,
            'plan_id': plan.id,
            'period_id': period.id,
        })
        if activate:
            membership.action_activate(start_date=start)
        return membership

    def _next_weekday(self, weekday, weeks_ahead=1):
        """Fecha local del próximo ``weekday`` (0 = lunes) al menos 1 día en el futuro."""
        day = self.today + timedelta(days=1)
        while day.weekday() != weekday:
            day += timedelta(days=1)
        return day + timedelta(weeks=weeks_ahead - 1)

    def _dt(self, day, hour):
        return self.tools.local_combine(day, hour)
