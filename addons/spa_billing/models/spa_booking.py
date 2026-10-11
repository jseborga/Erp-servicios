# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models


class SpaBooking(models.Model):
    _inherit = 'spa.booking'

    invoice_id = fields.Many2one('account.move', string='Factura (pago suelto)', readonly=True, copy=False)
    payment_state = fields.Selection(related='invoice_id.payment_state', string='Estado de pago')
    reminder_sent = fields.Boolean('Recordatorio generado', copy=False)

    def _after_confirm(self):
        res = super()._after_confirm()
        for booking in self.filtered(lambda b: b.payment_mode == 'single' and not b.invoice_id):
            booking._create_single_invoice()
        self.guest_ids._spa_charge_fee()
        for booking in self:
            local = self.env['spa.tools'].to_local(booking.start)
            policy = booking._policy()
            self.env['spa.message'].queue('booking_confirmed', booking.partner_id, {
                'servicio': booking.service_id.name,
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': local.strftime('%H:%M'),
                'horas_cancelacion': int(policy.free_cancel_hours) if policy else 0,
            }, record=booking)
        return res

    def _create_single_invoice(self):
        self.ensure_one()
        Membership = self.env['spa.membership']
        lines = [(0, 0, Membership._spa_line_vals(self.service_id.product_id,
                                                   name=self.env._('%(service)s – %(when)s', service=self.service_id.name,
                                                                   when=self.display_name),
                                                   analytic=self.space_id.analytic_account_id))]
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'spa_invoice_kind': 'single',
            'invoice_line_ids': lines,
            'company_id': self.company_id.id,
        })
        invoice.action_post()
        self.invoice_id = invoice
        return invoice

    def _charge_penalty(self, product, kind):
        res = super()._charge_penalty(product, kind)
        for booking in self.filtered('membership_id'):
            label = self.env._('Penalidad (%(kind)s) %(booking)s', kind=dict(
                late_cancel=self.env._('cancelación tardía'), no_show=self.env._('no se presentó'))[kind],
                booking=booking.display_name)
            booking.membership_id._spa_add_charge(product, name=label, analytic=booking.space_id.analytic_account_id)
        return res

    def action_register_payment_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar pago'),
            'res_model': 'spa.payment.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_invoice_id': self.invoice_id.id,
                'default_amount': self.invoice_id.amount_residual,
                'default_method': 'cash',
            },
        }

    @api.model
    def _cron_booking_reminders(self):
        now = fields.Datetime.now()
        bookings = self.search([('state', '=', 'confirmed'), ('reminder_sent', '=', False),
                                ('start', '>=', now + timedelta(hours=20)), ('start', '<=', now + timedelta(hours=28))])
        for booking in bookings:
            local = self.env['spa.tools'].to_local(booking.start)
            self.env['spa.message'].queue('booking_reminder', booking.partner_id, {
                'servicio': booking.service_id.name,
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': local.strftime('%H:%M'),
            }, record=booking)
            booking.reminder_sent = True
        return True


class SpaGuest(models.Model):
    _inherit = 'spa.guest'

    charge_line_id = fields.Many2one('account.move.line', string='Cargo', readonly=True, copy=False)

    def _after_guest_registered(self):
        res = super()._after_guest_registered()
        # Invitados de una reserva: se cobran al confirmarla (ver spa.booking._after_confirm).
        self.filtered(lambda g: not g.booking_id)._spa_charge_fee()
        return res

    def _spa_charge_fee(self):
        for guest in self.filtered(lambda g: g.charge_type == 'fee' and not g.charge_line_id and g.state != 'cancelled'):
            product = guest.membership_id.plan_id.guest_fee_product_id
            if product:
                guest.charge_line_id = guest.membership_id._spa_add_charge(
                    product, name=self.env._('Invitado: %(guest)s (%(date)s)', guest=guest.name,
                                             date=guest.date.strftime('%d/%m/%Y')),
                    analytic=guest.service_id.space_id.analytic_account_id)

    def action_cancel(self):
        res = super().action_cancel()
        for guest in self.filtered('charge_line_id'):
            line = guest.charge_line_id.sudo()
            if line.move_id.state == 'draft':
                move = line.move_id
                move.write({'invoice_line_ids': [(2, line.id)]})
                if not move.invoice_line_ids:
                    move.unlink()
        return res
