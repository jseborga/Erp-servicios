# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaService(models.Model):
    _name = 'spa.service'
    _description = 'Servicio del spa'
    _inherit = ['mail.thread']
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char('Servicio', required=True, translate=True, tracking=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    space_id = fields.Many2one('spa.space', string='Espacio', required=True, check_company=True, tracking=True)
    access_mode = fields.Selection(related='space_id.access_mode')
    product_id = fields.Many2one('product.product', string='Producto (precio suelto)', required=True,
                                 domain=[('type', '=', 'service')], tracking=True,
                                 help='Define el precio de la sesión suelta, los impuestos y la cuenta de ingreso.')
    list_price = fields.Float(related='product_id.lst_price', string='Precio suelto', readonly=False)
    duration = fields.Float('Duración (horas)', required=True, default=1.0)
    requires_staff = fields.Boolean('Requiere personal', tracking=True)
    skill_id = fields.Many2one('spa.skill', string='Especialidad requerida')
    seats_per_booking = fields.Integer('Cupos por reserva', default=1, required=True)
    guest_allowed = fields.Boolean('Admite invitados', default=True)
    booking_lead_min = fields.Float('Anticipación mínima (horas)', default=1.0,
                                    help='Tiempo mínimo entre la reserva y el inicio del servicio.')
    booking_lead_max = fields.Integer('Anticipación máxima (días)', default=30)
    description = fields.Text('Descripción para el socio', translate=True)
    active = fields.Boolean(default=True)

    @api.constrains('requires_staff', 'skill_id', 'duration', 'seats_per_booking')
    def _check_service(self):
        for service in self:
            if service.requires_staff and not service.skill_id:
                raise ValidationError(self.env._('Indique la especialidad requerida para %s.', service.name))
            if service.duration <= 0 or service.seats_per_booking <= 0:
                raise ValidationError(self.env._('Duración y cupos de %s deben ser mayores que cero.', service.name))

    def _qualified_employees(self):
        self.ensure_one()
        if not self.requires_staff:
            return self.env['hr.employee']
        return self.env['hr.employee'].search([
            ('spa_skill_ids', 'in', self.skill_id.ids),
            ('company_id', '=', self.company_id.id),
        ])
