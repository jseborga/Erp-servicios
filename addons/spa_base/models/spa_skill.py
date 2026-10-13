# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class SpaSkill(models.Model):
    _name = 'spa.skill'
    _description = 'Especialidad del personal'
    _order = 'name'

    name = fields.Char('Especialidad', required=True, translate=True)
    employee_ids = fields.Many2many('hr.employee', string='Personal', relation='hr_employee_spa_skill_rel',
                                    column1='skill_id', column2='employee_id')
    active = fields.Boolean(default=True, string='Activo')

    _name_uniq = models.Constraint('UNIQUE (name)', 'Ya existe una especialidad con ese nombre.')
