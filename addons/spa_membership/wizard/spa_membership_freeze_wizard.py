# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models


class SpaMembershipFreezeWizard(models.TransientModel):
    _name = 'spa.membership.freeze.wizard'
    _description = 'Congelar membresía'

    membership_id = fields.Many2one('spa.membership', string='Membresía', required=True, ondelete='cascade')
    date_from = fields.Date('Desde', required=True, default=lambda self: self.env['spa.tools'].local_today())
    date_to = fields.Date('Hasta', required=True)
    reason = fields.Char('Motivo', required=True, help='Ej. viaje, certificado médico.')
    days = fields.Integer('Días', compute='_compute_preview')
    days_left = fields.Integer('Días disponibles este año', compute='_compute_preview')
    date_end_current = fields.Date(related='membership_id.date_end', string='Vence hoy')
    date_end_new = fields.Date('Nuevo vencimiento', compute='_compute_preview')

    @api.depends('membership_id', 'date_from', 'date_to')
    def _compute_preview(self):
        for wizard in self:
            membership = wizard.membership_id
            ok = wizard.date_from and wizard.date_to and wizard.date_to >= wizard.date_from
            wizard.days = (wizard.date_to - wizard.date_from).days + 1 if ok else 0
            year = (wizard.date_from or self.env['spa.tools'].local_today()).year
            wizard.days_left = max(membership.freeze_max_days - membership._spa_frozen_days(year), 0) \
                if membership else 0
            wizard.date_end_new = membership.date_end + timedelta(days=wizard.days) \
                if membership.date_end and ok else membership.date_end

    def action_apply(self):
        self.ensure_one()
        self.membership_id._spa_freeze(self.date_from, self.date_to, self.reason)
        return {'type': 'ir.actions.act_window_close'}

