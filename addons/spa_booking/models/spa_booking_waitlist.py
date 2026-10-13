# Part of ERP Servicios Spa. License LGPL-3.
"""Lista de espera de franjas llenas.

Flujo: la persona se anota (recepción o web: ``_spa_join``) → cuando se libera un cupo
(cancelación, más aforo, otra persona que no usa su turno) se avisa por WhatsApp a la
primera de la lista que quepa (orden de llegada) y se le guarda el cupo N minutos
(``spa_booking.waitlist_priority_minutes``). No se reserva sola: la persona confirma en
la web o en recepción. Si no reserva a tiempo, su turno vence y se avisa a la siguiente.
"""
from collections import OrderedDict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from .spa_service import BLOCKING_STATES

OPEN_STATES = ('waiting', 'notified')
PRIORITY_PARAM = 'spa_booking.waitlist_priority_minutes'
DEFAULT_PRIORITY_MINUTES = 30


class SpaBookingWaitlist(models.Model):
    _name = 'spa.booking.waitlist'
    _description = 'Lista de espera de una franja'
    _inherit = ['mail.thread']
    _order = 'start, id'
    _check_company_auto = True

    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, index=True, tracking=True)
    phone = fields.Char(related='partner_id.phone', string='Celular')
    membership_id = fields.Many2one('spa.membership', string='Membresía', check_company=True,
                                    domain="[('partner_id', '=', partner_id), ('state', 'in', ('active', 'grace'))]")
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    service_id = fields.Many2one('spa.service', string='Servicio', required=True, check_company=True,
                                 domain=[('space_id.access_mode', '=', 'slot')])
    space_id = fields.Many2one(related='service_id.space_id', store=True, string='Espacio', index=True)
    start = fields.Datetime('Inicio', required=True, index=True)
    stop = fields.Datetime('Fin', compute='_compute_stop', store=True, required=True, precompute=True)
    guests = fields.Integer('Invitados', default=0)
    seats = fields.Integer('Cupos', compute='_compute_seats', store=True)
    channel = fields.Selection([
        ('reception', 'Recepción'),
        ('phone', 'Teléfono'),
        ('whatsapp', 'WhatsApp'),
        ('portal', 'Web del socio'),
    ], string='Canal', default='reception', required=True)
    state = fields.Selection([
        ('waiting', 'En espera'),
        ('notified', 'Avisado (cupo guardado)'),
        ('booked', 'Reservó'),
        ('expired', 'Vencido'),
        ('cancelled', 'Retirado'),
    ], string='Estado', default='waiting', required=True, index=True, tracking=True, copy=False)
    position = fields.Integer('Puesto', compute='_compute_position',
                              help='Lugar en la lista de esa franja (1 = el próximo en ser avisado).')
    notified_at = fields.Datetime('Avisado el', readonly=True, copy=False)
    priority_until = fields.Datetime('Cupo guardado hasta', readonly=True, copy=False, index=True)
    booking_id = fields.Many2one('spa.booking', string='Reserva', readonly=True, copy=False, check_company=True)
    spa_message_id = fields.Many2one('spa.message', string='Aviso de WhatsApp', readonly=True, copy=False)
    note = fields.Text('Notas')

    _guests_positive = models.Constraint('CHECK (guests >= 0)', 'Los invitados no pueden ser negativos.')

    @api.depends('start', 'service_id.duration')
    def _compute_stop(self):
        for entry in self:
            entry.stop = entry.start + timedelta(hours=entry.service_id.duration or 1.0) if entry.start else False

    @api.depends('service_id.seats_per_booking', 'guests')
    def _compute_seats(self):
        for entry in self:
            entry.seats = (entry.service_id.seats_per_booking or 1) + max(entry.guests, 0)

    def _compute_position(self):
        waiting = self.sudo().search([('state', 'in', OPEN_STATES),
                                      ('service_id', 'in', self.service_id.ids),
                                      ('start', 'in', [entry.start for entry in self if entry.start])],
                                     order='id')
        for entry in self:
            same = waiting.filtered(lambda w: w.service_id == entry.service_id and w.start == entry.start)
            entry.position = (same.ids.index(entry.id) + 1) if entry.id in same.ids else 0

    def _compute_display_name(self):
        tools = self.env['spa.tools']
        for entry in self:
            local = tools.to_local(entry.start)
            entry.display_name = '%s · %s · %s' % (entry.partner_id.name or '', entry.service_id.name or '',
                                                   local.strftime('%d/%m %H:%M') if local else '')

    # ------------------------------------------------------------------
    # API (recepción y web del socio)
    # ------------------------------------------------------------------
    @api.model
    def _priority_minutes(self):
        """Minutos que se guarda el cupo (parámetro; sin valor = 0, viene en 30 con los datos)."""
        value = self.env['ir.config_parameter'].sudo().get_param(PRIORITY_PARAM)
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return DEFAULT_PRIORITY_MINUTES

    @api.model
    def _spa_join(self, partner, service, start, membership=None, guests=0, channel='portal', note=False):
        """Anota a ``partner`` en la lista de espera de una franja llena y devuelve la inscripción.

        :param partner: res.partner que espera.
        :param service: spa.service de un espacio por franja.
        :param start: inicio de la franja (datetime UTC naïve o texto, como ``_get_slots()['start']``).
        :param membership: spa.membership con la que reservará (opcional: sin ella, pago suelto).
        :param guests: invitados que lo acompañarían (ocupan cupo).
        :param channel: reception / phone / whatsapp / portal.
        :raises UserError: franja pasada o fuera de horario, plan que no lo permite, ya tiene una
            reserva en ese horario o la franja todavía tiene cupo (que reserve directamente).

        Si la persona ya está en la lista de esa franja devuelve la inscripción existente.
        La web llama a este método con ``sudo()``; el puesto en la lista está en ``position``.
        """
        if not (partner and service and start):
            raise UserError(self.env._('Indique la persona, el servicio y la franja.'))
        start = fields.Datetime.to_datetime(start)
        service = service.sudo()
        space = service.space_id
        stop = start + timedelta(hours=service.duration)
        guests = max(int(guests or 0), 0)
        if service.access_mode != 'slot':
            raise UserError(self.env._('%s es de acceso libre: no tiene lista de espera.', space.name))
        if start <= fields.Datetime.now():
            raise UserError(self.env._('Esa franja ya empezó: elija otro horario.'))
        if space.state != 'active' or not space._within_hours(start, stop):
            raise UserError(self.env._('El horario está fuera de la atención de %s.', space.name))
        if guests and not service.guest_allowed:
            raise UserError(self.env._('%s no admite invitados.', service.name))
        if membership:
            if membership.partner_id != partner:
                raise UserError(self.env._('La membresía no pertenece a %s.', partner.name))
            membership.sudo()._spa_check_access(service, start, stop, guests=guests)
        existing = self.sudo().search([('partner_id', '=', partner.id), ('service_id', '=', service.id),
                                       ('start', '=', start), ('state', 'in', OPEN_STATES)], limit=1)
        if existing:
            return self.browse(existing.ids)
        if self.env['spa.booking'].sudo().search_count([
                ('partner_id', '=', partner.id), ('state', 'in', BLOCKING_STATES),
                ('start', '<', stop), ('stop', '>', start)], limit=1):
            raise UserError(self.env._('%s ya tiene una reserva en ese horario.', partner.name))
        seats = (service.seats_per_booking or 1) + guests
        taken = space.with_context(spa_waitlist_partner_id=partner.id)._seats_taken(start, stop)
        staff_ok = not service.requires_staff or service._free_employee(start, stop)
        if taken + seats <= space.capacity and staff_ok:
            raise UserError(self.env._('Todavía hay cupo en ese horario: reserve directamente.'))
        entry = self.create({
            'partner_id': partner.id,
            'membership_id': membership.id if membership else False,
            'company_id': service.company_id.id,
            'service_id': service.id,
            'start': start,
            'guests': guests,
            'channel': channel or 'reception',
            'note': note,
        })
        return entry

    @api.model
    def _spa_mark_booked(self, booking):
        """La persona reservó la franja por la que esperaba (llamado al confirmar la reserva)."""
        entries = self.sudo().search([
            ('partner_id', '=', booking.partner_id.id), ('service_id', '=', booking.service_id.id),
            ('start', '=', booking.start), ('state', 'in', OPEN_STATES)])
        if entries:
            entries.write({'state': 'booked', 'booking_id': booking.id})
        return entries

    @api.model
    def _spa_on_seats_freed(self, bookings):
        """Reservas canceladas: revisa la lista de espera de esas franjas."""
        bookings = bookings.filtered(lambda b: b.state not in BLOCKING_STATES and b.start)
        if not bookings:
            return self.browse()
        domain = Domain.OR([
            Domain('space_id', '=', booking.space_id.id) & Domain('start', '<', booking.stop)
            & Domain('stop', '>', booking.start)
            for booking in bookings])
        return self._spa_notify_available(domain)

    @api.model
    def _spa_notify_available(self, domain=None):
        """Avisa, por orden de llegada, a quien espera una franja que ahora tiene cupo.

        Cada inscripción que cabe en los cupos libres pasa a «Avisado» y se le guarda el cupo.
        Quien no cabe (p. ej. pide 2 cupos y se liberó 1) sigue esperando. Devuelve las avisadas.
        """
        now = fields.Datetime.now()
        Waitlist = self.sudo()
        waiting = Waitlist.search(Domain.AND([
            [('state', '=', 'waiting'), ('start', '>', now)], domain or []]), order='id')
        groups = OrderedDict()
        for entry in waiting:
            groups.setdefault((entry.service_id.id, entry.start), Waitlist.browse())
            groups[(entry.service_id.id, entry.start)] |= entry
        notified = Waitlist.browse()
        for entries in groups.values():
            first = entries[0]
            service, space = first.service_id, first.space_id
            if space.state != 'active' or not space._within_hours(first.start, first.stop):
                continue
            free = space.capacity - space._seats_taken(first.start, first.stop)
            if free <= 0:
                continue
            if service.requires_staff and not service._free_employee(first.start, first.stop):
                continue
            for entry in entries:
                if entry.seats <= free:
                    entry._spa_notify()
                    notified |= entry
                    free -= entry.seats
                if free <= 0:
                    break
        return notified

    def _spa_notify(self):
        """Avisa por WhatsApp que se liberó un cupo y lo guarda los minutos de prioridad."""
        now = fields.Datetime.now()
        minutes = self._priority_minutes()
        tools = self.env['spa.tools']
        for entry in self.sudo():
            entry.write({'state': 'notified', 'notified_at': now,
                         'priority_until': now + timedelta(minutes=minutes)})
            local = tools.to_local(entry.start)
            message = self.env['spa.message'].queue('waitlist_available', entry.partner_id, {
                'servicio': entry.service_id.name,
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': local.strftime('%H:%M'),
                'minutos': minutes,
            }, record=entry)
            entry.spa_message_id = message
            body = self.env._('Se liberó un cupo: se le guarda hasta las %s.',
                              tools.to_local(entry.priority_until).strftime('%H:%M'))
            if not message:
                body += ' ' + self.env._('No se generó el WhatsApp (sin celular válido o plantilla inactiva): '
                                         'avise por teléfono.')
            entry.message_post(body=body)
        return True

    @api.model
    def _cron_waitlist(self):
        """Vence inscripciones pasadas o sin respuesta a tiempo y avisa a las siguientes."""
        now = fields.Datetime.now()
        Waitlist = self.sudo()
        Waitlist.search([('state', 'in', OPEN_STATES), ('start', '<=', now)]).write({'state': 'expired'})
        late = Waitlist.search([('state', '=', 'notified'), ('priority_until', '<=', now)])
        for entry in late:
            entry.state = 'expired'
            entry.message_post(body=self.env._('No reservó a tiempo: el cupo pasa a la siguiente persona.'))
        self._spa_notify_available()
        return True

    # ------------------------------------------------------------------
    # Botones
    # ------------------------------------------------------------------
    def action_check_availability(self):
        """Revisa si hay cupo ahora y avisa (en orden de llegada)."""
        notified = self._spa_notify_available([('id', 'in', self.ids)])
        if not notified:
            message = self.env._('Todavía no hay cupo libre (o hay personas antes en la lista).')
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': self.env._('Lista de espera'), 'message': message, 'type': 'warning'}}
        return True

    def action_cancel(self):
        """La persona se retira de la lista. Si tenía un cupo guardado, pasa al siguiente."""
        held = self.filtered(lambda e: e.state == 'notified')
        self.filtered(lambda e: e.state in OPEN_STATES).write({'state': 'cancelled'})
        if held:
            self._spa_notify_available(Domain.OR([
                Domain('service_id', '=', entry.service_id.id) & Domain('start', '=', entry.start)
                for entry in held]))
        return True

    def action_book(self):
        """Abre una reserva con los datos de la inscripción para completarla y confirmarla."""
        self.ensure_one()
        if self.state not in OPEN_STATES:
            raise UserError(self.env._('Esta inscripción ya no está en espera.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reservar'),
            'res_model': 'spa.booking',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_membership_id': self.membership_id.id,
                'default_payment_mode': 'membership' if self.membership_id else 'single',
                'default_service_id': self.service_id.id,
                'default_start': fields.Datetime.to_string(self.start),
                'default_channel': self.channel if self.channel != 'portal' else 'reception',
            },
        }
