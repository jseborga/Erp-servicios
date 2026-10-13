# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    spa_pos_member_label = fields.Char('Socio (POS)', compute='_compute_spa_pos_member_label',
                                       help='Plan y estado de la membresía que ve el cajero en el POS.')
    spa_pos_member_live = fields.Boolean('Socio vigente (POS)', compute='_compute_spa_pos_member_label')

    @api.depends('spa_membership_ids.state', 'spa_membership_ids.plan_id')
    def _compute_spa_pos_member_label(self):
        # sudo: los cajeros del POS no necesariamente leen membresías.
        states = dict(self.env['spa.membership']._fields['state']._description_selection(self.env))
        for partner in self:
            membership = partner.sudo().spa_membership_id
            if membership:
                partner.spa_pos_member_label = f'{membership.plan_id.name} · {states.get(membership.state, "")}'
                partner.spa_pos_member_live = membership.state in ('active', 'grace')
            else:
                partner.spa_pos_member_label = False
                partner.spa_pos_member_live = False

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'spa_pos_member_label', 'spa_pos_member_live']

    def _spa_pos_open_debt(self, company, exclude_orders=None):
        """Consumo del restaurante y la cafetería pendiente de pago (facturas 'pos' + cargos sin factura)."""
        self.ensure_one()
        partner = self.commercial_partner_id
        moves = self.env['account.move'].sudo().search([
            ('commercial_partner_id', '=', partner.id),
            ('company_id', '=', company.id),
            ('spa_invoice_kind', '=', 'pos'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
        ])
        debt = sum(moves.mapped('amount_residual_signed'))
        orders = self.env['pos.order'].sudo().search([
            ('partner_id', 'child_of', partner.id),
            ('company_id', '=', company.id),
            ('state', '=', 'paid'),
            ('account_move', '=', False),
            ('id', 'not in', (exclude_orders or self.env['pos.order']).ids),
        ])
        debt += sum(order._spa_member_account_amount() for order in orders)
        return debt
