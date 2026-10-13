# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaSpace(models.Model):
    _inherit = 'spa.space'

    access_log_ids = fields.One2many('spa.access.log', 'space_id')
    occupancy = fields.Integer('Personas dentro', compute='_compute_occupancy')
    free_now = fields.Integer('Cupos libres ahora', compute='_compute_occupancy')
    occupancy_percent = fields.Float('Ocupación (%)', compute='_compute_occupancy')

    @api.depends('access_log_ids.state', 'access_log_ids.people', 'capacity')
    def _compute_occupancy(self):
        data = dict(self.env['spa.access.log']._read_group(
            [('space_id', 'in', self.ids), ('state', '=', 'open')], ['space_id'], ['people:sum']))
        for space in self:
            inside = data.get(space, 0) or 0
            space.occupancy = inside
            space.free_now = max(space.capacity - inside, 0)
            space.occupancy_percent = 100.0 * inside / space.capacity if space.capacity else 0.0

    def _free_mode_service(self):
        self.ensure_one()
        return self.service_ids.filtered(lambda s: s.active)[:1]

    def _seats_taken(self, start_utc, stop_utc, exclude_booking=None):
        """Agrega a las reservas las personas que están dentro sin reserva.

        Cortesías canjeadas, pases diarios u otros ingresos sin reserva ocupan aforo desde su
        ingreso hasta la salida estimada (ingreso + permanencia máxima del espacio, la misma
        que usa la salida automática). Si ya pasó ese tiempo pero aún no registró la salida,
        se considera dentro hasta ahora.
        """
        taken = super()._seats_taken(start_utc, stop_utc, exclude_booking=exclude_booking)
        stay = timedelta(hours=self.max_stay or 2.0)
        now = fields.Datetime.now()
        walk_ins = self.env['spa.access.log'].sudo().search([
            ('space_id', '=', self.id), ('state', '=', 'open'), ('booking_id', '=', False),
            ('check_in', '<', stop_utc)])
        for log in walk_ins:
            estimated_end = max(log.check_in + stay, now + timedelta(minutes=1))
            if estimated_end > start_utc:
                taken += log.people
        return taken

    def _check_open_now(self, now=None):
        """Error claro si el espacio no atiende en este momento (horario, día o cierre programado)."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        if self.state != 'active':
            raise UserError(self.env._('%s no está operativo.', self.name))
        if not self._within_hours(now, now):
            raise UserError(self.env._(
                '%(space)s está cerrado en este momento (atiende de %(open)s a %(close)s en los días '
                'habilitados; revise también los cierres programados).',
                space=self.name, open='%02d:%02d' % divmod(round(self.open_hour * 60), 60),
                close='%02d:%02d' % divmod(round(self.close_hour * 60), 60)))
        return True


class SpaAccessLog(models.Model):
    _name = 'spa.access.log'
    _description = 'Ingreso a un espacio'
    _order = 'check_in desc, id desc'
    _check_company_auto = True

    partner_id = fields.Many2one('res.partner', string='Persona', required=True, index=True)
    membership_id = fields.Many2one('spa.membership', string='Membresía', index=True)
    courtesy_ref = fields.Char('Pase / referencia')
    space_id = fields.Many2one('spa.space', string='Espacio', required=True, index=True, check_company=True)
    company_id = fields.Many2one(related='space_id.company_id', store=True)
    booking_id = fields.Many2one('spa.booking', string='Reserva')
    service_id = fields.Many2one('spa.service', string='Servicio', check_company=True,
                                 help='Servicio usado (espacios de acceso libre): define el precio del pase diario.')
    day_pass = fields.Boolean('Pase diario', readonly=True,
                              help='Ingreso pagado sin membresía (entrada suelta) a un espacio de acceso libre.')
    people = fields.Integer('Personas', default=1, required=True, help='Socio + invitados que ingresan juntos.')
    check_in = fields.Datetime('Ingreso', required=True, default=fields.Datetime.now)
    check_out = fields.Datetime('Salida')
    method = fields.Selection([('qr', 'Credencial QR'), ('manual', 'Manual')], default='manual', required=True)
    state = fields.Selection([('open', 'Dentro'), ('closed', 'Salió')], default='open', required=True, index=True)
    user_id = fields.Many2one('res.users', string='Registró', default=lambda self: self.env.user)

    def action_check_out(self):
        for log in self.filtered(lambda l: l.state == 'open'):
            log.write({'state': 'closed', 'check_out': fields.Datetime.now()})
            if log.booking_id.state == 'checked_in' and log.booking_id.stop <= fields.Datetime.now():
                log.booking_id.action_done()
        return True

    @api.model
    def _find_membership(self, token=None, partner=None):
        Membership = self.env['spa.membership'].sudo()
        if token:
            membership = Membership.search([('qr_token', '=', token.strip())], limit=1)
            if not membership:
                raise UserError(self.env._('Credencial no reconocida.'))
            return membership
        if partner:
            return partner.spa_membership_id
        raise UserError(self.env._('Escanee la credencial o elija a la persona.'))

    @api.model
    def do_check_in(self, space, token=None, partner=None, guests=0, day_pass=False):
        """Registra el ingreso a un espacio y devuelve el registro creado.

        * Espacio por franja: requiere una reserva confirmada que empiece en los
          próximos 30 minutos o esté en curso; la marca como «en curso». Si la reserva se
          paga con una membresía, esta debe dar acceso (no suspendida).
        * Espacio libre: valida horario, membresía, aforo actual y descuenta el saldo. Los
          invitados ya registrados para hoy (p. ej. desde la web) son los que ingresan;
          solo se crean los que falten.
        * ``day_pass=True`` (espacio libre): pase diario pagado, sin membresía (o elegido
          explícitamente por un socio). Valida horario, estado y aforo y llama al gancho
          ``_after_day_pass()`` (cobro).
        """
        guests = max(int(guests or 0), 0)
        if day_pass:
            return self._do_check_in_day_pass(space, token=token, partner=partner, guests=guests)
        now = fields.Datetime.now()
        method = 'qr' if token else 'manual'
        membership = self._find_membership(token, partner) if (token or not partner) else partner.spa_membership_id
        person = membership.partner_id if membership else partner
        if space.state != 'active':
            raise UserError(self.env._('%s no está operativo.', space.name))
        self._check_not_inside(person, space)

        if space.access_mode == 'slot':
            booking = self.env['spa.booking'].search([
                ('partner_id', '=', person.id), ('space_id', '=', space.id),
                ('state', 'in', ('confirmed', 'checked_in')),
                ('start', '<=', now + timedelta(minutes=30)), ('stop', '>', now),
            ], order='start', limit=1)
            if not booking:
                raise UserError(self.env._('%(name)s no tiene una reserva en %(space)s para esta hora.',
                                           name=person.name, space=space.name))
            booked_with = booking.sudo().membership_id
            if booking.payment_mode == 'membership' and booked_with.state not in ('active', 'grace'):
                states = dict(booked_with._fields['state']._description_selection(self.env))
                raise UserError(self.env._(
                    'La membresía %(name)s no da acceso (estado: %(state)s): no puede ingresar con la reserva '
                    '%(booking)s hasta regularizar el pago.', name=booked_with.name,
                    state=states.get(booked_with.state, booked_with.state), booking=booking.name))
            if booking.state == 'confirmed':
                booking.action_check_in()
            return self.create({
                'partner_id': person.id, 'membership_id': booking.membership_id.id, 'space_id': space.id,
                'booking_id': booking.id, 'people': booking.seats, 'method': method,
                'service_id': booking.service_id.id,
            })

        # Espacio de acceso libre
        if not membership:
            raise UserError(self.env._(
                '%s no tiene una membresía vigente. Registre el ingreso como pase diario (entrada suelta).',
                person.name))
        service = space._free_mode_service()
        if not service:
            raise UserError(self.env._('Configure el servicio de %s.', space.name))
        space._check_open_now(now)
        people = 1 + guests
        space._lock_for_booking()
        space.invalidate_recordset(['occupancy'])
        if space.occupancy + people > space.capacity:
            raise UserError(self.env._('%(space)s está lleno (%(n)s de %(cap)s).', space=space.name,
                                       n=space.occupancy, cap=space.capacity))
        stop = now + timedelta(hours=space.max_stay or service.duration)
        membership._spa_check_access(service, now, stop, guests=guests)
        membership._spa_consume(service, now, 'checkin')
        log = self.create({
            'partner_id': person.id, 'membership_id': membership.id, 'space_id': space.id,
            'people': people, 'method': method, 'service_id': service.id,
        })
        if guests:
            self._register_free_guests(membership, service, guests, person)
        return log

    def _check_not_inside(self, person, space):
        if self.search_count([('partner_id', '=', person.id), ('space_id', '=', space.id), ('state', '=', 'open')]):
            raise UserError(self.env._('%(name)s ya está dentro de %(space)s.', name=person.name, space=space.name))

    @api.model
    def _register_free_guests(self, membership, service, guests, person):
        """Invitados que ingresan con el socio a un espacio libre.

        Primero se usan los invitados que el socio ya registró para hoy (web o recepción) en
        ese servicio o sin servicio: pasan a «Asistió» sin consumir otro free pass. Solo se
        crean («Invitado N de …») los que falten.
        """
        Guest = self.env['spa.guest'].sudo()
        today = self.env['spa.tools'].local_today()
        planned = Guest.search([
            ('membership_id', '=', membership.id), ('date', '=', today), ('state', '=', 'planned'),
            ('booking_id', '=', False), ('service_id', 'in', [service.id, False])], order='id')
        planned = planned.sorted(lambda g: (g.service_id != service, g.id))[:guests]
        planned.write({'state': 'attended', 'service_id': service.id})
        created = Guest.browse()
        for index in range(len(planned), guests):
            created |= Guest.create({
                'name': self.env._('Invitado %(n)s de %(host)s', n=index + 1, host=person.name),
                'membership_id': membership.id, 'service_id': service.id, 'state': 'attended'})
        return planned | created

    @api.model
    def _do_check_in_day_pass(self, space, token=None, partner=None, guests=0):
        """Pase diario: ingreso pagado sin membresía a un espacio de acceso libre."""
        now = fields.Datetime.now()
        method = 'qr' if token else 'manual'
        person = partner
        if not person and token:
            person = self._find_membership(token).partner_id
        if not person:
            raise UserError(self.env._('Elija a la persona (o cree su contacto) para registrar el pase diario.'))
        if space.access_mode != 'free':
            raise UserError(self.env._(
                '%s funciona con reserva por franja: registre una reserva con pago suelto.', space.name))
        service = space._free_mode_service()
        if not service:
            raise UserError(self.env._('Configure el servicio de %s.', space.name))
        space._check_open_now(now)
        self._check_not_inside(person, space)
        people = 1 + guests
        space._lock_for_booking()
        space.invalidate_recordset(['occupancy'])
        if space.occupancy + people > space.capacity:
            raise UserError(self.env._('%(space)s está lleno (%(n)s de %(cap)s).', space=space.name,
                                       n=space.occupancy, cap=space.capacity))
        log = self.create({
            'partner_id': person.id, 'space_id': space.id, 'service_id': service.id, 'people': people,
            'method': method, 'day_pass': True,
        })
        log._after_day_pass()
        return log

    def _after_day_pass(self):
        """Gancho del pase diario (se llama una vez por ingreso con ``day_pass=True``).

        spa_billing lo extiende con ``super()`` para cobrar la entrada: producto
        ``self.service_id.product_id`` × ``self.people`` (persona + acompañantes), cliente
        ``self.partner_id``, área analítica ``self.space_id.analytic_account_id``. Corre en la
        misma transacción: si lanza un error, el ingreso no se registra. Devuelve True.
        """
        return True

    @api.model
    def _cron_auto_check_out(self):
        """Salida automática: espacios libres tras la permanencia máxima; reservas al terminar."""
        now = fields.Datetime.now()
        for log in self.search([('state', '=', 'open')]):
            limit = log.booking_id.stop if log.booking_id else \
                log.check_in + timedelta(hours=log.space_id.max_stay or 2.0)
            if limit and limit <= now:
                log.action_check_out()
        return True
