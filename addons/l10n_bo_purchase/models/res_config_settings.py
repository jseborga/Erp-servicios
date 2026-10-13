# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_bo_purchase_check = fields.Boolean(related='company_id.l10n_bo_purchase_check', readonly=False)
    l10n_bo_default_doc_type = fields.Selection(related='company_id.l10n_bo_default_doc_type', readonly=False)
    l10n_bo_default_purchase_type = fields.Selection(related='company_id.l10n_bo_default_purchase_type', readonly=False)
    l10n_bo_cuf_check = fields.Selection(related='company_id.l10n_bo_cuf_check', readonly=False)
    l10n_bo_nodoc_account_id = fields.Many2one(related='company_id.l10n_bo_nodoc_account_id', readonly=False)
    l10n_bo_ret_goods_tax_id = fields.Many2one(related='company_id.l10n_bo_ret_goods_tax_id', readonly=False)
    l10n_bo_ret_services_tax_id = fields.Many2one(related='company_id.l10n_bo_ret_services_tax_id', readonly=False)
    l10n_bo_ret_eventual_tax_id = fields.Many2one(related='company_id.l10n_bo_ret_eventual_tax_id', readonly=False)
    l10n_bo_gu_goods_tax_id = fields.Many2one(related='company_id.l10n_bo_gu_goods_tax_id', readonly=False)
    l10n_bo_gu_services_tax_id = fields.Many2one(related='company_id.l10n_bo_gu_services_tax_id', readonly=False)
    l10n_bo_gu_eventual_tax_id = fields.Many2one(related='company_id.l10n_bo_gu_eventual_tax_id', readonly=False)
