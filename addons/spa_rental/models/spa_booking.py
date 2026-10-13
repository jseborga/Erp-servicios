# Part of ERP Servicios Spa. License LGPL-3.
from odoo import models
from odoo.exceptions import UserError


class SpaBooking(models.Model):
    _inherit = 'spa.booking'

    def _confirm_one(self):
        """Antes de confirmar: clases grupales y eventos que reservan el espacio (mensaje claro)."""
        self.ensure_one()
        if self.state == 'draft' and self.service_id and self.start and self.stop:
            if self.service_id.spa_is_class:
                raise UserError(self.env._(
                    '%s es una clase grupal: inscriba al socio en una sesión desde Clases → Sesiones.',
                    self.service_id.name))
            space = self.space_id
            rentals = space._spa_rentals(self.start, self.stop)
            exclusive = rentals.filtered(lambda r: r.mode == 'exclusive')
            if exclusive:
                raise UserError(space._spa_exclusive_message(exclusive[0]))
            label = space._spa_reservation_label(self.start, self.stop)
            if label:
                space._lock_for_booking()
                taken = space._seats_taken(self.start, self.stop, exclude_booking=self)
                if taken + self.seats > space.capacity:
                    raise UserError(self.env._(
                        'No hay cupo en %(space)s: hay cupos reservados para %(what)s. Quedan %(free)s de %(cap)s.',
                        space=space.name, what=label, free=max(space.capacity - taken, 0), cap=space.capacity))
        return super()._confirm_one()
