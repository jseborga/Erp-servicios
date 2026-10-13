# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class SpaService(models.Model):
    _inherit = 'spa.service'

    spa_is_class = fields.Boolean(
        'Clase grupal', tracking=True,
        help='Se dicta en horarios fijos con instructor (Clases → Horarios). Los socios se inscriben a una '
             'sesión; no se reserva por franja.')

    def _free_employee(self, start_utc, stop_utc, exclude_booking=None, preferred=None, **kwargs):
        """Excluye al personal que dicta una clase en ese horario (no se cruza con masajes)."""
        busy = self.env['spa.class.session'].sudo().search([
            ('state', '=', 'planned'), ('instructor_id', '!=', False),
            ('start', '<', stop_utc), ('stop', '>', start_utc)]).instructor_id
        if busy:
            candidates = (preferred or self._qualified_employees()) - busy
            if not candidates:
                return self.env['hr.employee']
            preferred = candidates
        return super()._free_employee(start_utc, stop_utc, exclude_booking=exclude_booking, preferred=preferred,
                                      **kwargs)

    def _get_slots(self, day, seats=1, membership=None, guests=0, ignore_lead=False, **kwargs):
        slots = super()._get_slots(day, seats=seats, membership=membership, guests=guests, ignore_lead=ignore_lead,
                                   **kwargs)
        if self.spa_is_class:
            for slot in slots:
                slot.update(available=False, reason=self.env._('Clase grupal: inscríbase en un horario de clase'))
            return slots
        space = self.space_id
        now = fields.Datetime.now()
        for slot in slots:
            if slot['start'] <= now or slot['free'] >= seats:
                continue
            exclusive = space._spa_rentals(slot['start'], slot['stop']).filtered(lambda r: r.mode == 'exclusive')
            if exclusive:
                slot['reason'] = self.env._('Reservado para evento: %s', exclusive[0]._spa_public_name())
                slot['available'] = False
            elif slot['reason'] == self.env._('Lleno'):
                label = space._spa_reservation_label(slot['start'], slot['stop'])
                if label:
                    slot['reason'] = self.env._('Lleno (cupos reservados para %s)', label)
        return slots
