# Part of ERP Servicios Spa. License LGPL-3.
import re

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaGuest(models.Model):
    _name = 'spa.guest'
    _description = 'Invitado de un socio'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char('Invitado', required=True, tracking=True)
    phone = fields.Char('Celular')
    email = fields.Char('Correo')
    partner_id = fields.Many2one('res.partner', string='Contacto del invitado', readonly=True, copy=False)
    membership_id = fields.Many2one('spa.membership', string='Membresía del anfitrión', required=True,
                                    ondelete='cascade', index=True, check_company=True)
    host_partner_id = fields.Many2one(related='membership_id.partner_id', string='Anfitrión', store=True)
    company_id = fields.Many2one(related='membership_id.company_id', store=True)
    date = fields.Date('Fecha de visita', required=True, default=lambda self: self.env['spa.tools'].local_today())
    service_id = fields.Many2one('spa.service', string='Servicio')
    charge_type = fields.Selection([('free_pass', 'Free pass'), ('fee', 'Tarifa de invitado')],
                                   string='Cobro', readonly=True, copy=False)
    state = fields.Selection([
        ('planned', 'Programado'),
        ('attended', 'Asistió'),
        ('cancelled', 'Cancelado'),
    ], default='planned', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        guests = super().create(vals_list)
        for guest in guests:
            if guest.membership_id.state not in ('active', 'grace'):
                raise UserError(self.env._('La membresía del anfitrión no está vigente.'))
            if not guest.charge_type:
                guest.charge_type = guest.membership_id._guest_charge_type(guest.date)
            guest._ensure_partner()
            guest._after_guest_registered()
        return guests

    def _ensure_partner(self):
        Partner = self.env['res.partner'].sudo()
        for guest in self.filtered(lambda g: not g.partner_id):
            partner = Partner.browse()
            digits = re.sub(r'\D', '', guest.phone or '')
            if len(digits) >= 7:
                # Mismo número escrito distinto ("+591 700-11122" y "70011122"): compara los últimos 8 dígitos.
                candidates = Partner.search([('phone', 'ilike', digits[-4:])])
                partner = candidates.filtered(
                    lambda p: re.sub(r'\D', '', p.phone or '')[-8:] == digits[-8:])[:1]
            if not partner and guest.email:
                partner = Partner.search([('email', '=ilike', guest.email)], limit=1)
            if not partner:
                partner = Partner.create({'name': guest.name, 'phone': guest.phone, 'email': guest.email})
            guest.partner_id = partner

    def _after_guest_registered(self):
        """Gancho: cobro de tarifa (spa_billing) y alta como prospecto (spa_crm)."""
        return True

    def action_attended(self):
        self.write({'state': 'attended'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
