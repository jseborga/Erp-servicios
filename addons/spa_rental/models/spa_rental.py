# Part of ERP Servicios Spa. License LGPL-3.
"""Alquiler de ambientes para eventos.

Diseño: **un espacio por alquiler**. La disponibilidad, el aforo, el precio por hora y la
reserva de cupos son propios de cada espacio; un evento que usa varios espacios (piscina y
jacuzzi, por ejemplo) se registra como varios alquileres del mismo cliente y la misma
oportunidad del CRM (botón «Agregar otro espacio»). Así cada espacio se valida y se libera por
separado y ``spa.space._seats_taken`` sigue siendo una consulta simple por espacio.
"""
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

RESERVING_STATES = ('confirmed', 'in_progress')
LOCKED_FIELDS = ('partner_id', 'space_id', 'start', 'stop', 'mode', 'seats')


class SpaRental(models.Model):
    _name = 'spa.rental'
    _description = 'Alquiler de ambiente / evento'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start desc, id desc'
    _check_company_auto = True

    name = fields.Char('Número', readonly=True, copy=False, default='/')
    event_name = fields.Char('Evento', required=True, tracking=True,
                             help='Nombre del evento o actividad, p. ej. «Cumpleaños de Sofía» o «Club de natación».')
    private_event = fields.Boolean('Evento privado',
                                   help='No mostrar el nombre del evento a los socios: las franjas y avisos dirán '
                                        '«Reservado para evento: evento privado».')
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True, index=True)
    phone = fields.Char('Celular de contacto', compute='_compute_phone', store=True, readonly=False, precompute=True)
    email = fields.Char(related='partner_id.email')
    user_id = fields.Many2one('res.users', string='Responsable', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    space_id = fields.Many2one('spa.space', string='Espacio', required=True, tracking=True, check_company=True,
                               index=True)
    space_capacity = fields.Integer(related='space_id.capacity', string='Aforo del espacio')
    start = fields.Datetime('Inicio', required=True, tracking=True, index=True)
    stop = fields.Datetime('Fin', required=True, tracking=True, index=True)
    duration_hours = fields.Float('Horas', compute='_compute_duration_hours')
    mode = fields.Selection([
        ('exclusive', 'Exclusivo (todo el espacio)'),
        ('partial', 'Parcial (algunos cupos)'),
    ], string='Modo', required=True, default='exclusive', tracking=True,
        help='Exclusivo: nadie más usa el espacio durante el evento. Parcial: el evento reserva N cupos y '
             'los socios usan el resto.')
    seats = fields.Integer('Cupos reservados', tracking=True, help='Solo modo parcial: cupos del aforo para el evento.')
    reserved_seats = fields.Integer('Cupos que ocupa', compute='_compute_reserved_seats')
    attendees = fields.Integer('Asistentes', tracking=True)
    outside_hours_ok = fields.Boolean(
        'Autorizado fuera del horario', tracking=True,
        help='El gerente autoriza el evento fuera del horario de atención del espacio. Los cierres '
             'programados y el estado del espacio se validan igual.')
    line_ids = fields.One2many('spa.rental.line', 'rental_id', string='Precio', copy=True)
    amount_total = fields.Monetary('Total', compute='_compute_amount_total', store=True,
                                   help='Precio final (IVA incluido).')
    deposit_amount = fields.Monetary('Garantía', tracking=True,
                                     help='Monto de garantía que se cobra aparte de la factura y se devuelve '
                                          'o aplica a daños después del evento.')
    deposit_payment_ids = fields.One2many('account.payment', 'spa_rental_id', string='Cobros y devoluciones de garantía')
    move_ids = fields.One2many('account.move', 'spa_rental_id', string='Documentos contables')
    deposit_received = fields.Monetary('Garantía cobrada', compute='_compute_deposit', compute_sudo=True)
    deposit_refunded = fields.Monetary('Garantía devuelta', compute='_compute_deposit', compute_sudo=True)
    deposit_applied = fields.Monetary('Garantía aplicada a daños', compute='_compute_deposit', compute_sudo=True)
    deposit_balance = fields.Monetary('Garantía en custodia', compute='_compute_deposit', compute_sudo=True)
    deposit_state = fields.Selection([
        ('none', 'Sin garantía'),
        ('pending', 'Por cobrar'),
        ('held', 'En custodia'),
        ('settled', 'Liquidada'),
    ], string='Estado de la garantía', compute='_compute_deposit', compute_sudo=True)
    invoice_id = fields.Many2one('account.move', string='Factura', readonly=True, copy=False)
    invoice_status = fields.Selection([
        ('none', 'Sin factura'),
        ('draft', 'Borrador (se valida al cobrar o al terminar)'),
        ('posted', 'Validada, por cobrar'),
        ('partial', 'Pago parcial'),
        ('paid', 'Pagada'),
        ('cancel', 'Anulada'),
    ], string='Estado de la factura', compute='_compute_invoice_status', compute_sudo=True)
    amount_paid = fields.Monetary('Cobrado', compute='_compute_invoice_status', compute_sudo=True)
    amount_due = fields.Monetary('Saldo por cobrar', compute='_compute_invoice_status', compute_sudo=True)
    state = fields.Selection([
        ('quotation', 'Cotización'),
        ('confirmed', 'Confirmado'),
        ('in_progress', 'En curso'),
        ('done', 'Realizado'),
        ('cancelled', 'Cancelado'),
    ], default='quotation', required=True, tracking=True, index=True, copy=False)
    lead_id = fields.Many2one('crm.lead', string='Oportunidad', copy=False, index='btree_not_null')
    reminder_sent = fields.Boolean('Recordatorio generado', copy=False)
    availability_warning = fields.Text('Disponibilidad', compute='_compute_availability_warning')
    can_edit_prices = fields.Boolean('Puede cambiar precios', compute='_compute_can_edit_prices')
    cancel_reason = fields.Char('Motivo de cancelación', copy=False, tracking=True)
    note = fields.Text('Notas (montaje, catering, requerimientos)')
    color = fields.Integer(related='space_id.color')

    _check_mode_seats = models.Constraint('CHECK (seats >= 0 AND attendees >= 0)',
                                          'Los cupos y los asistentes no pueden ser negativos.')

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    @api.depends('partner_id')
    def _compute_phone(self):
        for rental in self:
            rental.phone = rental.partner_id.phone or rental.phone

    @api.depends('start', 'stop')
    def _compute_duration_hours(self):
        for rental in self:
            rental.duration_hours = (rental.stop - rental.start).total_seconds() / 3600.0 \
                if rental.start and rental.stop and rental.stop > rental.start else 0.0

    @api.depends('mode', 'seats', 'space_id.capacity')
    def _compute_reserved_seats(self):
        for rental in self:
            rental.reserved_seats = rental.space_id.capacity if rental.mode == 'exclusive' else rental.seats

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for rental in self:
            rental.amount_total = sum(rental.line_ids.mapped('subtotal'))

    @api.depends('deposit_amount', 'deposit_payment_ids.state', 'deposit_payment_ids.amount', 'move_ids.state')
    def _compute_deposit(self):
        for rental in self:
            payments = rental.deposit_payment_ids.filtered(lambda p: p.state in ('in_process', 'paid'))
            received = sum(payments.filtered(lambda p: p.spa_deposit_kind == 'receive').mapped('amount'))
            refunded = sum(payments.filtered(lambda p: p.spa_deposit_kind == 'refund').mapped('amount'))
            account = rental.company_id._spa_rental_deposit_account() if rental.company_id else False
            applied = sum(rental.move_ids.filtered(
                lambda m: m.spa_rental_move_kind == 'deposit_apply' and m.state == 'posted'
            ).line_ids.filtered(lambda l: l.account_id == account).mapped('debit'))
            balance = received - refunded - applied
            rental.deposit_received = received
            rental.deposit_refunded = refunded
            rental.deposit_applied = applied
            rental.deposit_balance = balance
            currency = rental.currency_id
            if not received and not rental.deposit_amount:
                rental.deposit_state = 'none'
            elif currency and currency.compare_amounts(balance, 0) > 0:
                rental.deposit_state = 'held'
            elif not received:
                rental.deposit_state = 'pending'
            else:
                rental.deposit_state = 'settled'

    @api.depends('invoice_id.state', 'invoice_id.amount_residual', 'invoice_id.amount_total', 'invoice_id.payment_state')
    def _compute_invoice_status(self):
        for rental in self:
            invoice = rental.invoice_id
            paid, due, status = 0.0, 0.0, 'none'
            if invoice.state == 'draft':
                status, due = 'draft', invoice.amount_total
            elif invoice.state == 'cancel':
                status = 'cancel'
            elif invoice.state == 'posted':
                due = invoice.amount_residual
                paid = invoice.amount_total - invoice.amount_residual
                if invoice.payment_state in ('paid', 'in_payment', 'reversed'):
                    status = 'paid'
                elif invoice.payment_state == 'partial':
                    status = 'partial'
                else:
                    status = 'posted'
            rental.invoice_status, rental.amount_paid, rental.amount_due = status, paid, due

    @api.depends('space_id', 'start', 'stop', 'mode', 'seats', 'state', 'outside_hours_ok')
    def _compute_availability_warning(self):
        for rental in self:
            errors = rental._spa_availability_errors() if rental.state == 'quotation' and rental._origin.id else []
            rental.availability_warning = '\n'.join('• ' + error for error in errors) if errors else False

    def _spa_public_name(self):
        """Nombre del evento que ven los socios (franjas, reservas e ingresos rechazados)."""
        self.ensure_one()
        return self.env._('evento privado') if self.private_event else self.event_name

    def _compute_can_edit_prices(self):
        allowed = self._spa_is_manager()
        for rental in self:
            rental.can_edit_prices = allowed

    def _compute_display_name(self):
        for rental in self:
            rental.display_name = '%s · %s' % (rental.name or '', rental.event_name or '')

    @api.constrains('start', 'stop')
    def _check_dates(self):
        for rental in self:
            if rental.stop <= rental.start:
                raise ValidationError(self.env._('El evento debe terminar después de empezar.'))

    @api.onchange('space_id', 'start', 'stop')
    def _onchange_space_hours(self):
        """Ajusta la cantidad de horas del producto de alquiler del espacio."""
        product = self.space_id.spa_rental_product_id
        # Al cambiar de espacio se quita el alquiler por hora del espacio anterior.
        other_products = self.env['spa.space'].search(
            [('spa_rental_product_id', '!=', False)]).spa_rental_product_id - product
        stale = self.line_ids.filtered(lambda l: l.product_id in other_products)
        if stale:
            self.line_ids -= stale
        if not (product and self.duration_hours):
            return
        line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if line:
            line.quantity = self.duration_hours
        else:
            self.line_ids = [Command.create({'product_id': product.id, 'quantity': self.duration_hours})]

    @api.onchange('attendees', 'mode')
    def _onchange_attendees(self):
        if self.mode == 'partial' and self.attendees and not self.seats:
            self.seats = min(self.attendees, self.space_id.capacity or self.attendees)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('spa.rental') or '/'
            if vals.get('outside_hours_ok') and not self._spa_is_manager():
                raise UserError(self.env._('Solo el gerente autoriza eventos fuera del horario de atención.'))
        rentals = super().create(vals_list)
        for rental in rentals:
            if not rental.line_ids:
                rental._spa_add_space_line()
            if rental.phone and not rental.partner_id.phone:
                rental.partner_id.sudo().phone = rental.phone
        rentals._spa_sync_lead()
        return rentals

    def write(self, vals):
        if not self.env.context.get('spa_rental_internal') and set(LOCKED_FIELDS) & set(vals):
            for rental in self.filtered(lambda r: r.state != 'quotation'):
                changed = []
                for fname in LOCKED_FIELDS:
                    if fname not in vals:
                        continue
                    field = rental._fields[fname]
                    new = field.convert_to_record(field.convert_to_cache(vals[fname], rental), rental)
                    if new != rental[fname]:
                        changed.append(fname)
                if changed:
                    raise UserError(self.env._(
                        'El alquiler %s ya está confirmado: para cambiar cliente, espacio, horario o cupos, el '
                        'gerente debe volverlo a cotización.', rental.name))
        if 'outside_hours_ok' in vals and not self._spa_is_manager():
            raise UserError(self.env._('Solo el gerente autoriza eventos fuera del horario de atención.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.state not in ('quotation', 'cancelled')):
            raise UserError(self.env._('Solo se eliminan alquileres en cotización o cancelados.'))
        return super().unlink()

    def _spa_is_manager(self):
        return self.env.su or self.env.user.has_group('spa_base.group_spa_manager')

    def _spa_check_manager(self, action):
        if not self._spa_is_manager():
            raise UserError(self.env._('Solo el gerente puede %s.', action))

    def _spa_add_space_line(self):
        self.ensure_one()
        product = self.space_id.spa_rental_product_id
        if product and self.duration_hours:
            self.env['spa.rental.line'].sudo().create({
                'rental_id': self.id, 'product_id': product.id, 'quantity': self.duration_hours})

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------
    def _spa_availability_errors(self):
        """Motivos por los que el alquiler no se puede confirmar (lista vacía = disponible)."""
        self.ensure_one()
        _ = self.env._
        space = self.space_id
        if not (space and self.start and self.stop) or self.stop <= self.start:
            return []
        tools = self.env['spa.tools']
        errors = []
        start, stop = self.start, self.stop
        local_start = tools.to_local(start)
        local_stop = tools.to_local(stop)
        if space.state != 'active':
            errors.append(_('%s no está operativo.', space.name))
        closures = space.closure_ids.filtered(
            lambda c: c.date_from <= local_stop.date() and c.date_to >= local_start.date())
        if closures:
            errors.append(_('%(space)s tiene un cierre programado: %(reason)s.', space=space.name,
                            reason=closures[0].reason))
        elif not self.outside_hours_ok and not space._within_hours(start, stop):
            errors.append(_('El horario está fuera de la atención de %(space)s (%(open)s a %(close)s, días '
                            'habilitados). El gerente puede autorizarlo con «Autorizado fuera del horario».',
                            space=space.name, open=self._spa_hour_label(space.open_hour),
                            close=self._spa_hour_label(space.close_hour)))
        others = self.sudo().search([
            ('space_id', '=', space.id), ('state', 'in', RESERVING_STATES), ('id', '!=', self._origin.id or 0),
            ('start', '<', stop), ('stop', '>', start)])
        for other in others:
            errors.append(_('Ya hay otro evento confirmado en %(space)s en ese horario: %(name)s (%(event)s).',
                            space=space.name, name=other.name, event=other.event_name))
        sessions = self.env['spa.class.session'].sudo().search([
            ('space_id', '=', space.id), ('state', '=', 'planned'), ('start', '<', stop), ('stop', '>', start)])
        inside = space._spa_people_inside(start, stop)
        if self.mode == 'exclusive':
            for session in sessions:
                errors.append(_('La clase %(name)s usa %(space)s en ese horario: cancélela o muévala antes de '
                                'confirmar el evento exclusivo.', name=session.display_name, space=space.name))
            bookings = self.env['spa.booking'].sudo().search([
                ('space_id', '=', space.id), ('state', 'in', ('confirmed', 'checked_in')),
                ('start', '<', stop), ('stop', '>', start)])
            if bookings:
                errors.append(_('Hay %(n)s reserva(s) de socios en ese horario (%(names)s): reprográmelas o '
                                'cancélelas antes de confirmar el evento exclusivo.', n=len(bookings),
                                names=', '.join(bookings[:5].mapped('display_name'))))
            if inside:
                errors.append(_('Hay %(n)s persona(s) dentro de %(space)s y el evento empieza antes de que '
                                'termine su permanencia.', n=inside, space=space.name))
            if not (others or sessions or bookings or inside):
                taken = space.with_context(spa_exclude_rental_ids=[self._origin.id or 0])._seats_taken(start, stop)
                if taken:
                    errors.append(_('%(space)s tiene %(n)s cupo(s) ocupados en ese horario.', space=space.name,
                                    n=taken))
        else:
            if self.seats <= 0:
                errors.append(_('Indique cuántos cupos reserva el evento (modo parcial).'))
            elif self.seats > space.capacity:
                errors.append(_('El evento reserva %(seats)s cupos y el aforo de %(space)s es %(cap)s: use el '
                                'modo exclusivo o reduzca los cupos.', seats=self.seats, space=space.name,
                                cap=space.capacity))
            elif not others:
                taken = space.with_context(spa_exclude_rental_ids=[self._origin.id or 0])._seats_taken(start, stop)
                if space.access_mode == 'free':
                    taken += inside
                if taken + self.seats > space.capacity:
                    errors.append(_('No hay cupos suficientes en %(space)s: quedan %(free)s de %(cap)s (reservas de '
                                    'socios, clases y personas dentro) y el evento necesita %(seats)s.',
                                    space=space.name, free=max(space.capacity - taken, 0), cap=space.capacity,
                                    seats=self.seats))
        return errors

    @api.model
    def _spa_hour_label(self, value):
        hours = int(value)
        return '%02d:%02d' % (hours, int(round((value - hours) * 60)))

    # ------------------------------------------------------------------
    # Flujo
    # ------------------------------------------------------------------
    def action_confirm(self):
        self._spa_check_manager(self.env._('confirmar alquileres'))
        for rental in self:
            if rental.state != 'quotation':
                raise UserError(self.env._('Solo se confirman alquileres en cotización (%s).', rental.name))
            if not rental.line_ids:
                raise UserError(self.env._('Agregue al menos una línea de precio a %s (alquiler del espacio, '
                                           'extras).', rental.name))
            if rental.stop <= fields.Datetime.now():
                raise UserError(self.env._('El evento %s ya terminó: corrija la fecha.', rental.name))
            # Serializa con reservas, ingresos y clases concurrentes sobre el mismo espacio.
            rental.space_id._lock_for_booking()
            errors = rental._spa_availability_errors()
            if errors:
                raise UserError(self.env._('No se puede confirmar %(name)s:\n%(errors)s', name=rental.name,
                                           errors='\n'.join('• ' + error for error in errors)))
            rental.with_context(spa_rental_internal=True).state = 'confirmed'
            rental._spa_create_invoice()
            rental._spa_lead_won()
            rental._spa_notify('rental_confirmed')
            rental.message_post(body=self.env._('Evento confirmado: %(n)s cupo(s) de %(space)s reservados.',
                                                n=rental.reserved_seats, space=rental.space_id.name))
        return True

    def action_start(self):
        for rental in self:
            if rental.state != 'confirmed':
                raise UserError(self.env._('Solo se inicia un evento confirmado.'))
            rental.state = 'in_progress'
        return True

    def action_done(self):
        """Fin del evento: el servicio está prestado; se valida la factura (hecho imponible)."""
        for rental in self:
            if rental.state not in RESERVING_STATES:
                raise UserError(self.env._('Solo se finaliza un evento confirmado o en curso.'))
            rental.state = 'done'
            if rental.invoice_id.state == 'draft':
                rental.invoice_id._spa_post_on_taxable_event()
                rental.message_post(body=self.env._('Evento realizado: factura %s validada.', rental.invoice_id.name))
            if rental.deposit_balance > 0:
                rental.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=rental.user_id.id or self.env.uid,
                    summary=self.env._('Liquidar la garantía'),
                    note=self.env._('Revise el espacio y devuelva la garantía o aplíquela a daños.'))
        return True

    def action_cancel(self):
        for rental in self:
            if rental.state not in ('quotation', 'confirmed'):
                raise UserError(self.env._('El alquiler %s ya no se puede cancelar.', rental.name))
            if rental.state == 'confirmed':
                rental._spa_check_manager(self.env._('cancelar eventos confirmados'))
            if rental.deposit_balance > 0:
                raise UserError(self.env._('Devuelva o aplique la garantía (%(amount)s) de %(name)s antes de cancelar.',
                                           amount=rental.currency_id.format(rental.deposit_balance), name=rental.name))
            invoice = rental.invoice_id.sudo()
            if invoice.state == 'posted':
                if invoice.currency_id.compare_amounts(invoice.amount_residual, invoice.amount_total) < 0:
                    raise UserError(self.env._(
                        'La factura %(inv)s de %(name)s ya tiene cobros: emita la nota de crédito y la devolución '
                        '(o acuerde la penalidad) desde Contabilidad antes de cancelar.', inv=invoice.name,
                        name=rental.name))
                invoice._reverse_moves(cancel=True)
            elif invoice.state == 'draft':
                invoice.button_cancel()
            rental.with_context(spa_rental_internal=True).state = 'cancelled'
            rental._spa_lead_lost()
        return True

    def action_reset_quotation(self):
        """El gerente vuelve un evento confirmado a cotización para cambiar fecha, espacio o precios."""
        self._spa_check_manager(self.env._('volver un evento a cotización'))
        for rental in self:
            if rental.state not in ('confirmed', 'cancelled'):
                raise UserError(self.env._('Solo un evento confirmado o cancelado vuelve a cotización.'))
            invoice = rental.invoice_id.sudo()
            if invoice.state == 'posted':
                raise UserError(self.env._('La factura %s ya está validada: no se puede volver a cotización.',
                                           invoice.name))
            if invoice.state == 'draft':
                invoice.button_cancel()
            rental.with_context(spa_rental_internal=True).write({
                'state': 'quotation', 'invoice_id': False, 'reminder_sent': False})
        return True

    def action_add_space(self):
        """Otro espacio para el mismo evento: copia cliente, horario y oportunidad."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Otro espacio para %s', self.event_name),
            'res_model': 'spa.rental',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_partner_id': self.partner_id.id, 'default_phone': self.phone,
                'default_event_name': self.event_name, 'default_start': self.start, 'default_stop': self.stop,
                'default_attendees': self.attendees, 'default_lead_id': self.lead_id.id,
                'default_user_id': self.user_id.id,
            },
        }

    # ------------------------------------------------------------------
    # Facturación y garantía
    # ------------------------------------------------------------------
    def _spa_create_invoice(self):
        """Factura en BORRADOR: se valida al cobrar o al terminar el evento (Ley 843 art. 4 inc. b)."""
        self.ensure_one()
        if self.invoice_id and self.invoice_id.sudo().state != 'cancel':
            return self.invoice_id
        company = self.company_id
        analytic = company._spa_rental_analytic()
        Move = self.env['account.move'].sudo().with_company(company)
        lines = [Command.create(Move._spa_rental_line_vals(
            line.product_id, quantity=line.quantity, price=line.price_unit, name=line.name, discount=line.discount,
            analytic=analytic, company=company)) for line in self.line_ids]
        invoice = Move.create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': company.id,
            'invoice_origin': self.name,
            'ref': self.event_name,
            'spa_invoice_kind': 'rental',
            'spa_rental_id': self.id,
            'spa_rental_move_kind': 'invoice',
            'invoice_line_ids': lines,
        })
        self.with_context(spa_rental_internal=True).invoice_id = invoice
        return invoice

    def _spa_deposit_account(self):
        self.ensure_one()
        account = self.company_id._spa_rental_deposit_account()
        if not account:
            raise UserError(self.env._('Configure la cuenta de garantías recibidas en Ajustes del spa.'))
        return account

    def _spa_deposit_payment(self, kind, amount, method, reference=None):
        self.ensure_one()
        journal = self.company_id._spa_journal(method)
        if not journal:
            raise UserError(self.env._('Configure el diario de cobro en Ajustes del spa.'))
        label = self.env._('Garantía %(name)s – %(event)s', name=self.name, event=self.event_name) if kind == 'receive' \
            else self.env._('Devolución de garantía %(name)s – %(event)s', name=self.name, event=self.event_name)
        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound' if kind == 'receive' else 'outbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': amount,
            'date': self.env['spa.tools'].local_today(),
            'journal_id': journal.id,
            'company_id': self.company_id.id,
            'destination_account_id': self._spa_deposit_account().id,
            'memo': ' '.join(filter(None, [label, reference])),
            'spa_rental_id': self.id,
            'spa_deposit_kind': kind,
        })
        payment.action_post()
        self._spa_reconcile_deposit()
        return payment

    def _spa_receive_deposit(self, amount, method, reference=None):
        self.ensure_one()
        if self.state not in ('quotation', 'confirmed', 'in_progress'):
            raise UserError(self.env._('No se cobra garantía en un alquiler %s.',
                                       dict(self._fields['state'].selection)[self.state].lower()))
        if amount <= 0:
            raise UserError(self.env._('El monto de la garantía debe ser mayor que cero.'))
        payment = self._spa_deposit_payment('receive', amount, method, reference)
        self.message_post(body=self.env._('Garantía cobrada: %s (cuenta de garantías recibidas).',
                                          self.currency_id.format(amount)))
        return payment

    def _spa_check_deposit_amount(self, amount):
        self.ensure_one()
        if amount <= 0:
            raise UserError(self.env._('El monto debe ser mayor que cero.'))
        if self.currency_id.compare_amounts(amount, self.deposit_balance) > 0:
            raise UserError(self.env._('El monto (%(amount)s) supera la garantía en custodia (%(balance)s).',
                                       amount=self.currency_id.format(amount),
                                       balance=self.currency_id.format(self.deposit_balance)))

    def _spa_refund_deposit(self, amount, method, reference=None):
        self.ensure_one()
        self._spa_check_deposit_amount(amount)
        payment = self._spa_deposit_payment('refund', amount, method, reference)
        self.message_post(body=self.env._('Garantía devuelta: %s.', self.currency_id.format(amount)))
        return payment

    def _spa_apply_deposit(self, amount, product=None, description=None):
        """Cobra daños con la garantía: factura validada (el precio ya se percibió) pagada con 216200."""
        self.ensure_one()
        self._spa_check_deposit_amount(amount)
        company = self.company_id
        product = product or company._spa_rental_damage_product()
        if not product:
            raise UserError(self.env._('Configure el producto para cobro de daños en Ajustes del spa.'))
        account = self._spa_deposit_account()
        description = description or self.env._('Daños y reposiciones – %s', self.event_name)
        Move = self.env['account.move'].sudo().with_company(company)
        invoice = Move.create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': company.id,
            'invoice_origin': self.name,
            'ref': description,
            'spa_invoice_kind': 'rental',
            'spa_rental_id': self.id,
            'spa_rental_move_kind': 'damage',
            'invoice_line_ids': [Command.create(Move._spa_rental_line_vals(
                product, price=amount, name=description, analytic=company._spa_rental_analytic(), company=company))],
        })
        invoice._spa_post_on_taxable_event()
        journal = company._spa_rental_misc_journal()
        receivable = invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        label = self.env._('Garantía aplicada a %s', invoice.name)
        entry = Move.create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'company_id': company.id,
            'partner_id': self.partner_id.id,
            'date': self.env['spa.tools'].local_today(),
            'ref': label,
            'spa_rental_id': self.id,
            'spa_rental_move_kind': 'deposit_apply',
            'line_ids': [
                Command.create({'account_id': account.id, 'partner_id': self.partner_id.id, 'name': label,
                                'debit': invoice.amount_total, 'credit': 0.0}),
                Command.create({'account_id': receivable[:1].account_id.id, 'partner_id': self.partner_id.id,
                                'name': label, 'debit': 0.0, 'credit': invoice.amount_total}),
            ],
        })
        entry.action_post()
        (entry.line_ids.filtered(lambda l: l.account_id == receivable[:1].account_id) | receivable).reconcile()
        self._spa_reconcile_deposit()
        self.message_post(body=self.env._('Garantía aplicada a daños: %(amount)s (factura %(inv)s).',
                                          amount=self.currency_id.format(amount), inv=invoice.name))
        return invoice

    def _spa_reconcile_deposit(self):
        """Concilia en 216200 los cobros, devoluciones y aplicaciones de la garantía del alquiler."""
        for rental in self.sudo():
            account = rental.company_id._spa_rental_deposit_account()
            if not account or not account.reconcile:
                continue
            moves = rental.deposit_payment_ids.filtered(lambda p: p.state in ('in_process', 'paid')).move_id | \
                rental.move_ids.filtered(lambda m: m.spa_rental_move_kind == 'deposit_apply' and m.state == 'posted')
            lines = moves.line_ids.filtered(lambda l: l.account_id == account and not l.reconciled)
            if lines.filtered(lambda l: l.debit) and lines.filtered(lambda l: l.credit):
                lines.reconcile()

    def action_open_payment(self):
        self.ensure_one()
        if not self.invoice_id or self.invoice_id.sudo().state == 'cancel':
            raise UserError(self.env._('El alquiler %s no tiene factura: confírmelo primero.', self.name))
        return self.env['spa.rental.payment.wizard']._spa_open(invoice=self.invoice_id, rental=self)

    def action_open_deposit_payment(self):
        self.ensure_one()
        amount = max(self.deposit_amount - self.deposit_received + self.deposit_refunded, 0.0) or self.deposit_amount
        return self.env['spa.rental.payment.wizard']._spa_open(rental=self, kind='deposit', amount=amount)

    def action_open_deposit_wizard(self):
        self.ensure_one()
        operation = self.env.context.get('spa_deposit_operation', 'refund')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Devolver garantía') if operation == 'refund' else self.env._('Aplicar garantía a daños'),
            'res_model': 'spa.rental.deposit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rental_id': self.id, 'default_operation': operation,
                        'default_amount': self.deposit_balance},
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Documentos de %s', self.name),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('spa_rental_id', '=', self.id)],
        }

    # ------------------------------------------------------------------
    # CRM y mensajes
    # ------------------------------------------------------------------
    def _spa_sync_lead(self):
        """Crea o vincula la oportunidad del CRM (fuente «Evento») de cada cotización."""
        Lead = self.env['crm.lead'].sudo()
        for rental in self:
            lead = rental.lead_id.sudo()
            team = rental.company_id._spa_rental_team()
            if not lead and team:
                candidates = Lead._spa_find_open_leads(team, rental.partner_id, rental.phone, rental.email, limit=5)
                lead = candidates.filtered(
                    lambda l: not l.spa_rental_ids.filtered(lambda r: r.state != 'cancelled' and r != rental))[:1]
            if not lead:
                lead = Lead.create({
                    'name': self.env._('Evento: %s', rental.event_name),
                    'type': 'opportunity',
                    'team_id': team.id or False,
                    'user_id': team.user_id.id or rental.user_id.id or False,
                    'company_id': rental.company_id.id,
                    'partner_id': rental.partner_id.id,
                    'phone': rental.phone or rental.partner_id.phone,
                    'email_from': rental.email,
                    'source_id': Lead._spa_source('event').id or False,
                    'expected_revenue': rental.amount_total,
                })
            elif lead.won_status == 'pending' and lead.active:
                lead.expected_revenue = sum(lead.spa_rental_ids.filtered(
                    lambda r: r.state != 'cancelled').mapped('amount_total')) or rental.amount_total
            quote_stage = self.env.ref('spa_rental.crm_stage_event_quote', raise_if_not_found=False)
            if quote_stage and lead.won_status == 'pending' and lead.team_id in quote_stage.sudo().team_ids \
                    and lead.stage_id.sequence < quote_stage.sequence:
                lead.stage_id = quote_stage
            rental.with_context(spa_rental_internal=True).lead_id = lead
            local = self.env['spa.tools'].to_local(rental.start)
            lead.message_post(body=self.env._('Cotización de alquiler %(name)s: %(event)s en %(space)s el %(date)s.',
                                              name=rental.name, event=rental.event_name, space=rental.space_id.name,
                                              date=local.strftime('%d/%m/%Y %H:%M')))

    def _spa_lead_won(self):
        for rental in self.sudo():
            lead = rental.lead_id
            if lead and lead.won_status != 'won':
                lead.expected_revenue = sum(lead.spa_rental_ids.filtered(
                    lambda r: r.state != 'cancelled').mapped('amount_total'))
                lead.action_set_won()
                lead.message_post(body=self.env._('Ganada: alquiler %s confirmado.', rental.name))

    def _spa_lead_lost(self):
        for rental in self.sudo():
            lead = rental.lead_id
            if lead and lead.won_status == 'pending' and lead.active and not lead.spa_rental_ids.filtered(
                    lambda r: r.state != 'cancelled'):
                lead.action_set_lost()
                lead.message_post(body=self.env._('Perdida: alquiler %(name)s cancelado. %(reason)s',
                                                  name=rental.name, reason=rental.cancel_reason or ''))

    def _spa_message_values(self):
        self.ensure_one()
        tools = self.env['spa.tools']
        local_start, local_stop = tools.to_local(self.start), tools.to_local(self.stop)
        return {
            'numero': self.name,
            'evento': self.event_name,
            'espacio': self.space_id.name,
            'fecha': local_start.strftime('%d/%m/%Y'),
            'hora': local_start.strftime('%H:%M'),
            'hora_fin': local_stop.strftime('%H:%M'),
            'monto': self.currency_id.format(self.amount_total),
            'garantia': self.currency_id.format(self.deposit_amount),
        }

    def _spa_notify(self, template_code):
        Message = self.env['spa.message']
        for rental in self:
            message = Message.queue(template_code, rental.partner_id, rental._spa_message_values(), record=rental)
            # El contacto del evento puede ser otra persona que el cliente (empresa que alquila).
            phone = Message._normalize_phone(rental.phone)
            if message and phone and message.phone != phone:
                message.sudo().phone = phone

    @api.model
    def _cron_rentals(self):
        """Recordatorios, inicio y fin automático de eventos (al terminar se valida la factura)."""
        now = fields.Datetime.now()
        hours = int(self.env['ir.config_parameter'].sudo().get_param('spa_rental.reminder_hours', 24) or 0)
        if hours > 0:
            for rental in self.search([('state', '=', 'confirmed'), ('reminder_sent', '=', False),
                                       ('start', '>', now), ('start', '<=', now + timedelta(hours=hours))]):
                rental._spa_notify('rental_reminder')
                rental.reminder_sent = True
        self.search([('state', '=', 'confirmed'), ('start', '<=', now), ('stop', '>', now)]).write(
            {'state': 'in_progress'})
        self.search([('state', 'in', RESERVING_STATES), ('stop', '<=', now)]).action_done()
        return True


class SpaRentalLine(models.Model):
    _name = 'spa.rental.line'
    _description = 'Línea de precio del alquiler'
    _order = 'rental_id, sequence, id'

    rental_id = fields.Many2one('spa.rental', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='rental_id.company_id', store=True)
    currency_id = fields.Many2one(related='rental_id.currency_id')
    product_id = fields.Many2one('product.product', string='Producto', required=True,
                                 domain=[('type', '=', 'service'), ('sale_ok', '=', True)])
    name = fields.Char('Descripción', compute='_compute_name', store=True, readonly=False, precompute=True)
    quantity = fields.Float('Cantidad', default=1.0, digits='Product Unit')
    price_unit = fields.Monetary('Precio unitario', compute='_compute_price_unit', store=True, readonly=False,
                                 precompute=True, help='IVA incluido. Solo el gerente lo cambia.')
    discount = fields.Float('Desc. (%)', digits='Discount', help='Solo el gerente aplica descuentos.')
    subtotal = fields.Monetary('Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            line.name = line.product_id.display_name

    @api.depends('product_id')
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.product_id.lst_price

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.currency_id.round(line.quantity * line.price_unit * (1 - (line.discount or 0.0) / 100.0)) \
                if line.currency_id else line.quantity * line.price_unit * (1 - (line.discount or 0.0) / 100.0)

    def _spa_check_rights(self):
        """Las líneas solo cambian en cotización (la factura en borrador ya se generó al confirmar) y
        solo el gerente cambia precios o aplica descuentos."""
        if self.env.su:
            return
        manager = self.env.user.has_group('spa_base.group_spa_manager')
        for line in self:
            if line.rental_id.state != 'quotation':
                raise UserError(self.env._('El precio de %s solo se modifica en cotización: el gerente puede volver '
                                           'el evento a cotización.', line.rental_id.name))
            if manager:
                continue
            if line.discount or line.currency_id.compare_amounts(line.price_unit, line.product_id.lst_price):
                raise UserError(self.env._('Solo el gerente cambia precios o aplica descuentos (%s).',
                                           line.product_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._spa_check_rights()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self._spa_check_rights()
        return res

    def unlink(self):
        if not self.env.su and self.filtered(lambda l: l.rental_id.state != 'quotation'):
            raise UserError(self.env._('Las líneas de precio solo se quitan en cotización.'))
        return super().unlink()
