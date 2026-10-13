# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

PENALTY_ACTIONS = [
    ('none', 'Sin penalidad (se devuelve la sesión)'),
    ('lose_session', 'Pierde la sesión'),
    ('fee', 'Cobro de penalidad'),
]


class SpaCancelPolicy(models.Model):
    _name = 'spa.cancel.policy'
    _description = 'Política de cancelación'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char('Política', required=True, translate=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    free_cancel_hours = fields.Float('Cancelación sin costo hasta (horas antes)', default=12.0, required=True)
    late_cancel_action = fields.Selection(PENALTY_ACTIONS, string='Si cancela tarde', default='lose_session', required=True)
    late_cancel_fee_product_id = fields.Many2one('product.product', string='Producto penalidad (cancelación)',
                                                 domain=[('type', '=', 'service')])
    no_show_action = fields.Selection(PENALTY_ACTIONS, string='Si no se presenta', default='lose_session', required=True)
    no_show_fee_product_id = fields.Many2one('product.product', string='Producto penalidad (no-show)',
                                             domain=[('type', '=', 'service')])
    max_cancellations_month = fields.Integer('Máx. cancelaciones al mes', default=0,
                                             help='0 = sin límite. Superado el límite, toda cancelación cuenta como tardía.')
    active = fields.Boolean(default=True, string='Activo')
