# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaConsumption(models.Model):
    _inherit = 'spa.consumption'

    booking_id = fields.Many2one('spa.booking', string='Reserva', index=True, ondelete='set null')

    def _booking_ref(self):
        self.ensure_one()
        return self.booking_id


class SpaGuest(models.Model):
    _inherit = 'spa.guest'

    booking_id = fields.Many2one('spa.booking', string='Reserva', index=True, ondelete='cascade')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('booking_id'):
                booking = self.env['spa.booking'].browse(vals['booking_id'])
                if not booking.membership_id:
                    raise UserError(self.env._('Los invitados se registran sobre la membresía de un socio.'))
                vals.setdefault('membership_id', booking.membership_id.id)
                vals.setdefault('service_id', booking.service_id.id)
                vals['date'] = self.env['spa.tools'].to_local(booking.start).date()
        return super().create(vals_list)


class SpaMembership(models.Model):
    _inherit = 'spa.membership'

    booking_ids = fields.One2many('spa.booking', 'membership_id', string='Reservas')
    booking_count = fields.Integer(compute='_compute_booking_count')

    def _compute_booking_count(self):
        for membership in self:
            membership.booking_count = len(membership.booking_ids)

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reservas'),
            'res_model': 'spa.booking',
            'view_mode': 'list,calendar,form',
            'domain': [('membership_id', '=', self.id)],
            'context': {'default_partner_id': self.partner_id.id, 'default_membership_id': self.id},
        }

    def action_new_booking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Nueva reserva'),
            'res_model': 'spa.booking.slot.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.partner_id.id, 'default_membership_id': self.id},
        }
