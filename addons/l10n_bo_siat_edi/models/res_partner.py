# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

from .l10n_bo_siat_catalog import BUYER_DOC_TYPES


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_bo_siat_id_type = fields.Selection(
        BUYER_DOC_TYPES, string='Tipo de documento (SIAT)',
        help='Tipo del documento indicado en NIT/CI para las facturas de venta. Vacío: NIT si el contacto tiene '
             'número; si no, el "consumidor final" de la compañía.')
    l10n_bo_siat_id_complement = fields.Char(
        string='Complemento del CI',
        help='Complemento de la cédula de identidad (por ejemplo 1F) cuando el SEGIP lo asignó por duplicidad. '
             'El SIAT solo lo admite con tipo de documento CI.')
