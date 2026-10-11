# Part of ERP Servicios Spa. License LGPL-3.
from datetime import datetime, timedelta

from odoo import api, fields, models

BLOCKING_STATES = ('confirmed', 'checked_in')


class SpaSpace(models.Model):
    _inherit = 'spa.space'

    def _seats_taken(self, start_utc, stop_utc, exclude_booking=None):
        """Cupos ocupados por reservas que se superponen con el intervalo."""
        self.ensure_one()
        query = """
            SELECT COALESCE(SUM(seats), 0) FROM spa_booking
             WHERE space_id = %s AND state IN %s AND start < %s AND stop > %s AND id != %s
        """
        self.env['spa.booking'].flush_model(['space_id', 'state', 'start', 'stop', 'seats'])
        self.env.cr.execute(query, [self.id, BLOCKING_STATES, stop_utc, start_utc, exclude_booking.id if exclude_booking else 0])
        return self.env.cr.fetchone()[0]

    def _lock_for_booking(self):
        """Bloquea la fila del espacio para serializar confirmaciones concurrentes."""
        self.env.cr.execute('SELECT id FROM spa_space WHERE id IN %s FOR UPDATE', [tuple(self.ids)])


class SpaService(models.Model):
    _inherit = 'spa.service'

    def _free_employee(self, start_utc, stop_utc, exclude_booking=None, preferred=None):
        """Primer profesional con turno y sin otra reserva en el intervalo."""
        self.ensure_one()
        candidates = self._qualified_employees()
        if preferred:
            candidates = preferred & candidates
        if not candidates:
            return self.env['hr.employee']
        busy = self.env['spa.booking'].search([
            ('employee_id', 'in', candidates.ids),
            ('state', 'in', BLOCKING_STATES),
            ('start', '<', stop_utc), ('stop', '>', start_utc),
            ('id', '!=', exclude_booking.id if exclude_booking else 0),
        ]).employee_id
        for employee in candidates - busy:
            if employee._spa_is_working(start_utc, stop_utc):
                return employee
        return self.env['hr.employee']

    def _get_slots(self, day, seats=1, membership=None, guests=0, ignore_lead=False):
        """Franjas del día (fecha local) con su disponibilidad.

        Devuelve una lista de dicts: start, stop (UTC), label, free, capacity,
        available y reason (por qué no se puede reservar).
        """
        self.ensure_one()
        tools = self.env['spa.tools']
        space = self.space_id
        now = fields.Datetime.now()
        slots = []
        for local_start in space._slot_starts(day, self.duration):
            start = tools.to_utc(local_start)
            stop = start + timedelta(hours=self.duration)
            taken = space._seats_taken(start, stop)
            free = max(space.capacity - taken, 0)
            reason = False
            if start <= now:
                reason = self.env._('Ya pasó')
            elif not ignore_lead and start < now + timedelta(hours=self.booking_lead_min):
                reason = self.env._('Requiere %s h de anticipación', self.booking_lead_min)
            elif not ignore_lead and start > now + timedelta(days=self.booking_lead_max):
                reason = self.env._('Aún no se abre la agenda')
            elif free < seats:
                reason = self.env._('Lleno')
            elif self.requires_staff and not self._free_employee(start, stop):
                reason = self.env._('Sin personal disponible')
            elif membership:
                ok = membership._spa_check_access(self, start, stop, guests=guests, raise_error=False)
                if ok is False:
                    reason = self.env._('No incluido en su plan a esta hora')
            slots.append({
                'start': start,
                'stop': stop,
                'label': '%s–%s' % (local_start.strftime('%H:%M'),
                                    (local_start + timedelta(hours=self.duration)).strftime('%H:%M')),
                'free': free,
                'capacity': space.capacity,
                'available': not reason,
                'reason': reason,
            })
        return slots
