# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaBooking(models.Model):
    _inherit = 'spa.booking'

    invoice_id = fields.Many2one('account.move', string='Factura (pago suelto)', readonly=True, copy=False)
    payment_state = fields.Selection(related='invoice_id.payment_state', string='Estado de pago', related_sudo=True)
    invoice_state = fields.Selection(related='invoice_id.state', string='Estado de la factura', related_sudo=True)
    charge_status = fields.Selection([
        ('pending', 'Por cobrar (sin factura)'),
        ('invoiced', 'Facturado, por cobrar'),
        ('partial', 'Pagado en parte'),
        ('paid', 'Pagado'),
        ('cancelled', 'Anulado'),
    ], string='Cobro', compute='_compute_charge_status', compute_sudo=True,
        help='Pago suelto: el cobro nace pendiente y la factura se emite al cobrar o al prestar el servicio.')
    reminder_sent = fields.Boolean('Recordatorio generado', copy=False)

    @api.depends('invoice_id.state', 'invoice_id.payment_state')
    def _compute_charge_status(self):
        for booking in self:
            invoice = booking.invoice_id
            if not invoice:
                booking.charge_status = False
            elif invoice.state == 'cancel' or invoice.payment_state == 'reversed':
                booking.charge_status = 'cancelled'
            elif invoice.state == 'draft':
                booking.charge_status = 'pending'
            elif invoice.payment_state in ('paid', 'in_payment'):
                booking.charge_status = 'paid'
            elif invoice.payment_state == 'partial':
                booking.charge_status = 'partial'
            else:
                booking.charge_status = 'invoiced'

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
        """Cobro pendiente (borrador) del servicio suelto: se emite al cobrarlo o al prestar el servicio."""
        self.ensure_one()
        Membership = self.env['spa.membership']
        today = self.env['spa.tools'].local_today()
        lines = [(0, 0, Membership._spa_line_vals(self.service_id.product_id,
                                                   name=self.env._('%(service)s – %(when)s', service=self.service_id.name,
                                                                   when=self.display_name),
                                                   analytic=self.space_id.analytic_account_id))]
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': today,
            'invoice_date_due': today,
            'invoice_origin': self.name,
            'spa_invoice_kind': 'single',
            'invoice_line_ids': lines,
            'company_id': self.company_id.id,
        })
        self.invoice_id = invoice
        return invoice

    def _spa_issue_single_invoice(self):
        """Servicio prestado (ingreso o atendida) sin cobrar todavía: se emite la factura (hecho imponible)."""
        for booking in self.filtered(lambda b: b.payment_mode == 'single' and b.invoice_id):
            booking.invoice_id.sudo()._spa_post_pending()

    def _spa_refund_user(self):
        """Usuario de caja para la actividad de reembolso (o el usuario actual)."""
        self.ensure_one()
        cashier = self.env.ref('spa_base.group_spa_cashier', raise_if_not_found=False)
        manager = self.env.ref('spa_base.group_spa_manager', raise_if_not_found=False)
        users = cashier.sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share and self.company_id in u.company_ids) if cashier else self.env['res.users']
        preferred = users.filtered(lambda u: manager not in u.all_group_ids) if manager else users
        return (preferred or users)[:1] or self.env.user

    def _spa_void_single_invoice(self, refund=True):
        """Reserva suelta cancelada (o no-show): sin cobro pendiente ni deuda por un servicio no prestado.

        * Borrador → se anula (nunca fue documento fiscal).
        * Emitida y sin pagos → nota de crédito (reversión); si ya tiene documento fiscal que exige anulación
          (SIAT), queda una actividad para anularla.
        * Con pagos → se conserva y, si ``refund``, se avisa a caja para el reembolso.
        """
        for booking in self.filtered(lambda b: b.payment_mode == 'single' and b.invoice_id):
            invoice = booking.invoice_id.sudo()
            if invoice.state == 'draft':
                invoice._spa_cancel_pending(self.env._('Reserva %s cancelada: se anula el cobro pendiente.', booking.name))
                continue
            if invoice.state != 'posted' or invoice.payment_state == 'reversed':
                continue
            currency = invoice.currency_id
            unpaid = invoice.payment_state == 'not_paid' and not currency.compare_amounts(
                invoice.amount_residual, invoice.amount_total)
            if unpaid and not invoice.need_cancel_request:
                today = self.env['spa.tools'].local_today()
                invoice._reverse_moves([{
                    'ref': self.env._('Reserva %s cancelada', booking.name),
                    'date': today, 'invoice_date': today, 'invoice_date_due': today,
                }], cancel=True)
                booking.message_post(body=self.env._('Se revirtió la factura %s (servicio no prestado).', invoice.name))
            elif unpaid:
                booking.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=booking._spa_refund_user().id,
                    summary=self.env._('Anular la factura de una reserva cancelada'),
                    note=self.env._('La factura %s ya tiene documento fiscal: anúlela (SIAT) para no cobrar un servicio '
                                    'que no se prestó.', invoice.name))
            elif refund:
                paid = invoice.amount_total - invoice.amount_residual
                booking.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=booking._spa_refund_user().id,
                    summary=self.env._('Reembolsar reserva cancelada'),
                    note=self.env._('%(partner)s pagó %(amount)s por la reserva %(booking)s (factura %(invoice)s) y la '
                                    'canceló. Coordine el reembolso (nota de crédito y devolución) o un saldo a favor.',
                                    partner=booking.partner_id.name, amount=currency.format(paid),
                                    booking=booking.name, invoice=invoice.name))

    def action_cancel(self):
        res = super().action_cancel()
        self.filtered(lambda b: b.state in ('cancelled', 'late_cancel'))._spa_void_single_invoice()
        return res

    def action_no_show(self):
        res = super().action_no_show()
        # No se presentó: no hubo servicio ni cobro → se anula el cobro pendiente (lo pagado no se devuelve).
        self.filtered(lambda b: b.state == 'no_show')._spa_void_single_invoice(refund=False)
        return res

    def action_check_in(self):
        res = super().action_check_in()
        self._spa_issue_single_invoice()
        return res

    def action_done(self):
        res = super().action_done()
        self.filtered(lambda b: b.state == 'done')._spa_issue_single_invoice()
        return res

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
        if self.payment_mode == 'single' and not self.invoice_id and self.state in ('confirmed', 'checked_in', 'done'):
            self._create_single_invoice()
        invoice = self.invoice_id.sudo()
        if not invoice or invoice.state == 'cancel':
            raise UserError(self.env._('La reserva %s no tiene un cobro pendiente.', self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar pago'),
            'res_model': 'spa.payment.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_invoice_id': invoice.id,
                'default_amount': invoice._spa_amount_to_pay(),
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
