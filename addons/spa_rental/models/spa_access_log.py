# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class SpaAccessLog(models.Model):
    _inherit = 'spa.access.log'

    class_session_id = fields.Many2one('spa.class.session', string='Clase', readonly=True,
                                       index='btree_not_null', ondelete='set null')
    class_enrollment_id = fields.Many2one('spa.class.enrollment', string='Inscripción', readonly=True,
                                          index='btree_not_null', ondelete='set null')

    @api.model
    def _spa_rental_person(self, token=None, partner=None):
        """Persona del ingreso (socio por su QR o contacto elegido); vacío para pases de cortesía."""
        if token:
            membership = self.env['spa.membership'].sudo().search([('qr_token', '=', token.strip())], limit=1)
            return membership.partner_id
        return partner or self.env['res.partner']

    @api.model
    def do_check_in(self, space, token=None, partner=None, guests=0, **kwargs):
        """Alumno de una clase: marca la asistencia en su cupo reservado. Resto: valida eventos y clases."""
        now = fields.Datetime.now()
        person = self._spa_rental_person(token, partner)
        if person and not guests:
            enrollment = self.env['spa.class.enrollment']._spa_find_for_check_in(person, space, now)
            if enrollment:
                return enrollment._spa_check_in(method='qr' if token else 'manual')
        space._lock_for_booking()
        space._spa_check_walk_in(people=1 + (guests or 0), now=now)
        return super().do_check_in(space, token=token, partner=partner, guests=guests, **kwargs)

    @api.model
    def _cron_auto_check_out(self):
        res = super()._cron_auto_check_out()
        now = fields.Datetime.now()
        self.search([('state', '=', 'open'), ('class_session_id', '!=', False),
                     ('class_session_id.stop', '<=', now)]).action_check_out()
        return res


class SpaCourtesyPass(models.Model):
    _inherit = 'spa.courtesy.pass'

    def _redeem(self, space, service=None, method='manual', **kwargs):
        space._lock_for_booking()
        space._spa_check_walk_in(people=1)
        return super()._redeem(space, service=service, method=method, **kwargs)
