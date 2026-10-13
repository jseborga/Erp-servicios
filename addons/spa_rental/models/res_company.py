# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    spa_rental_deposit_account_id = fields.Many2one(
        'account.account', string='Cuenta de garantías recibidas',
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current')), ('company_ids', 'in', id)]",
        help='Pasivo donde se registran las garantías de alquiler. Vacío = 216200 del plan de cuentas.')
    spa_rental_analytic_id = fields.Many2one(
        'account.analytic.account', string='Área analítica de eventos y clases',
        help='Área de las facturas de alquileres y clases. Vacío = «Eventos, clases y alquileres».')
    spa_rental_damage_product_id = fields.Many2one(
        'product.product', string='Producto para cobro de daños', domain=[('type', '=', 'service')],
        help='Se usa al aplicar la garantía a daños o reposiciones después del evento.')
    spa_rental_team_id = fields.Many2one(
        'crm.team', string='Embudo de eventos',
        help='Embudo del CRM donde entran las cotizaciones de alquiler. Vacío = «Eventos y alquileres».')

    def _spa_rental_deposit_account(self):
        self.ensure_one()
        return self.spa_rental_deposit_account_id or self.env['account.chart.template'].with_company(self).ref(
            'l10n_bo_spa_2162', raise_if_not_found=False) or self.env['account.account']

    def _spa_rental_analytic(self):
        self.ensure_one()
        return self.spa_rental_analytic_id or self.env.ref(
            'l10n_bo_spa.analytic_area_eventos', raise_if_not_found=False) or self.env['account.analytic.account']

    def _spa_rental_damage_product(self):
        self.ensure_one()
        return self.spa_rental_damage_product_id or self.env.ref(
            'spa_rental.product_rental_damage', raise_if_not_found=False) or self.env['product.product']

    def _spa_rental_team(self):
        self.ensure_one()
        team = self.spa_rental_team_id or self.env.ref('spa_rental.crm_team_events', raise_if_not_found=False)
        return team.sudo() if team else self.env['crm.team'].sudo()

    def _spa_rental_misc_journal(self):
        self.ensure_one()
        return self.env['account.journal'].sudo().search(
            [('type', '=', 'general'), ('company_id', '=', self.id)], order='sequence, id', limit=1)
