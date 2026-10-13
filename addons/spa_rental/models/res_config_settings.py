# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    spa_rental_weeks_ahead = fields.Integer(
        'Generar sesiones con (semanas)', default=5, config_parameter='spa_rental.class_weeks_ahead',
        help='Semanas hacia adelante para las que el proceso diario crea las sesiones de clase. '
             'Conviene que sea mayor que la anticipación máxima de reservas para que la clase '
             'reserve su cupo antes que los socios.')
    spa_rental_reminder_hours = fields.Integer(
        'Recordatorio del evento (horas antes)', default=24, config_parameter='spa_rental.reminder_hours',
        help='Genera el WhatsApp «Recordatorio de evento» este número de horas antes del inicio. 0 = no enviar.')
    spa_rental_class_cancel_hours = fields.Integer(
        'Cancelar inscripción sin cargo (horas antes)', default=2, config_parameter='spa_rental.class_cancel_hours',
        help='Si el alumno cancela con esta anticipación se devuelve la sesión (saldo del plan o factura). '
             'Más tarde la sesión se considera usada.')
    spa_rental_checkin_minutes = fields.Integer(
        'Ingreso a clase desde (minutos antes)', default=30, config_parameter='spa_rental.class_checkin_minutes',
        help='Minutos antes del inicio en que el alumno puede registrar su ingreso con el QR.')
    spa_rental_deposit_account_id = fields.Many2one(
        related='company_id.spa_rental_deposit_account_id', readonly=False)
    spa_rental_analytic_id = fields.Many2one(related='company_id.spa_rental_analytic_id', readonly=False)
    spa_rental_damage_product_id = fields.Many2one(related='company_id.spa_rental_damage_product_id', readonly=False)
    spa_rental_team_id = fields.Many2one(related='company_id.spa_rental_team_id', readonly=False)
