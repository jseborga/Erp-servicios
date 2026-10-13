# Part of ERP Servicios Spa. License LGPL-3.
"""Cupos reservados por eventos (alquileres confirmados) y clases (sesiones programadas).

Se integran en el cálculo de aforo del núcleo extendiendo ``spa.space._seats_taken`` (con
super()), de modo que las franjas de los socios, la confirmación de reservas y el canje de
cortesías en espacios por franja los tienen en cuenta sin cambios en los otros módulos. En
los espacios libres, el ingreso se valida con ``_spa_check_walk_in``.
"""
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError

RENTAL_RESERVING_STATES = ('confirmed', 'in_progress')


class SpaSpace(models.Model):
    _inherit = 'spa.space'

    spa_rental_product_id = fields.Many2one(
        'product.product', string='Producto de alquiler por hora', domain=[('type', '=', 'service')],
        help='Se agrega solo al cotizar un alquiler de este espacio (cantidad = horas del evento).')
    spa_rental_ids = fields.One2many('spa.rental', 'space_id', string='Alquileres')
    spa_reserved_now = fields.Integer('Reservados ahora (eventos y clases)', compute='_compute_spa_reserved_now')
    spa_reserved_label = fields.Char('Reserva en curso', compute='_compute_spa_reserved_now')

    def _compute_spa_reserved_now(self):
        now = fields.Datetime.now()
        later = now + timedelta(minutes=1)
        for space in self:
            if not space.id:
                space.spa_reserved_now, space.spa_reserved_label = 0, False
                continue
            space.spa_reserved_now = space._spa_reserved_seats(now, later)
            space.spa_reserved_label = space._spa_reservation_label(now, later) or False

    # ------------------------------------------------------------------
    # Reservas de eventos y clases
    # ------------------------------------------------------------------
    def _spa_excluded(self, key):
        return [int(i) for i in (self.env.context.get(key) or []) if i] + [0]

    def _spa_rentals(self, start_utc, stop_utc):
        """Alquileres confirmados o en curso que se superponen con el intervalo."""
        self.ensure_one()
        return self.env['spa.rental'].sudo().search([
            ('space_id', '=', self.id), ('state', 'in', RENTAL_RESERVING_STATES),
            ('start', '<', stop_utc), ('stop', '>', start_utc),
            ('id', 'not in', self._spa_excluded('spa_exclude_rental_ids'))], order='start')

    def _spa_sessions(self, start_utc, stop_utc):
        """Sesiones de clase programadas que se superponen con el intervalo."""
        self.ensure_one()
        return self.env['spa.class.session'].sudo().search([
            ('space_id', '=', self.id), ('state', '=', 'planned'),
            ('start', '<', stop_utc), ('stop', '>', start_utc),
            ('id', 'not in', self._spa_excluded('spa_exclude_session_ids'))], order='start')

    def _spa_reserved_seats(self, start_utc, stop_utc):
        """Cupos reservados por eventos (exclusivo = todo el aforo) y clases en el intervalo."""
        self.ensure_one()
        if not self.id:
            return 0
        self.env['spa.rental'].flush_model(['space_id', 'state', 'start', 'stop', 'mode', 'seats'])
        self.env['spa.class.session'].flush_model(['space_id', 'state', 'start', 'stop', 'capacity'])
        cr = self.env.cr
        cr.execute("""
            SELECT COALESCE(SUM(CASE WHEN mode = 'exclusive' THEN %s ELSE seats END), 0)
              FROM spa_rental
             WHERE space_id = %s AND state IN %s AND start < %s AND stop > %s AND NOT (id = ANY(%s))
        """, [self.capacity, self.id, RENTAL_RESERVING_STATES, stop_utc, start_utc,
              self._spa_excluded('spa_exclude_rental_ids')])
        rentals = cr.fetchone()[0] or 0
        cr.execute("""
            SELECT COALESCE(SUM(capacity), 0)
              FROM spa_class_session
             WHERE space_id = %s AND state = 'planned' AND start < %s AND stop > %s AND NOT (id = ANY(%s))
        """, [self.id, stop_utc, start_utc, self._spa_excluded('spa_exclude_session_ids')])
        sessions = cr.fetchone()[0] or 0
        return int(rentals) + int(sessions)

    def _seats_taken(self, start_utc, stop_utc, *args, **kwargs):
        taken = super()._seats_taken(start_utc, stop_utc, *args, **kwargs)
        return taken + self._spa_reserved_seats(start_utc, stop_utc)

    def _spa_reservation_label(self, start_utc, stop_utc):
        """Texto de los eventos y clases que ocupan el intervalo, para mensajes al usuario."""
        self.ensure_one()
        tools = self.env['spa.tools']
        parts = []
        for rental in self._spa_rentals(start_utc, stop_utc):
            parts.append(self.env._('evento «%(event)s» (%(start)s–%(stop)s)', event=rental._spa_public_name(),
                                    start=tools.to_local(rental.start).strftime('%H:%M'),
                                    stop=tools.to_local(rental.stop).strftime('%H:%M')))
        for session in self._spa_sessions(start_utc, stop_utc):
            parts.append(self.env._('clase «%(name)s» (%(start)s–%(stop)s)', name=session.template_id.name or
                                    session.service_id.name, start=tools.to_local(session.start).strftime('%H:%M'),
                                    stop=tools.to_local(session.stop).strftime('%H:%M')))
        return ', '.join(parts)

    def _spa_exclusive_message(self, rental):
        tools = self.env['spa.tools']
        start, stop = tools.to_local(rental.start), tools.to_local(rental.stop)
        return self.env._('Reservado para evento: %(event)s (%(day)s de %(start)s a %(stop)s). %(space)s no está '
                          'disponible para socios en ese horario.', event=rental._spa_public_name(),
                          day=start.strftime('%d/%m'), start=start.strftime('%H:%M'), stop=stop.strftime('%H:%M'),
                          space=self.name)

    def _spa_people_inside(self, start_utc, stop_utc):
        """Personas dentro ahora (ingresos abiertos) que seguirán dentro al empezar el intervalo."""
        self.ensure_one()
        now = fields.Datetime.now()
        if start_utc > now + timedelta(hours=max(self.max_stay or 0.0, 4.0)) or stop_utc <= now:
            return 0
        people = 0
        for log in self.env['spa.access.log'].sudo().search([('space_id', '=', self.id), ('state', '=', 'open'),
                                                             ('people', '>', 0)]):
            expected_exit = log.booking_id.stop if log.booking_id else \
                log.check_in + timedelta(hours=self.max_stay or 2.0)
            if expected_exit > start_utc:
                people += log.people
        return people

    def _spa_check_walk_in(self, people=1, now=None):
        """Valida un ingreso sin reserva de clase contra eventos y clases (mensaje claro)."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        window_stop = now + timedelta(hours=self.max_stay or 1.0) if self.access_mode == 'free' \
            else now + timedelta(minutes=1)
        exclusive = self._spa_rentals(now, window_stop).filtered(lambda r: r.mode == 'exclusive')
        if exclusive:
            raise UserError(self._spa_exclusive_message(exclusive[0]))
        if self.access_mode != 'free':
            return True
        reserved = self._spa_reserved_seats(now, window_stop)
        if not reserved:
            return True
        self.invalidate_recordset(['occupancy', 'free_now', 'occupancy_percent'])
        inside = self.occupancy
        if inside + reserved + people > self.capacity:
            raise UserError(self.env._(
                '%(space)s: %(reserved)s cupo(s) están reservados para %(what)s y hay %(inside)s persona(s) dentro; '
                'quedan %(free)s de %(cap)s.', space=self.name, reserved=reserved,
                what=self._spa_reservation_label(now, window_stop), inside=inside,
                free=max(self.capacity - inside - reserved, 0), cap=self.capacity))
        return True

    def _free_mode_service(self):
        service = super()._free_mode_service()
        if service.spa_is_class:
            return self.service_ids.filtered(lambda s: s.active and not s.spa_is_class)[:1]
        return service

    def action_view_rentals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Alquileres de %s', self.name),
            'res_model': 'spa.rental',
            'view_mode': 'calendar,list,form',
            'domain': [('space_id', '=', self.id)],
            'context': {'default_space_id': self.id},
        }
