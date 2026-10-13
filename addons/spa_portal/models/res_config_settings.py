# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

DEFAULT_BOOKING_DAYS = 14
DEFAULT_RECEIPT_MAX_MB = 5.0


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    spa_portal_booking_days = fields.Integer(
        'Días visibles para reservar en la web', config_parameter='spa_portal.booking_days',
        default=DEFAULT_BOOKING_DAYS,
        help='Cuántos días hacia adelante ve el socio al reservar o registrar invitados desde la web.')
    spa_portal_receipt_max_mb = fields.Float(
        'Tamaño máximo del comprobante (MB)', config_parameter='spa_portal.receipt_max_mb',
        default=DEFAULT_RECEIPT_MAX_MB,
        help='Límite del archivo (imagen o PDF) que el socio sube como comprobante de pago.')
