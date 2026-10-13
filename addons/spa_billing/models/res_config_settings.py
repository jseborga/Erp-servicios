# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    spa_payment_qr = fields.Binary(related='company_id.spa_payment_qr', readonly=False)
    spa_payment_instructions = fields.Text(related='company_id.spa_payment_instructions', readonly=False)
    spa_bank_account_text = fields.Char(related='company_id.spa_bank_account_text', readonly=False)
    spa_payment_journal_id = fields.Many2one(related='company_id.spa_payment_journal_id', readonly=False)
    spa_cash_journal_id = fields.Many2one(related='company_id.spa_cash_journal_id', readonly=False)
    spa_renewal_days = fields.Integer(related='company_id.spa_renewal_days', readonly=False)
    spa_installment_reminder_days = fields.Integer(related='company_id.spa_installment_reminder_days', readonly=False)
    spa_installment_suspend_days = fields.Integer(related='company_id.spa_installment_suspend_days', readonly=False)
