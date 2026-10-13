# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models

SIAT_MODE_FIELDS = ('l10n_bo_siat_mode', 'l10n_bo_siat_provider_id')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_bo_siat_mode = fields.Selection(related='company_id.l10n_bo_siat_mode', readonly=False)
    l10n_bo_siat_provider_id = fields.Many2one(related='company_id.l10n_bo_siat_provider_id', readonly=False)
    l10n_bo_siat_user_id = fields.Many2one(related='company_id.l10n_bo_siat_user_id', readonly=False)
    l10n_bo_siat_cuf_check = fields.Selection(related='company_id.l10n_bo_siat_cuf_check', readonly=False)
    l10n_bo_siat_buyer_doc_type = fields.Selection(related='company_id.l10n_bo_siat_buyer_doc_type', readonly=False)
    l10n_bo_siat_buyer_number = fields.Char(related='company_id.l10n_bo_siat_buyer_number', readonly=False)
    l10n_bo_siat_buyer_name = fields.Char(related='company_id.l10n_bo_siat_buyer_name', readonly=False)
    l10n_bo_siat_anonymous_max = fields.Monetary(related='company_id.l10n_bo_siat_anonymous_max', readonly=False)
    l10n_bo_siat_cancel_day = fields.Integer(related='company_id.l10n_bo_siat_cancel_day', readonly=False)
    l10n_bo_siat_retry_limit = fields.Integer(related='company_id.l10n_bo_siat_retry_limit', readonly=False)
    l10n_bo_sale_no_invoice_max = fields.Monetary(related='company_id.l10n_bo_sale_no_invoice_max', readonly=False)
    l10n_bo_siat_warning = fields.Text(related='company_id.l10n_bo_siat_warning')

    @api.model_create_multi
    def create(self, vals_list):
        """Valida la modalidad solo cuando el usuario la cambia (Ajustes no reescribe valores sin
        cambios), para no impedir guardar otros ajustes de una compañía aún sin NIT."""
        company = self.env.company
        before = {fname: company[fname] for fname in SIAT_MODE_FIELDS}
        settings = super().create(vals_list)
        for record in settings:
            target = record.company_id
            if target == company and any(target[fname] != before[fname] for fname in SIAT_MODE_FIELDS):
                target._l10n_bo_siat_check_mode_requirements()
        return settings
