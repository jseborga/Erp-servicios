# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaBookingSlotWizard(models.TransientModel):
    """Reserva rápida para recepción: elegir servicio y día, ver franjas libres y reservar."""
    _name = 'spa.booking.slot.wizard'
    _description = 'Reserva rápida'

    partner_id = fields.Many2one('res.partner', string='Cliente', required=True)
    membership_id = fields.Many2one('spa.membership', string='Membresía',
                                    domain="[('partner_id', '=', partner_id), ('state', 'in', ('active', 'grace'))]")
    service_id = fields.Many2one('spa.service', string='Servicio', required=True,
                                 domain=[('space_id.access_mode', '=', 'slot')])
    date = fields.Date('Día', required=True, default=lambda self: self.env['spa.tools'].local_today())
    channel = fields.Selection([('reception', 'Recepción'), ('phone', 'Teléfono'), ('whatsapp', 'WhatsApp')],
                               default='reception', required=True)
    guest_names = fields.Text('Invitados', help='Un invitado por línea: "Nombre, celular".')
    line_ids = fields.One2many('spa.booking.slot.line', 'wizard_id', string='Franjas')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        membership = self.partner_id.spa_membership_id
        self.membership_id = membership if membership.state in ('active', 'grace') else False

    def _guests(self):
        guests = []
        for raw in (self.guest_names or '').splitlines():
            if not raw.strip():
                continue
            name, _sep, phone = raw.partition(',')
            guests.append({'name': name.strip(), 'phone': phone.strip() or False})
        return guests

    def action_search(self):
        self.ensure_one()
        guests = self._guests()
        service = self.service_id.with_context(spa_waitlist_partner_id=self.partner_id.id)
        slots = service._get_slots(self.date, seats=1 + len(guests), membership=self.membership_id,
                                   guests=len(guests), ignore_lead=True)
        self.line_ids = [(5, 0, 0)] + [(0, 0, {
            'start': slot['start'], 'stop': slot['stop'], 'label': slot['label'], 'free': slot['free'],
            'capacity': slot['capacity'], 'available': slot['available'], 'reason': slot['reason'] or '',
            'can_wait': slot.get('waitlist', False),
        }) for slot in slots]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': self.env._('Reserva rápida'),
        }


class SpaBookingSlotLine(models.TransientModel):
    _name = 'spa.booking.slot.line'
    _description = 'Franja disponible'
    _order = 'start'

    wizard_id = fields.Many2one('spa.booking.slot.wizard', required=True, ondelete='cascade')
    start = fields.Datetime(required=True)
    stop = fields.Datetime(required=True)
    label = fields.Char('Horario')
    free = fields.Integer('Libres')
    capacity = fields.Integer('Aforo')
    available = fields.Boolean('Disponible')
    reason = fields.Char('Motivo')
    can_wait = fields.Boolean('Admite lista de espera')

    def action_book(self):
        self.ensure_one()
        wizard = self.wizard_id
        if not self.available:
            raise UserError(self.reason or self.env._('Franja no disponible.'))
        guests = wizard._guests()
        booking = self.env['spa.booking'].create({
            'partner_id': wizard.partner_id.id,
            'membership_id': wizard.membership_id.id,
            'payment_mode': 'membership' if wizard.membership_id else 'single',
            'service_id': wizard.service_id.id,
            'start': self.start,
            'channel': wizard.channel,
            'guest_ids': [(0, 0, guest) for guest in guests],
        })
        booking.action_confirm()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'spa.booking',
            'res_id': booking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_waitlist(self):
        """Franja llena: anota a la persona en la lista de espera."""
        self.ensure_one()
        wizard = self.wizard_id
        entry = self.env['spa.booking.waitlist']._spa_join(
            wizard.partner_id, wizard.service_id, self.start, membership=wizard.membership_id or None,
            guests=len(wizard._guests()), channel=wizard.channel)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'spa.booking.waitlist',
            'res_id': entry.id,
            'view_mode': 'form',
            'target': 'current',
        }
