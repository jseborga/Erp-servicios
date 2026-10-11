# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    spa_membership_ids = fields.One2many('spa.membership', 'partner_id', string='Membresías')
    spa_membership_id = fields.Many2one('spa.membership', string='Membresía vigente',
                                        compute='_compute_spa_membership')
    spa_member_state = fields.Selection([
        ('draft', 'Por activar'), ('active', 'Activa'), ('grace', 'En gracia'), ('suspended', 'Suspendida'),
        ('expired', 'Vencida'), ('cancelled', 'Cancelada'),
    ], string='Estado de socio', compute='_compute_spa_membership')
    spa_membership_count = fields.Integer(compute='_compute_spa_membership')

    @api.depends('spa_membership_ids.state', 'spa_membership_ids.date_end')
    def _compute_spa_membership(self):
        for partner in self:
            memberships = partner.spa_membership_ids
            current = memberships.filtered(lambda m: m.state in ('active', 'grace')) \
                or memberships.filtered(lambda m: m.state == 'suspended')
            partner.spa_membership_id = current.sorted('date_end', reverse=True)[:1]
            partner.spa_member_state = partner.spa_membership_id.state
            partner.spa_membership_count = len(memberships)

    def action_view_spa_memberships(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Membresías'),
            'res_model': 'spa.membership',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
