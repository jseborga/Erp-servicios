# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

from .spa_message import PROVIDERS


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    spa_messaging_provider = fields.Selection(PROVIDERS, string='Proveedor de WhatsApp', default='wa_link',
                                              config_parameter='spa_messaging.provider')
    spa_messaging_country_code = fields.Char('Código de país', default='591',
                                             config_parameter='spa_messaging.country_code')
    spa_messaging_meta_token = fields.Char('Token de acceso (Meta)', config_parameter='spa_messaging.meta_token')
    spa_messaging_meta_phone_id = fields.Char('Phone Number ID (Meta)', config_parameter='spa_messaging.meta_phone_id')
