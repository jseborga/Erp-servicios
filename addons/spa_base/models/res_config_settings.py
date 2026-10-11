# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    spa_timezone = fields.Char('Zona horaria del spa', default='America/La_Paz', config_parameter='spa.timezone',
                               help='Zona horaria de los horarios de atención y de las franjas.')
