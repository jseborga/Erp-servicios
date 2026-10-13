# Part of ERP Servicios Spa. License LGPL-3.
import re
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'spa')
class TestSpaClassPortal(HttpCase):
    """Web del socio: ver clases de su plan, inscribirse (descuenta saldo) y cancelar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('spa_rental.class_cancel_hours', '2')
        cls.service = env.ref('spa_rental.service_class_swim')
        cls.template = env.ref('spa_rental.class_template_swim')
        plan = env.ref('spa_membership.plan_premium')
        plan.write({'line_ids': [Command.create({'service_id': cls.service.id, 'quantity': 4})]})
        cls.user = new_test_user(env, login='class_portal', groups='base.group_portal', name='Socia Portal')
        cls.user.partner_id.phone = '+591 74444444'
        cls.membership = env['spa.membership'].create({
            'partner_id': cls.user.partner_id.id, 'plan_id': plan.id,
            'period_id': plan.period_ids.filtered(lambda p: p.months == 1).id})
        cls.membership.action_activate()
        cls.other = env['res.partner'].create({'name': 'Otro alumno', 'phone': '+591 75555555'})
        cls.template.write({'active': True})

    def _token(self, html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_portal_enroll_and_cancel(self):
        now = fields.Datetime.now()
        session = self.env['spa.class.session'].search([
            ('template_id', '=', self.template.id), ('state', '=', 'planned'),
            ('start', '>', now + timedelta(hours=3)), ('start', '<', now + timedelta(days=13))], order='start', limit=1)
        self.assertTrue(session)
        self.authenticate('class_portal', 'class_portal')
        response = self.url_open('/my/spa/classes')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Inscribirme', response.text)
        token = self._token(response.text)
        response = self.url_open(f'/my/spa/classes/{session.id}/enroll', data={'csrf_token': token})
        self.assertEqual(response.status_code, 200)
        self.assertIn('quedaste inscrito', response.text)
        self.env.invalidate_all()
        enrollment = self.env['spa.class.enrollment'].search([('session_id', '=', session.id),
                                                              ('partner_id', '=', self.user.partner_id.id)])
        self.assertEqual(enrollment.state, 'enrolled')
        self.assertEqual(enrollment.channel, 'portal')
        self.assertEqual(enrollment.membership_id, self.membership)
        self.assertEqual(sum(enrollment.consumption_ids.mapped('qty')), 1)
        # Otra persona: no puede cancelar una inscripción ajena.
        foreign = self.env['spa.class.enrollment'].create({'session_id': session.id, 'partner_id': self.other.id})
        foreign.action_enroll()
        response = self.url_open(f'/my/spa/classes/enrollment/{foreign.id}/cancel', data={'csrf_token': token})
        self.assertEqual(response.status_code, 404)
        self.env.invalidate_all()
        self.assertEqual(foreign.state, 'enrolled')
        # La propia sí, y vuelve la sesión al saldo.
        response = self.url_open(f'/my/spa/classes/enrollment/{enrollment.id}/cancel', data={'csrf_token': token})
        self.assertEqual(response.status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(enrollment.state, 'cancelled')
        self.assertEqual(sum(enrollment.consumption_ids.mapped('qty')), 0)
