# Part of ERP Servicios Spa. License LGPL-3.
from datetime import datetime, timedelta

from odoo import api, fields, models

BLOCKING_STATES = ('confirmed', 'checked_in')


class SpaSpace(models.Model):
    _inherit = 'spa.space'

    def _seats_taken(self, start_utc, stop_utc, exclude_booking=None):
        """Cupos ocupados que se superponen con el intervalo.

        Suma las reservas confirmadas o en curso y los cupos que la lista de espera guarda a
        quien fue avisado (durante sus minutos de prioridad). El contexto
        ``spa_waitlist_partner_id`` excluye el cupo guardado para esa persona (es suyo).
        Otros módulos agregan ocupación con ``super()`` (spa_access: personas dentro sin reserva).
        """
        self.ensure_one()
        query = """
            SELECT COALESCE(SUM(seats), 0) FROM spa_booking
             WHERE space_id = %s AND state IN %s AND start < %s AND stop > %s AND id != %s
        """
        self.env['spa.booking'].flush_model(['space_id', 'state', 'start', 'stop', 'seats'])
        self.env.cr.execute(query, [self.id, BLOCKING_STATES, stop_utc, start_utc, exclude_booking.id if exclude_booking else 0])
        taken = self.env.cr.fetchone()[0]
        return taken + self._seats_held_for_waitlist(start_utc, stop_utc)

    def _seats_held_for_waitlist(self, start_utc, stop_utc):
        """Cupos guardados a personas avisadas de la lista de espera (prioridad vigente)."""
        self.ensure_one()
        Waitlist = self.env['spa.booking.waitlist']
        Waitlist.flush_model(['space_id', 'state', 'start', 'stop', 'seats', 'priority_until', 'partner_id'])
        self.env.cr.execute("""
            SELECT COALESCE(SUM(seats), 0) FROM spa_booking_waitlist
             WHERE space_id = %s AND state = 'notified' AND priority_until > %s
               AND start < %s AND stop > %s AND partner_id != %s
        """, [self.id, fields.Datetime.now(), stop_utc, start_utc,
              self.env.context.get('spa_waitlist_partner_id') or 0])
        return self.env.cr.fetchone()[0]

    def _lock_for_booking(self):
        """Bloquea la fila del espacio para serializar confirmaciones concurrentes."""
        self.env.cr.execute('SELECT id FROM spa_space WHERE id IN %s FOR UPDATE', [tuple(self.ids)])


class SpaService(models.Model):
    _inherit = 'spa.service'

    def _spa_slot_bookable(self):
        """True si el servicio se reserva por franja individual (portal y reserva rápida).

        Otros módulos lo extienden (p. ej. spa_rental: las clases grupales se inscriben, no se reservan).
        """
        self.ensure_one()
        return self.space_id.access_mode == 'slot'

    def _free_employee(self, start_utc, stop_utc, exclude_booking=None, preferred=None):
        """Primer profesional con turno y sin otra reserva en el intervalo."""
        self.ensure_one()
        candidates = self._qualified_employees()
        if preferred:
            candidates = candidates & preferred
        if not candidates:
            return self.env['hr.employee']
        # sudo: el terapeuta solo ve sus sesiones y la web no ve reservas ajenas.
        busy = self.env['spa.booking'].sudo().search([
            ('employee_id', 'in', candidates.ids),
            ('state', 'in', BLOCKING_STATES),
            ('start', '<', stop_utc), ('stop', '>', start_utc),
            ('id', '!=', exclude_booking.id if exclude_booking else 0),
        ]).employee_id
        for employee in candidates.filtered(lambda e: e.id not in busy.ids):
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
        if membership and not self.env.context.get('spa_waitlist_partner_id'):
            # El cupo que la lista de espera guarda para este socio está libre para él.
            space = space.with_context(spa_waitlist_partner_id=membership.partner_id.id)
        now = fields.Datetime.now()
        slots = []
        for local_start in space._slot_starts(day, self.duration):
            start = tools.to_utc(local_start)
            stop = start + timedelta(hours=self.duration)
            taken = space._seats_taken(start, stop)
            free = max(space.capacity - taken, 0)
            reason = code = False
            if start <= now:
                reason, code = self.env._('Ya pasó'), 'past'
            elif not ignore_lead and start < now + timedelta(hours=self.booking_lead_min):
                reason, code = self.env._('Requiere %s h de anticipación', self.booking_lead_min), 'lead_min'
            elif not ignore_lead and start > now + timedelta(days=self.booking_lead_max):
                reason, code = self.env._('Aún no se abre la agenda'), 'lead_max'
            elif free < seats:
                reason, code = self.env._('Lleno'), 'full'
            elif self.requires_staff and not self._free_employee(start, stop):
                reason, code = self.env._('Sin personal disponible'), 'no_staff'
            elif membership and membership._spa_frozen_on(local_start.date()):
                reason, code = self.env._('Membresía congelada'), 'frozen'
            elif membership:
                ok = membership._spa_check_access(self, start, stop, guests=guests, raise_error=False)
                if ok is False:
                    reason, code = self.env._('No incluido en su plan a esta hora'), 'plan'
            slots.append({
                'start': start,
                'stop': stop,
                'label': '%s–%s' % (local_start.strftime('%H:%M'),
                                    (local_start + timedelta(hours=self.duration)).strftime('%H:%M')),
                'free': free,
                'capacity': space.capacity,
                'available': not reason,
                'reason': reason,
                'code': code,
                # Franja llena (o sin personal): se puede pedir la lista de espera (spa.booking.waitlist._spa_join).
                'waitlist': code in ('full', 'no_staff'),
            })
        return slots
