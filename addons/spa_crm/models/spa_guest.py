# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import fields, models

LIVE_STATES = ('active', 'grace', 'suspended')


class SpaGuest(models.Model):
    _inherit = 'spa.guest'

    lead_id = fields.Many2one('crm.lead', string='Prospecto', readonly=True, copy=False, index='btree_not_null',
                              groups='sales_team.group_sale_salesman')

    def _after_guest_registered(self):
        res = super()._after_guest_registered()
        for guest in self:
            guest._spa_crm_register_lead()
        return res

    def _spa_crm_register_lead(self):
        """El invitado pasa a ser prospecto referido por su anfitrión (sin duplicados)."""
        self.ensure_one()
        guest = self.sudo()
        partner = guest.partner_id
        if not partner or guest.state == 'cancelled':
            return False
        # Sin celular ni correo no hay forma de hacer seguimiento (p. ej. «Invitado 1 de …» en el check-in).
        if not (guest.phone or guest.email or partner.phone or partner.email):
            return False
        if partner.spa_membership_ids.filtered(lambda m: m.state in LIVE_STATES):
            return False
        host = guest.host_partner_id
        if partner == host:
            return False
        Lead = self.env['crm.lead'].sudo()
        lead = Lead._spa_upsert_acquisition(
            partner, guest.company_id, source=Lead._spa_source('member_guest'), stage_code='visit',
            name=self.env._('%(guest)s (invitado de %(host)s)', guest=guest.name, host=host.name),
            referred_by=host, phone=guest.phone, email=guest.email,
            note=self.env._('Visita como invitado de %(host)s el %(date)s.', host=host.name,
                            date=guest.date.strftime('%d/%m/%Y')))
        if not lead:
            return False
        guest.lead_id = lead
        days = int(self.env['ir.config_parameter'].sudo().get_param('spa_crm.followup_days', 0) or 0)
        if days:
            lead._spa_schedule_activity(self.env._('Seguimiento de la visita como invitado'),
                                        deadline=guest.date + timedelta(days=days))
        if self.env['ir.config_parameter'].sudo().get_param('spa_crm.guest_welcome'):
            self.env['spa.message'].queue('guest_welcome', partner, {
                'nombre': (guest.name or '').split(' ')[0],
                'anfitrion': host.name,
                'fecha': guest.date.strftime('%d/%m/%Y'),
            }, record=guest)
        return lead
