# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class SpaDeferralLine(models.Model):
    """Cuota mensual de ingreso diferido que pasa de 215100 a ingresos por membresías."""
    _name = 'spa.deferral.line'
    _description = 'Devengo mensual de membresía'
    _order = 'date, id'

    membership_id = fields.Many2one('spa.membership', required=True, ondelete='cascade', index=True)
    invoice_id = fields.Many2one('account.move', string='Factura', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='membership_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date('Mes', required=True, index=True)
    amount = fields.Monetary('Monto', required=True)
    deferred_account_id = fields.Many2one('account.account', string='Cuenta diferida', required=True)
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True, copy=False)
    state = fields.Selection([('planned', 'Programado'), ('posted', 'Contabilizado')], default='planned',
                             required=True, index=True)

    def _income_account(self):
        self.ensure_one()
        categ = self.env.ref('l10n_bo_spa.categ_membership_monthly', raise_if_not_found=False)
        return categ.with_company(self.company_id).property_account_income_categ_id if categ else False

    def _journal(self):
        self.ensure_one()
        chart = self.env['account.chart.template'].with_company(self.company_id)
        return chart.ref('l10n_bo_spa_journal_deferred', raise_if_not_found=False) or \
            self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', self.company_id.id)],
                                               limit=1)

    def action_post(self):
        for line in self.filtered(lambda l: l.state == 'planned'):
            income = line._income_account()
            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': line._journal().id,
                'date': line.date,
                'ref': self.env._('Devengo %(membership)s %(month)s', membership=line.membership_id.name,
                                  month=line.date.strftime('%m/%Y')),
                'company_id': line.company_id.id,
                'line_ids': [
                    (0, 0, {'account_id': line.deferred_account_id.id, 'debit': line.amount, 'credit': 0.0,
                            'partner_id': line.membership_id.partner_id.id, 'name': line.membership_id.name}),
                    (0, 0, {'account_id': income.id, 'debit': 0.0, 'credit': line.amount,
                            'partner_id': line.membership_id.partner_id.id, 'name': line.membership_id.name}),
                ],
            })
            move.action_post()
            line.write({'move_id': move.id, 'state': 'posted'})
        return True

    @api.model
    def _cron_post_deferrals(self):
        today = self.env['spa.tools'].local_today()
        self.search([('state', '=', 'planned'), ('date', '<=', today)]).action_post()
        return True
