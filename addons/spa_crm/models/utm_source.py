# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class UtmSource(models.Model):
    _inherit = 'utm.source'

    spa_team_id = fields.Many2one(
        'crm.team', string='Embudo de destino',
        help='Los prospectos creados con esta fuente y sin equipo (por ejemplo, desde un '
             'formulario web) entran a este embudo.')
