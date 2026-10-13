# Part of ERP Servicios Spa. License LGPL-3.
"""Base de pruebas de alquileres y clases.

Hora congelada: lunes 2 de noviembre de 2026, 08:00 en La Paz (UTC-4) = 12:00 UTC.
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from lxml import etree

from odoo.tests import new_test_user

from odoo.addons.spa_membership.tests.common import SpaCommon

LA_PAZ_OFFSET = timedelta(hours=4)
MON = date(2026, 11, 2)
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)


def utc_at(day, hour, minute=0):
    """Hora local de La Paz -> datetime UTC naïve."""
    return datetime.combine(day, time(hour, minute)) + LA_PAZ_OFFSET


NOW = utc_at(MON, 8)


class SpaRentalCommon(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        icp = env['ir.config_parameter'].sudo()
        for key, value in {
            'spa.timezone': 'America/La_Paz',
            'spa_messaging.provider': 'wa_link',
            'spa_rental.class_weeks_ahead': '5',
            'spa_rental.reminder_hours': '24',
            'spa_rental.class_cancel_hours': '2',
            'spa_rental.class_checkin_minutes': '30',
        }.items():
            icp.set_param(key, value)
        cls.company = env.company
        cls.chart = env['account.chart.template'].with_company(cls.company)
        cls.space_pool = env.ref('spa_base.space_pool')
        cls.space_sauna = env.ref('spa_base.space_sauna')
        cls.space_massage = env.ref('spa_base.space_massage_room')
        cls.class_service = env.ref('spa_rental.service_class_swim')
        cls.instructor = env.ref('spa_rental.employee_swim_instructor')
        cls.template = env.ref('spa_rental.class_template_swim')
        cls.pool_hour = env.ref('spa_rental.product_pool_rental_hour')
        cls.space_sauna.spa_rental_product_id = env['product.product'].create({
            'name': 'Alquiler de sauna por hora (prueba)', 'type': 'service', 'list_price': 300.0,
            'categ_id': env.ref('l10n_bo_spa.categ_rental').id})
        cls.area_events = env.ref('l10n_bo_spa.analytic_area_eventos')
        cls.acc_rental = cls.chart.ref('l10n_bo_spa_41016')
        cls.acc_class = cls.chart.ref('l10n_bo_spa_41017')
        cls.acc_deposit = cls.chart.ref('l10n_bo_spa_2162')

        def user(login, groups):
            return new_test_user(env, login=login, groups=groups, name=login.replace('_', ' ').title(),
                                 tz='America/La_Paz', company_id=cls.company.id, company_ids=[cls.company.id])

        cls.manager = user('rent_manager', 'base.group_user,spa_base.group_spa_manager')
        cls.reception = user('rent_reception', 'base.group_user,spa_base.group_spa_reception')
        cls.cashier = user('rent_cashier', 'base.group_user,spa_base.group_spa_cashier')
        cls.therapist = user('rent_instructor', 'base.group_user,spa_base.group_spa_therapist')
        cls.instructor.user_id = cls.therapist
        cls.customer = env['res.partner'].create({'name': 'Club Delfines (prueba)', 'phone': '+591 71111111',
                                                  'email': 'delfines@example.com'})
        cls.walk_in = env['res.partner'].create({'name': 'Luis Alumno (prueba)', 'phone': '+591 72222222'})

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _web_read_view(self, user, records, view_type):
        """Lee, como el cliente web, los campos que la vista muestra a ``user`` (detecta faltas de permiso)."""
        self.env.invalidate_all()
        model = records.with_user(user)
        view = model.get_views([(False, view_type)])
        fields_info = view['models'][records._name]['fields']
        tree = etree.fromstring(view['views'][view_type]['arch'])
        names = set()
        for node in tree.iter('field'):
            parent, nested = node.getparent(), False
            while parent is not None:
                if parent.tag == 'field':
                    nested = True
                    break
                parent = parent.getparent()
            if not nested:
                names.add(node.get('name'))
        spec = {name: ({'fields': {'display_name': {}}} if fields_info[name]['type'] in
                       ('many2one', 'one2many', 'many2many') else {}) for name in names}
        return model.web_read(spec)

    @contextmanager
    def _raises(self, exception, regex=None):
        """Como assertRaisesRegex, pero deshace lo escrito antes del error (savepoint) y limpia la caché."""
        checker = self.assertRaisesRegex(exception, regex) if regex else self.assertRaises(exception)
        with checker:
            with self.env.cr.savepoint():
                yield
        self.env.invalidate_all()

    def _rental(self, day, hour_from, hour_to, space=None, mode='exclusive', seats=0, deposit=0.0,
                event='Cumpleaños de Sofía', partner=None, user=None, **extra):
        vals = {
            'event_name': event,
            'partner_id': (partner or self.customer).id,
            'space_id': (space or self.space_pool).id,
            'start': self._dt(day, hour_from),
            'stop': self._dt(day, hour_to),
            'mode': mode,
            'seats': seats,
            'deposit_amount': deposit,
            'attendees': 20,
        }
        vals.update(extra)
        rental = self.env['spa.rental'].with_user(user or self.reception).create(vals)
        return self.env['spa.rental'].browse(rental.id)

    def _booking(self, membership, service, day, hour, confirm=True):
        booking = self.env['spa.booking'].create({
            'partner_id': membership.partner_id.id, 'membership_id': membership.id, 'payment_mode': 'membership',
            'service_id': service.id, 'start': self._dt(day, hour)})
        if confirm:
            booking.action_confirm()
        return booking

    def _pay(self, record, amount, user=None, kind='invoice', method='cash'):
        action = record.action_open_deposit_payment() if kind == 'deposit' else record.action_open_payment()
        context = {key[len('default_'):]: value for key, value in action['context'].items()
                   if key.startswith('default_')}
        context['amount'] = amount
        context['method'] = method
        wizard = self.env['spa.rental.payment.wizard'].with_user(user or self.cashier).create(context)
        return wizard.action_confirm()

    def _partner_balance(self, account, partner):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('partner_id', '=', partner.id), ('parent_state', '=', 'posted')])
        return sum(lines.mapped('balance'))

    def _messages(self, partner, code):
        return self.env['spa.message'].search([('partner_id', '=', partner.id), ('template_id.code', '=', code)])

    def _activate_template(self, template=None, **vals):
        template = template or self.template
        vals.setdefault('active', True)
        template.write(vals)
        return template
