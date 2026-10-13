# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    spa_rental_ids = fields.One2many('spa.rental', 'lead_id', string='Alquileres y eventos',
                                     groups='spa_base.group_spa_reception')
    spa_rental_count = fields.Integer('Nº de alquileres', compute='_compute_spa_rental_count',
                                      groups='spa_base.group_spa_reception')

    def _compute_spa_rental_count(self):
        data = dict(self.env['spa.rental'].sudo()._read_group(
            [('lead_id', 'in', self.ids)], ['lead_id'], ['__count']))
        for lead in self:
            lead.spa_rental_count = data.get(lead, 0)

    def action_spa_view_rentals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Alquileres y eventos'),
            'res_model': 'spa.rental',
            'view_mode': 'list,form,calendar',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id, 'default_partner_id': self.partner_id.id,
                        'default_phone': self.phone, 'default_event_name': self.name},
        }
