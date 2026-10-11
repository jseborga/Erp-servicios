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
    def do_check_in(self, space, token=None, partner=None, guests=0):
        """Registra el ingreso a un espacio y devuelve el registro creado.

        * Espacio por franja: requiere una reserva confirmada que empiece en los
          próximos 30 minutos o esté en curso; la marca como «en curso».
        * Espacio libre: valida la membresía, el aforo actual y descuenta el saldo.
        """
        now = fields.Datetime.now()
        method = 'qr' if token else 'manual'
        membership = self._find_membership(token, partner) if (token or not partner) else partner.spa_membership_id
        person = membership.partner_id if membership else partner
        if space.state != 'active':
            raise UserError(self.env._('%s no está operativo.', space.name))
        already = self.search([('partner_id', '=', person.id), ('space_id', '=', space.id), ('state', '=', 'open')])
        if already:
            raise UserError(self.env._('%(name)s ya está dentro de %(space)s.', name=person.name, space=space.name))

        if space.access_mode == 'slot':
            booking = self.env['spa.booking'].search([
                ('partner_id', '=', person.id), ('space_id', '=', space.id),
                ('state', 'in', ('confirmed', 'checked_in')),
                ('start', '<=', now + timedelta(minutes=30)), ('stop', '>', now),
            ], order='start', limit=1)
            if not booking:
                raise UserError(self.env._('%(name)s no tiene una reserva en %(space)s para esta hora.',
                                           name=person.name, space=space.name))
            if booking.state == 'confirmed':
                booking.action_check_in()
            return self.create({
                'partner_id': person.id, 'membership_id': booking.membership_id.id, 'space_id': space.id,
                'booking_id': booking.id, 'people': booking.seats, 'method': method,
            })

        # Espacio de acceso libre
        if not membership:
            raise UserError(self.env._('%s no tiene una membresía vigente. Venda una entrada suelta.', person.name))
        service = space._free_mode_service()
        if not service:
            raise UserError(self.env._('Configure el servicio de %s.', space.name))
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
            'people': people, 'method': method,
        })
        if guests:
            for index in range(guests):
                self.env['spa.guest'].sudo().create({
                    'name': self.env._('Invitado %(n)s de %(host)s', n=index + 1, host=person.name),
                    'membership_id': membership.id, 'service_id': service.id, 'state': 'attended'})
        return log

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
