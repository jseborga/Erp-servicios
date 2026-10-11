# Part of ERP Servicios Spa. License LGPL-3.
import pytz

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    spa_skill_ids = fields.Many2many('spa.skill', string='Especialidades del spa',
                                     relation='hr_employee_spa_skill_rel',
                                     column1='employee_id', column2='skill_id')

    def _spa_is_working(self, start_utc, stop_utc):
        """True si el turno (calendario de trabajo) del empleado cubre todo el intervalo."""
        self.ensure_one()
        calendar = self.resource_calendar_id or self.company_id.resource_calendar_id
        if not calendar:
            return True
        start = pytz.utc.localize(start_utc)
        stop = pytz.utc.localize(stop_utc)
        intervals = calendar._work_intervals_batch(start, stop, resources=self.resource_id)[self.resource_id.id]
        covered = sum((i_stop - i_start).total_seconds() for i_start, i_stop, _rec in intervals)
        return covered + 1 >= (stop - start).total_seconds()
