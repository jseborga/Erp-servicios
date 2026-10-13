# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class L10nBoSiatCancelReason(models.Model):
    """Motivo de anulación (paramétrica "Motivo de anulación" del SIAT).

    Los registros iniciales son los códigos conocidos de la paramétrica; NO se pudieron verificar
    con la lista oficial vigente. Si el proveedor o el SIN informan otros, edítelos aquí.
    """
    _name = 'l10n_bo.siat.cancel.reason'
    _description = 'Motivo de anulación SIAT'
    _order = 'sequence, code'

    code = fields.Integer(string='Código SIN', required=True)
    name = fields.Char(string='Descripción', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, string='Activo')
    note = fields.Char(string='Cuándo usarlo')

    _code_unique = models.Constraint('UNIQUE (code)', 'Ya existe un motivo de anulación con ese código.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for reason in self:
            reason.display_name = '%s - %s' % (reason.code, reason.name)
