# Part of ERP Servicios Spa. License LGPL-3.
"""Clases en la web del socio (/my/spa/classes).

El socio conectado ve las próximas sesiones de las clases que incluye su plan, se inscribe
(descuenta una sesión de su saldo) y cancela. Seguridad igual que spa_portal: se busca con
sudo SOLO después de comprobar que el registro es de la cuenta del usuario conectado.
"""
from datetime import timedelta

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

DEFAULT_DAYS = 14
FLASH = {
    'enrolled': ('success', 'Listo: quedaste inscrito en la clase. Te esperamos.'),
    'cancelled': ('info', 'Cancelaste tu inscripción.'),
}


class SpaClassPortal(CustomerPortal):

    def _spa_class_commercial(self):
        return request.env.user.partner_id.commercial_partner_id

    def _spa_class_membership(self):
        """Membresía vigente del usuario conectado (o de su cuenta) en la compañía actual."""
        partner = request.env.user.partner_id
        memberships = request.env['spa.membership'].sudo().search([
            ('partner_id', 'child_of', self._spa_class_commercial().id),
            ('company_id', '=', request.env.company.id),
            ('state', 'in', ('active', 'grace'))])
        return memberships.sorted(lambda m: (m.partner_id != partner, -m.id))[:1]

    def _spa_class_services(self, membership):
        return membership.plan_id.line_ids.service_id.filtered(lambda s: s.spa_is_class and s.active)

    def _spa_class_sessions(self, membership):
        services = self._spa_class_services(membership)
        if not services:
            return request.env['spa.class.session'].sudo()
        now = fields.Datetime.now()
        return request.env['spa.class.session'].sudo().search([
            ('service_id', 'in', services.ids), ('state', '=', 'planned'),
            ('company_id', '=', request.env.company.id),
            ('start', '>', now), ('start', '<', now + timedelta(days=DEFAULT_DAYS)),
        ], order='start')

    def _spa_class_own_enrollments(self):
        return request.env['spa.class.enrollment'].sudo().search([
            ('partner_id', 'child_of', self._spa_class_commercial().id),
            ('company_id', '=', request.env.company.id),
            ('state', '=', 'enrolled'), ('stop', '>', fields.Datetime.now())], order='start')

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'spa_class_count' in counters:
            membership = self._spa_class_membership()
            values['spa_class_count'] = len(self._spa_class_sessions(membership)) if membership else 0
        return values

    def _spa_class_values(self, msg=None, error=None):
        tools = request.env['spa.tools']
        membership = self._spa_class_membership()
        values = self._prepare_portal_layout_values()
        enrollments = self._spa_class_own_enrollments()
        rows = []
        if membership:
            mine = {e.session_id.id: e for e in enrollments}
            for session in self._spa_class_sessions(membership):
                local = tools.to_local(session.start)
                reason = False
                if session.id in mine:
                    reason = request.env._('Inscrito')
                elif session.seats_left <= 0:
                    reason = request.env._('Clase llena')
                else:
                    ok = membership._spa_check_access(session.service_id, session.start, session.stop,
                                                      raise_error=False)
                    if ok is False:
                        reason = request.env._('No disponible en su plan')
                rows.append({
                    'session': session,
                    'day': local.strftime('%d/%m'),
                    'weekday': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][local.weekday()],
                    'hour': '%s–%s' % (local.strftime('%H:%M'), tools.to_local(session.stop).strftime('%H:%M')),
                    'reason': reason,
                    'enrolled': session.id in mine,
                })
        values.update({
            'page_name': 'spa_classes',
            'membership': membership,
            'rows': rows,
            'enrollments': [{
                'record': e,
                'when': '%s %s' % (tools.to_local(e.start).strftime('%d/%m'), tools.to_local(e.start).strftime('%H:%M')),
            } for e in enrollments],
            'flash': FLASH.get(msg),
            'error': error,
        })
        return values

    @http.route('/my/spa/classes', type='http', auth='user', website=True, sitemap=False)
    def spa_classes(self, msg=None, **kw):
        return request.render('spa_rental.portal_my_classes', self._spa_class_values(msg=msg))

    @http.route('/my/spa/classes/<int:session_id>/enroll', type='http', auth='user', website=True,
                methods=['POST'], sitemap=False)
    def spa_class_enroll(self, session_id, **kw):
        membership = self._spa_class_membership()
        if not membership:
            raise NotFound()
        session = request.env['spa.class.session'].sudo().browse(session_id).exists()
        if not session or session not in self._spa_class_sessions(membership):
            raise NotFound()
        try:
            with request.env.cr.savepoint():
                enrollment = request.env['spa.class.enrollment'].sudo().create({
                    'session_id': session.id,
                    'partner_id': membership.partner_id.id,
                    'membership_id': membership.id,
                    'payment_mode': 'membership',
                    'channel': 'portal',
                })
                enrollment.action_enroll()
        except (UserError, ValidationError) as error:
            return request.render('spa_rental.portal_my_classes', self._spa_class_values(error=str(error)))
        return request.redirect('/my/spa/classes?msg=enrolled')

    @http.route('/my/spa/classes/enrollment/<int:enrollment_id>/cancel', type='http', auth='user', website=True,
                methods=['POST'], sitemap=False)
    def spa_class_cancel(self, enrollment_id, **kw):
        enrollment = request.env['spa.class.enrollment'].sudo().browse(enrollment_id).exists()
        if not enrollment or enrollment.partner_id.commercial_partner_id != self._spa_class_commercial() \
                or enrollment.company_id != request.env.company:
            raise NotFound()
        try:
            with request.env.cr.savepoint():
                enrollment.action_cancel()
        except UserError as error:
            return request.render('spa_rental.portal_my_classes', self._spa_class_values(error=str(error)))
        return request.redirect('/my/spa/classes?msg=cancelled')
