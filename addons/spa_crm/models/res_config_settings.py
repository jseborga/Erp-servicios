# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Los campos enteros sin «default» permiten guardar 0 (= desactivado): Odoo borra el
    # parámetro cuando el valor es 0 y el código lo interpreta como 0.
    spa_crm_courtesy_monthly_limit = fields.Integer(
        'Pases de cortesía por usuario al mes', config_parameter='spa_crm.courtesy_monthly_limit',
        help='0 = sin límite. Los gerentes no tienen límite.')
    spa_crm_courtesy_validity_days = fields.Integer(
        'Vigencia por defecto (días)', default=15, config_parameter='spa_crm.courtesy_validity_days')
    spa_crm_guest_welcome = fields.Boolean(
        'Bienvenida por WhatsApp a invitados', config_parameter='spa_crm.guest_welcome',
        help='Genera el mensaje «Bienvenida a invitados» cuando un socio registra un invitado nuevo.')
    spa_crm_followup_days = fields.Integer(
        'Llamada de seguimiento tras la visita (días)', config_parameter='spa_crm.followup_days',
        help='Programa una actividad de seguimiento N días después de la visita de un invitado o del canje '
             'de una cortesía. 0 = no programar.')
    spa_crm_retention_low_usage_pct = fields.Integer(
        'Uso bajo: menos del (%)', config_parameter='spa_crm.retention_low_usage_pct',
        help='Porcentaje del saldo del mes usado por debajo del cual el socio pasa a «En riesgo». 0 = no evaluar.')
    spa_crm_retention_low_usage_day = fields.Integer(
        'Uso bajo: evaluar desde el día', default=15, config_parameter='spa_crm.retention_low_usage_day',
        help='Día del mes desde el que se evalúa el uso (y antigüedad mínima de la membresía en días).')
    spa_crm_retention_expiry_days = fields.Integer(
        'Por vencer: días antes del vencimiento', config_parameter='spa_crm.retention_expiry_days',
        help='Socios que vencen dentro de estos días sin una factura de renovación abierta. 0 = no evaluar.')
    spa_crm_signup_lead_reception = fields.Boolean(
        'Prospecto también para altas de recepción sin pagar', config_parameter='spa_crm.signup_lead_reception',
        help='Las altas web sin pagar siempre crean (o avanzan) el prospecto en «Propuesta». Active esta opción '
             'para hacer lo mismo con las membresías en borrador que registra el personal; si no, solo se '
             'avanza el prospecto que ya exista.')
    spa_crm_activity_type_id = fields.Many2one(
        'mail.activity.type', string='Tipo de actividad de seguimiento', config_parameter='spa_crm.activity_type_id',
        domain="[('res_model', 'in', (False, 'crm.lead'))]",
        help='Vacío = «Llamada».')
