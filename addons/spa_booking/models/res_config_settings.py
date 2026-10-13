# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Sin «default»: así se puede guardar 0 (Odoo borra el parámetro y el código lo lee como 0).
    spa_waitlist_priority_minutes = fields.Integer(
        'Lista de espera: minutos de prioridad',
        config_parameter='spa_booking.waitlist_priority_minutes',
        help='Cuando se libera un cupo se avisa a la primera persona de la lista y se le guarda el cupo '
             'durante estos minutos. 0 = se avisa sin guardar el cupo.')
