# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


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
    analytic_distribution = fields.Json('Distribución por área',
                                        help='Áreas del negocio del ingreso devengado (se copia del plan al facturar).')
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True, copy=False)
    state = fields.Selection([
        ('planned', 'Programado'),
        ('posted', 'Contabilizado'),
        ('reversed', 'Ingreso revertido'),
        ('cancelled', 'Anulado'),
    ], default='planned', required=True, index=True,
        help='Ingreso revertido: nota de crédito que devolvió meses ya devengados (Debe ingresos / Haber 215100).')
    cancel_reason = fields.Char('Motivo de anulación', readonly=True, copy=False)
    refund_move_id = fields.Many2one('account.move', string='Nota de crédito', readonly=True, copy=False,
                                     help='Nota de crédito que devolvió esta cuota (ya no se puede reconocer).')

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

    def _post_line(self, date=None):
        """Debe 215100 / Haber ingresos (una cuota negativa revierte ingreso ya reconocido)."""
        self.ensure_one()
        income = self._income_account()
        partner = self.membership_id.partner_id
        amount = abs(self.amount)
        positive = self.amount >= 0
        income_vals = {'account_id': income.id, 'debit': 0.0 if positive else amount,
                       'credit': amount if positive else 0.0, 'partner_id': partner.id,
                       'name': self.membership_id.name}
        if self.analytic_distribution:
            income_vals['analytic_distribution'] = self.analytic_distribution
        ref = self.env._('Devengo %(membership)s %(month)s', membership=self.membership_id.name,
                         month=self.date.strftime('%m/%Y')) if positive else \
            self.env._('Reversión de ingreso devengado %(membership)s (nota de crédito)',
                       membership=self.membership_id.name)
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': self._journal().id,
            'date': date or self.date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {'account_id': self.deferred_account_id.id, 'debit': amount if positive else 0.0,
                        'credit': 0.0 if positive else amount, 'partner_id': partner.id,
                        'name': self.membership_id.name}),
                (0, 0, income_vals),
            ],
        })
        move.action_post()
        self.write({'move_id': move.id, 'state': 'posted' if positive else 'reversed'})
        return move

    def action_post(self):
        for line in self.filtered(lambda l: l.state == 'planned'):
            line._post_line()
        return True

    def _spa_cancel(self, reason):
        """Deja de devengar (membresía cancelada, factura anulada o con nota de crédito)."""
        self.filtered(lambda l: l.state == 'planned').sudo().write({'state': 'cancelled', 'cancel_reason': reason})
        return True

    def action_recognize_now(self):
        """Membresía cancelada SIN devolución: el saldo diferido ya no es una obligación y se reconoce como
        ingreso hoy. No usar si se emitió (o se emitirá) una nota de crédito por ese monto."""
        if not (self.env.su or self.env.user.has_group('account.group_account_user')
                or self.env.user.has_group('spa_base.group_spa_manager')):
            raise UserError(self.env._('Solo el contador o el gerente pueden reconocer el ingreso diferido.'))
        today = self.env['spa.tools'].local_today()
        lines = self.filtered(lambda l: l.state == 'cancelled')
        for line in lines:
            if line.refund_move_id or line.invoice_id.payment_state == 'reversed' or line.invoice_id.state != 'posted':
                raise UserError(self.env._(
                    'La factura %s fue revertida o anulada: no hay ingreso diferido que reconocer.',
                    line.invoice_id.display_name))
            line._post_line(date=today)
        return True

    @api.model
    def _cron_post_deferrals(self):
        today = self.env['spa.tools'].local_today()
        # Solo facturas publicadas: una factura restablecida a borrador deja de devengar hasta re-publicarse.
        self.search([('state', '=', 'planned'), ('date', '<=', today),
                     ('invoice_id.state', '=', 'posted')]).action_post()
        return True
