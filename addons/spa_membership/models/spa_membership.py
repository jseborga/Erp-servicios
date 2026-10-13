# Part of ERP Servicios Spa. License LGPL-3.
import uuid
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

ACCESS_STATES = ('active', 'grace')
LIVE_STATES = ('active', 'grace', 'suspended')


class SpaMembership(models.Model):
    _name = 'spa.membership'
    _description = 'Membresía de un socio'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _check_company_auto = True

    name = fields.Char('Número', readonly=True, copy=False, default='/')
    partner_id = fields.Many2one('res.partner', string='Socio', required=True, tracking=True, index=True)
    phone = fields.Char(related='partner_id.phone')
    email = fields.Char(related='partner_id.email')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    plan_id = fields.Many2one('spa.plan', string='Plan', required=True, tracking=True, check_company=True)
    period_id = fields.Many2one('spa.plan.period', string='Duración', required=True, tracking=True,
                                domain="[('plan_id', '=', plan_id)]")
    price = fields.Monetary(related='period_id.price', string='Precio del período')
    date_start = fields.Date('Inicio', tracking=True, copy=False)
    date_end = fields.Date('Vence', tracking=True, copy=False)
    grace_until = fields.Date('Gracia hasta', compute='_compute_grace_until', store=True)
    state = fields.Selection([
        ('draft', 'Por activar'),
        ('active', 'Activa'),
        ('grace', 'En gracia'),
        ('suspended', 'Suspendida'),
        ('expired', 'Vencida'),
        ('cancelled', 'Cancelada'),
    ], default='draft', required=True, tracking=True, copy=False, index=True)
    qr_token = fields.Char('Credencial QR', readonly=True, copy=False, index=True,
                           default=lambda self: uuid.uuid4().hex)
    entitlement_ids = fields.One2many('spa.entitlement', 'membership_id', string='Saldos')
    consumption_ids = fields.One2many('spa.consumption', 'membership_id', string='Consumos')
    guest_ids = fields.One2many('spa.guest', 'membership_id', string='Invitados')
    guests_this_month = fields.Integer('Free pass usados este mes', compute='_compute_guests_this_month')
    note = fields.Text('Notas internas')

    _qr_token_uniq = models.Constraint('UNIQUE (qr_token)', 'La credencial QR debe ser única.')

    @api.depends('date_end', 'plan_id.grace_days')
    def _compute_grace_until(self):
        for membership in self:
            membership.grace_until = (membership.date_end + timedelta(days=membership.plan_id.grace_days)
                                      if membership.date_end else False)

    def _compute_guests_this_month(self):
        tools = self.env['spa.tools']
        start, end = tools.month_bounds(tools.local_today())
        for membership in self:
            membership.guests_this_month = len(membership.guest_ids.filtered(
                lambda g: g.charge_type == 'free_pass' and g.state != 'cancelled' and start <= g.date <= end))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('spa.membership') or '/'
        return super().create(vals_list)

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id and self.period_id.plan_id != self.plan_id:
            self.period_id = self.plan_id.period_ids[:1]

    def _compute_display_name(self):
        for membership in self:
            membership.display_name = f'{membership.name} · {membership.partner_id.name or ""} · {membership.plan_id.name or ""}'

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def _period_end(self, start):
        self.ensure_one()
        return start + relativedelta(months=self.period_id.months) - timedelta(days=1)

    def action_activate(self, start_date=None):
        """Activa una membresía nueva o extiende una vigente por un período más."""
        today = self.env['spa.tools'].local_today()
        for membership in self:
            if membership.state == 'cancelled':
                raise UserError(self.env._('La membresía %s está cancelada.', membership.name))
            if membership.state in ('draft', 'expired') or not membership.date_end:
                start = start_date or today
                membership.write({'date_start': start, 'date_end': membership._period_end(start), 'state': 'active'})
            else:
                new_start = max(membership.date_end + timedelta(days=1), today) if membership.state == 'suspended' \
                    else membership.date_end + timedelta(days=1)
                membership.write({'date_end': membership._period_end(new_start), 'state': 'active'})
            membership._apply_partner_pricelist()
            membership._ensure_entitlements(today)
            membership.message_post(body=self.env._('Membresía vigente hasta %s.', membership.date_end))
        return True

    def action_suspend(self):
        self.write({'state': 'suspended'})
        self._apply_partner_pricelist()

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        self._apply_partner_pricelist()

    def action_reset_draft(self):
        self.filtered(lambda m: m.state == 'cancelled' and not m.date_start).write({'state': 'draft'})

    def _apply_partner_pricelist(self):
        """Asigna la lista de precios del plan al socio mientras la membresía da acceso."""
        for membership in self:
            partner = membership.partner_id.with_company(membership.company_id)
            plan_pricelist = membership.plan_id.pricelist_id
            if membership.state in ACCESS_STATES and plan_pricelist:
                partner.sudo().specific_property_product_pricelist = plan_pricelist
            elif plan_pricelist and partner.specific_property_product_pricelist == plan_pricelist:
                other = partner.spa_membership_ids.filtered(
                    lambda m: m != membership and m.state in ACCESS_STATES and m.plan_id.pricelist_id)
                partner.sudo().specific_property_product_pricelist = other[:1].plan_id.pricelist_id

    @api.model
    def _cron_membership_daily(self):
        """Gracia, suspensión, vencimiento y saldos del mes."""
        today = self.env['spa.tools'].local_today()
        expire_after = int(self.env['ir.config_parameter'].sudo().get_param('spa.expire_after_days', 90))
        to_grace = self.search([('state', '=', 'active'), ('date_end', '<', today)])
        for membership in to_grace:
            membership.state = 'grace' if membership.grace_until and membership.grace_until >= today else 'suspended'
        to_suspend = self.search([('state', '=', 'grace'), ('grace_until', '<', today)])
        to_suspend.write({'state': 'suspended'})
        (to_grace | to_suspend).filtered(lambda m: m.state == 'suspended')._apply_partner_pricelist()
        to_expire = self.search([('state', '=', 'suspended'),
                                 ('date_end', '<', today - timedelta(days=expire_after))])
        to_expire.write({'state': 'expired'})
        to_expire._apply_partner_pricelist()
        self._resolve_pending_carryover()
        self.search([('state', 'in', ACCESS_STATES)])._ensure_entitlements(today)
        return True

    # ------------------------------------------------------------------
    # Saldos
    # ------------------------------------------------------------------
    def _ensure_entitlements(self, day):
        """Crea los saldos del mes de ``day`` (con el traslado del mes anterior)."""
        Entitlement = self.env['spa.entitlement'].sudo()
        tools = self.env['spa.tools']
        start, end = tools.month_bounds(day)
        current_start, _current_end = tools.month_bounds(tools.local_today())
        for membership in self:
            for line in membership.plan_id.line_ids:
                existing = membership.entitlement_ids.filtered(
                    lambda e: e.plan_line_id == line and e.period_start == start)
                if existing:
                    continue
                carried = 0
                carry_pending = False
                if not line.unlimited and line.carryover != 'lose' and start > current_start:
                    # Mes futuro: el traslado se calcula cuando empiece el mes.
                    carry_pending = True
                elif not line.unlimited and line.carryover != 'lose':
                    previous = membership.entitlement_ids.filtered(
                        lambda e: e.plan_line_id == line and e.period_end < start).sorted('period_start')[-1:]
                    if previous:
                        carried = max(previous.remaining, 0)
                        if line.carryover == 'carry_limited':
                            carried = min(carried, line.carryover_max)
                        elif line.carryover == 'accumulate' and line.carryover_max:
                            carried = min(carried, line.carryover_max)
                Entitlement.create({
                    'membership_id': membership.id,
                    'plan_line_id': line.id,
                    'period_start': start,
                    'period_end': end,
                    'unlimited': line.unlimited,
                    'granted': 0 if line.unlimited else line.quantity,
                    'carried_in': carried,
                    'carry_pending': carry_pending,
                })
        return True

    def _resolve_pending_carryover(self):
        """Calcula el traslado de saldos de meses que ya empezaron."""
        today = self.env['spa.tools'].local_today()
        pending = self.env['spa.entitlement'].sudo().search([('carry_pending', '=', True), ('period_start', '<=', today)])
        for entitlement in pending:
            line = entitlement.plan_line_id
            previous = entitlement.membership_id.entitlement_ids.filtered(
                lambda e: e.plan_line_id == line and e.period_end < entitlement.period_start).sorted('period_start')[-1:]
            carried = max(previous.remaining, 0) if previous else 0
            if line.carryover == 'carry_limited' or (line.carryover == 'accumulate' and line.carryover_max):
                carried = min(carried, line.carryover_max)
            entitlement.write({'carried_in': carried, 'carry_pending': False})

    def _entitlement_for(self, service, day):
        self.ensure_one()
        line = self.plan_id._line_for_service(service)
        if not line:
            return self.env['spa.entitlement']
        self._ensure_entitlements(day)
        start, _end = self.env['spa.tools'].month_bounds(day)
        return self.entitlement_ids.filtered(lambda e: e.plan_line_id == line and e.period_start == start)[:1]

    def _covers_date(self, day):
        self.ensure_one()
        if not self.date_start or day < self.date_start:
            return False
        return day <= (self.grace_until or self.date_end) if self.state == 'grace' else day <= self.date_end

    def _spa_check_access(self, service, start_utc, stop_utc=None, guests=0, raise_error=True, exclude_booking=None):
        """Valida si el socio puede usar ``service`` en esa fecha. Devuelve el saldo (spa.entitlement).

        Reglas: estado, vigencia, servicio incluido, horario permitido, saldo, tope de
        frecuencia e invitados por reserva.
        """
        self.ensure_one()
        tools = self.env['spa.tools']
        stop_utc = stop_utc or start_utc + timedelta(hours=service.duration)
        local_start = tools.to_local(start_utc)
        day = local_start.date()

        def fail(message):
            if raise_error:
                raise UserError(message)
            return False

        if self.state not in ACCESS_STATES:
            return fail(self.env._('La membresía %(name)s no da acceso (estado: %(state)s).', name=self.name,
                                   state=dict(self._fields['state'].selection)[self.state]))
        if not self._covers_date(day):
            return fail(self.env._('La membresía %(name)s no está vigente el %(day)s.', name=self.name, day=day))
        freeze = self._spa_frozen_on(day)
        if freeze:
            return fail(self.env._(
                'La membresía %(name)s está congelada del %(from)s al %(to)s (%(reason)s). '
                'Puede volver a usarla desde el %(next)s.',
                **{'name': self.name, 'from': freeze.date_from.strftime('%d/%m/%Y'),
                   'to': freeze.date_to.strftime('%d/%m/%Y'), 'reason': freeze.reason,
                   'next': (freeze.date_to + timedelta(days=1)).strftime('%d/%m/%Y')}))
        line = self.plan_id._line_for_service(service)
        if not line:
            return fail(self.env._('El plan %(plan)s no incluye %(service)s.', plan=self.plan_id.name,
                                   service=service.name))
        start_h = local_start.hour + local_start.minute / 60.0
        local_stop = tools.to_local(stop_utc)
        stop_h = (local_stop.hour + local_stop.minute / 60.0) or 24.0
        if start_h < line.hour_from - 1e-6 or stop_h > line.hour_to + 1e-6:
            return fail(self.env._('Su plan permite %(service)s solo en el horario %(range)s.',
                                   service=service.name, range=line._summary()))
        if guests and guests > line.guests_per_booking:
            return fail(self.env._('Su plan permite hasta %(n)s invitado(s) por reserva en %(service)s.',
                                   n=line.guests_per_booking, service=service.name))
        entitlement = self._entitlement_for(service, day)
        if not line.unlimited and entitlement.remaining < 1:
            return fail(self.env._('No le quedan sesiones de %(service)s en %(month)s.',
                                   service=service.name, month=day.strftime('%m/%Y')))
        if line.freq_limit_qty:
            if line.freq_limit_period == 'day':
                range_start, range_end = day, day
            else:
                range_start, range_end = tools.week_bounds(day)
            used = self._usage_between(service, range_start, range_end, exclude_booking=exclude_booking)
            if used >= line.freq_limit_qty:
                return fail(self.env._('Su plan permite %(qty)s %(service)s %(period)s y ya los usó.',
                                       qty=line.freq_limit_qty, service=service.name,
                                       period=dict(line._fields['freq_limit_period'].selection)[line.freq_limit_period]))
        return entitlement

    def _usage_between(self, service, day_from, day_to, exclude_booking=None):
        """Usos netos (consumos menos devoluciones) de un servicio entre dos fechas locales."""
        self.ensure_one()
        tools = self.env['spa.tools']
        dt_from = tools.local_combine(day_from, 0.0)
        dt_to = tools.local_combine(day_to + timedelta(days=1), 0.0)
        consumptions = self.consumption_ids.filtered(
            lambda c: c.service_id == service and dt_from <= c.service_date < dt_to)
        if exclude_booking:
            consumptions = consumptions.filtered(lambda c: c._booking_ref() != exclude_booking)
        return sum(consumptions.mapped('qty'))

    def _spa_consume(self, service, service_date, reason, qty=1, note=False, extra_vals=None):
        """Registra un consumo (o una devolución si qty < 0) en el libro."""
        self.ensure_one()
        day = self.env['spa.tools'].to_local(service_date).date()
        entitlement = self._entitlement_for(service, day)
        vals = {
            'membership_id': self.id,
            'entitlement_id': entitlement.id,
            'service_id': service.id,
            'service_date': service_date,
            'qty': qty,
            'reason': reason,
            'note': note,
        }
        vals.update(extra_vals or {})
        return self.env['spa.consumption'].sudo().create(vals)

    def _guest_charge_type(self, day):
        """'free_pass' si queda cupo de invitados en el mes de ``day``; si no, 'fee'."""
        self.ensure_one()
        start, end = self.env['spa.tools'].month_bounds(day)
        used = len(self.guest_ids.filtered(
            lambda g: g.charge_type == 'free_pass' and g.state != 'cancelled' and start <= g.date <= end))
        return 'free_pass' if used < self.plan_id.guest_quota else 'fee'

    def _balance_summary(self, day=None):
        """Resumen de saldos del mes para pantallas (portal, recepción)."""
        self.ensure_one()
        day = day or self.env['spa.tools'].local_today()
        result = []
        for line in self.plan_id.line_ids:
            entitlement = self._entitlement_for(line.service_id, day) if self.state in ACCESS_STATES else False
            result.append({
                'service': line.service_id,
                'line': line,
                'unlimited': line.unlimited,
                'available': (entitlement.granted + entitlement.carried_in) if entitlement else line.quantity,
                'used': entitlement.used if entitlement else 0,
                'remaining': entitlement.remaining if entitlement else 0,
                'rule': line._summary(),
            })
        return result

    def action_open_adjust_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Ajustar saldo'),
            'res_model': 'spa.consumption.adjust',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_membership_id': self.id},
        }
