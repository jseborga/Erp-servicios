# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .spa_service import BLOCKING_STATES


class SpaBooking(models.Model):
    _name = 'spa.booking'
    _description = 'Reserva del spa'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start desc, id desc'
    _check_company_auto = True

    name = fields.Char('Reserva', readonly=True, copy=False, default='/')
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True, index=True)
    phone = fields.Char(related='partner_id.phone', string='Celular')
    membership_id = fields.Many2one('spa.membership', string='Membresía', tracking=True, check_company=True,
                                    domain="[('partner_id', '=', partner_id), ('state', 'in', ('active', 'grace'))]")
    payment_mode = fields.Selection([
        ('membership', 'Con su membresía'),
        ('single', 'Pago suelto'),
    ], string='Forma de pago', required=True, default='membership', tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    service_id = fields.Many2one('spa.service', string='Servicio', required=True, tracking=True, check_company=True)
    space_id = fields.Many2one(related='service_id.space_id', store=True, string='Espacio', index=True)
    employee_id = fields.Many2one('hr.employee', string='Profesional', tracking=True, check_company=True)
    requires_staff = fields.Boolean(related='service_id.requires_staff')
    start = fields.Datetime('Inicio', required=True, tracking=True, index=True)
    stop = fields.Datetime('Fin', compute='_compute_stop', store=True, readonly=False, required=True, precompute=True)
    guest_ids = fields.One2many('spa.guest', 'booking_id', string='Invitados')
    seats = fields.Integer('Cupos', compute='_compute_seats', store=True)
    channel = fields.Selection([
        ('reception', 'Recepción'),
        ('phone', 'Teléfono'),
        ('whatsapp', 'WhatsApp'),
        ('portal', 'Web del socio'),
    ], string='Canal', default='reception', required=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmada'),
        ('checked_in', 'En curso'),
        ('done', 'Atendida'),
        ('cancelled', 'Cancelada'),
        ('late_cancel', 'Cancelación tardía'),
        ('no_show', 'No se presentó'),
    ], default='draft', required=True, tracking=True, index=True, copy=False, string='Estado')
    consumption_ids = fields.One2many('spa.consumption', 'booking_id', string='Consumos')
    note = fields.Text('Notas')
    color = fields.Integer(related='space_id.color')

    @api.depends('start', 'service_id.duration')
    def _compute_stop(self):
        for booking in self:
            if booking.start and booking.service_id:
                booking.stop = booking.start + timedelta(hours=booking.service_id.duration)
            elif not booking.stop:
                booking.stop = booking.start

    @api.depends('guest_ids.state')
    def _compute_seats(self):
        for booking in self:
            booking.seats = (booking.service_id.seats_per_booking or 1) + len(
                booking.guest_ids.filtered(lambda g: g.state != 'cancelled'))

    @api.onchange('partner_id', 'service_id')
    def _onchange_partner_membership(self):
        if self.partner_id:
            membership = self.partner_id.spa_membership_id
            if membership.state in ('active', 'grace') and (
                    not self.service_id or membership.plan_id._line_for_service(self.service_id)):
                self.membership_id = membership
                self.payment_mode = 'membership'
            else:
                self.membership_id = False
                self.payment_mode = 'single'

    @api.constrains('start', 'stop')
    def _check_dates(self):
        for booking in self:
            if booking.stop <= booking.start:
                raise ValidationError(self.env._('La reserva debe terminar después de empezar.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('spa.booking') or '/'
        return super().create(vals_list)

    def _compute_display_name(self):
        tools = self.env['spa.tools']
        for booking in self:
            local = tools.to_local(booking.start)
            booking.display_name = '%s · %s · %s' % (
                booking.partner_id.name or '', booking.service_id.name or '',
                local.strftime('%d/%m %H:%M') if local else '')

    # ------------------------------------------------------------------
    # Confirmación
    # ------------------------------------------------------------------
    def _guest_count(self):
        return len(self.guest_ids.filtered(lambda g: g.state != 'cancelled'))

    def action_confirm(self):
        for booking in self:
            booking._confirm_one()
        return True

    def _confirm_one(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._('Solo se confirman reservas en borrador.'))
        service = self.service_id
        space = self.space_id
        if service.access_mode == 'free':
            raise UserError(self.env._('%s es de acceso libre: no requiere reserva, solo check-in.', space.name))
        if space.state != 'active':
            raise UserError(self.env._('%s no está operativo.', space.name))
        if not space._within_hours(self.start, self.stop):
            raise UserError(self.env._('El horario está fuera de la atención de %s.', space.name))
        now = fields.Datetime.now()
        if self.start <= now:
            raise UserError(self.env._('No se puede reservar en el pasado.'))
        if self.channel == 'portal' and self.start < now + timedelta(hours=service.booking_lead_min):
            raise UserError(self.env._('Este servicio requiere %s horas de anticipación.', service.booking_lead_min))
        if self.guest_ids and not service.guest_allowed:
            raise UserError(self.env._('%s no admite invitados.', service.name))
        if self.payment_mode == 'membership' and not self.membership_id:
            raise UserError(self.env._('Seleccione la membresía o cambie a pago suelto.'))
        if self.membership_id and self.membership_id.partner_id != self.partner_id:
            raise UserError(self.env._('La membresía no pertenece a %s.', self.partner_id.name))

        # Serializa confirmaciones concurrentes sobre el mismo espacio.
        space._lock_for_booking()
        # El cupo que la lista de espera guarda para esta persona es suyo.
        taken = space.with_context(spa_waitlist_partner_id=self.partner_id.id)._seats_taken(
            self.start, self.stop, exclude_booking=self)
        if taken + self.seats > space.capacity:
            raise UserError(self.env._('No hay cupo en %(space)s: quedan %(free)s de %(cap)s.',
                                       space=space.name, free=max(space.capacity - taken, 0), cap=space.capacity))
        overlapping = self.search([
            ('partner_id', '=', self.partner_id.id), ('state', 'in', BLOCKING_STATES),
            ('start', '<', self.stop), ('stop', '>', self.start), ('id', '!=', self.id)])
        if overlapping:
            raise UserError(self.env._('%s ya tiene otra reserva en ese horario.', self.partner_id.name))
        if service.requires_staff:
            employee = service._free_employee(self.start, self.stop, exclude_booking=self, preferred=self.employee_id)
            if not employee:
                raise UserError(self.env._('No hay %s disponible en ese horario.', service.skill_id.name))
            self.employee_id = employee

        if self.payment_mode == 'membership':
            self.membership_id._spa_check_access(service, self.start, self.stop, guests=self._guest_count(),
                                                 exclude_booking=self)
            self.membership_id._spa_consume(service, self.start, 'booking', extra_vals={'booking_id': self.id})
            for guest in self.guest_ids.filtered(lambda g: not g.membership_id):
                guest.membership_id = self.membership_id
        self.state = 'confirmed'
        self.env['spa.booking.waitlist']._spa_mark_booked(self)
        self._after_confirm()

    def _after_confirm(self):
        """Gancho: cobro de pago suelto (spa_billing) y avisos (spa_messaging)."""
        return True

    # ------------------------------------------------------------------
    # Cancelación, asistencia y no-show
    # ------------------------------------------------------------------
    def _policy(self):
        self.ensure_one()
        return self.membership_id.plan_id.cancel_policy_id if self.payment_mode == 'membership' else \
            self.env['spa.cancel.policy']

    def _cancellations_this_month(self):
        self.ensure_one()
        tools = self.env['spa.tools']
        month_start, month_end = tools.month_bounds(tools.to_local(self.start).date())
        return self.search_count([
            ('membership_id', '=', self.membership_id.id),
            ('state', 'in', ('cancelled', 'late_cancel')),
            ('start', '>=', tools.local_combine(month_start, 0.0)),
            ('start', '<', tools.local_combine(month_end + timedelta(days=1), 0.0)),
        ])

    def _is_late_cancel(self):
        self.ensure_one()
        policy = self._policy()
        if not policy:
            return False
        if policy.max_cancellations_month and self._cancellations_this_month() >= policy.max_cancellations_month:
            return True
        return fields.Datetime.now() > self.start - timedelta(hours=policy.free_cancel_hours)

    def _refund_session(self, reason='refund', note=False):
        for booking in self.filtered(lambda b: b.payment_mode == 'membership' and b.membership_id):
            net = sum(booking.consumption_ids.mapped('qty'))
            if net > 0:
                booking.membership_id._spa_consume(booking.service_id, booking.start, reason, qty=-net, note=note,
                                                   extra_vals={'booking_id': booking.id})

    def action_cancel(self):
        for booking in self:
            if booking.state not in ('draft', 'confirmed'):
                raise UserError(self.env._('La reserva %s ya no se puede cancelar.', booking.name))
            booking.guest_ids.sudo().filtered(lambda g: g.state == 'planned').action_cancel()
            if booking.state == 'draft':
                booking.state = 'cancelled'
                continue
            if booking._is_late_cancel():
                policy = booking._policy()
                booking.state = 'late_cancel'
                if policy.late_cancel_action == 'none':
                    booking._refund_session(note=self.env._('Cancelación tardía sin penalidad'))
                elif policy.late_cancel_action == 'fee':
                    booking._refund_session(note=self.env._('Se cobra penalidad en lugar de la sesión'))
                    booking._charge_penalty(policy.late_cancel_fee_product_id, 'late_cancel')
                booking.message_post(body=self.env._('Cancelación tardía: %s.',
                                                     dict(policy._fields['late_cancel_action'].selection)[policy.late_cancel_action]))
            else:
                booking.state = 'cancelled'
                booking._refund_session()
        # Se liberaron cupos: avisar a la lista de espera (en orden de llegada).
        self.env['spa.booking.waitlist']._spa_on_seats_freed(self)
        return True

    def _charge_penalty(self, product, kind):
        """Gancho: spa_billing agrega la penalidad a la cuenta del socio."""
        return True

    def action_check_in(self):
        for booking in self:
            if booking.state != 'confirmed':
                raise UserError(self.env._('Solo se registra la llegada de reservas confirmadas.'))
            booking.state = 'checked_in'
            booking.guest_ids.sudo().filtered(lambda g: g.state == 'planned').action_attended()
        return True

    def action_done(self):
        self.filtered(lambda b: b.state in ('confirmed', 'checked_in')).write({'state': 'done'})
        return True

    def action_no_show(self):
        for booking in self.filtered(lambda b: b.state == 'confirmed'):
            booking.state = 'no_show'
            booking.guest_ids.sudo().filtered(lambda g: g.state == 'planned').action_cancel()
            policy = booking._policy()
            if not policy or policy.no_show_action == 'none':
                booking._refund_session(reason='refund', note=self.env._('No-show sin penalidad'))
            elif policy.no_show_action == 'fee':
                booking._refund_session(reason='refund', note=self.env._('Se cobra penalidad en lugar de la sesión'))
                booking._charge_penalty(policy.no_show_fee_product_id, 'no_show')
        return True

    @api.model
    def _cron_booking_states(self):
        """Cierra reservas atendidas y marca las ausencias (no-show)."""
        now = fields.Datetime.now()
        grace = int(self.env['ir.config_parameter'].sudo().get_param('spa.no_show_grace_minutes', 15))
        self.search([('state', '=', 'checked_in'), ('stop', '<', now)]).action_done()
        self.search([('state', '=', 'confirmed'), ('start', '<', now - timedelta(minutes=grace)),
                     ('stop', '<', now)]).action_no_show()
        return True
