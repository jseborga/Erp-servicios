# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    spa_invoice_kind = fields.Selection(
        selection_add=[('pos', 'Consumo restaurante/cafetería')],
        ondelete={'pos': 'set null'},
    )
