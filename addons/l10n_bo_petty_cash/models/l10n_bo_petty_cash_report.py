# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .l10n_bo_petty_cash_fund import ACCOUNTANT_GROUP


class L10nBoPettyCashReport(models.Model):
    """Rendición de un fondo fijo: comprobantes del período + arqueo de efectivo.

    Al aprobarla (contador) cada comprobante se registra como factura de proveedor pagada
    desde el diario del fondo y se publica UN asiento de reposición desde el banco que,
    junto con la diferencia de arqueo, devuelve la cuenta del fondo a su monto fijo.
    """
    _name = 'l10n_bo.petty.cash.report'
    _description = 'Rendición de fondo fijo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Número', readonly=True, copy=False, default='/')
    fund_id = fields.Many2one('l10n_bo.petty.cash.fund', string='Fondo fijo', required=True, index=True,
                              ondelete='restrict', check_company=True, domain="[('state', '=', 'open')]",
                              default=lambda self: self.env['l10n_bo.petty.cash.voucher']._default_fund())
    company_id = fields.Many2one(related='fund_id.company_id', store=True, index=True, precompute=True)
    currency_id = fields.Many2one(related='fund_id.currency_id')
    custodian_id = fields.Many2one(related='fund_id.custodian_id', store=True, string='Custodio')
    date = fields.Date(string='Fecha de rendición', required=True, default=fields.Date.context_today)
    state = fields.Selection(
        [('draft', 'Borrador'), ('submitted', 'Enviada'), ('approved', 'Aprobada y repuesta')],
        string='Estado', default='draft', required=True, tracking=True, copy=False)
    voucher_ids = fields.One2many('l10n_bo.petty.cash.voucher', 'report_id', string='Comprobantes')
    amount_fixed = fields.Monetary(string='Monto fijo', compute='_compute_amount_fixed', store=True)
    amount_paid = fields.Monetary(string='Gastos rendidos (efectivo pagado)', compute='_compute_amounts', store=True)
    cash_counted = fields.Monetary(string='Efectivo contado (arqueo)', tracking=True)
    cash_expected = fields.Monetary(string='Efectivo esperado', compute='_compute_amounts', store=True)
    difference = fields.Monetary(
        string='Diferencia de arqueo', compute='_compute_amounts', store=True,
        help='Efectivo contado − (monto fijo − gastos rendidos). Negativo = faltante; positivo = sobrante.')
    replenish_amount = fields.Monetary(string='Reposición desde el banco', readonly=True, copy=False)
    replenish_move_id = fields.Many2one('account.move', string='Asiento de reposición', readonly=True, copy=False)
    bill_ids = fields.Many2many('account.move', string='Facturas', compute='_compute_bill_ids',
                                groups='account.group_account_invoice,account.group_account_readonly')
    bill_count = fields.Integer(compute='_compute_bill_count')
    approved_by_id = fields.Many2one('res.users', string='Aprobada por', readonly=True, copy=False)
    approval_date = fields.Date(string='Fecha de aprobación', readonly=True, copy=False)
    note = fields.Text(string='Observaciones')

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    @api.depends('fund_id.amount_fixed', 'state')
    def _compute_amount_fixed(self):
        for report in self:
            if report.state != 'approved' or not report.amount_fixed:
                report.amount_fixed = report.fund_id.amount_fixed
            else:
                report.amount_fixed = report.amount_fixed

    @api.depends('voucher_ids.amount_paid', 'voucher_ids.state', 'cash_counted', 'amount_fixed')
    def _compute_amounts(self):
        for report in self:
            paid = sum(report.voucher_ids.filtered(lambda v: v.state != 'cancel').mapped('amount_paid'))
            report.amount_paid = paid
            report.cash_expected = report.amount_fixed - paid
            report.difference = report.cash_counted - report.cash_expected

    def _compute_bill_ids(self):
        for report in self:
            report.bill_ids = report.voucher_ids.move_id

    def _compute_bill_count(self):
        for report in self:
            report.bill_count = len(report.sudo().voucher_ids.move_id)

    @api.constrains('fund_id', 'state')
    def _check_one_open_report(self):
        for report in self:
            others = self.search_count([
                ('fund_id', '=', report.fund_id.id), ('state', '!=', 'approved'), ('id', '!=', report.id),
            ])
            if report.state != 'approved' and others:
                raise ValidationError(self.env._(
                    'El fondo %s ya tiene una rendición pendiente: complétela antes de crear otra.', report.fund_id.name))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('l10n_bo.petty.cash.report') or '/'
        reports = super().create(vals_list)
        reports._load_vouchers()
        return reports

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda r: r.state != 'draft'):
            raise UserError(self.env._('Solo se pueden eliminar rendiciones en borrador.'))

    def _load_vouchers(self):
        """Incluye en la rendición todos los comprobantes en borrador del fondo."""
        for report in self.filtered(lambda r: r.state == 'draft'):
            pending = self.env['l10n_bo.petty.cash.voucher'].search([
                ('fund_id', '=', report.fund_id.id), ('state', '=', 'draft'),
                '|', ('report_id', '=', False), ('report_id', '=', report.id),
            ])
            pending.with_context(l10n_bo_petty_cash_internal=True).report_id = report

    # ------------------------------------------------------------------
    # Flujo
    # ------------------------------------------------------------------
    def _check_accountant(self):
        if not self.env.su and not self.env.user.has_group(ACCOUNTANT_GROUP):
            raise AccessError(self.env._('Solo el contador puede aprobar o devolver rendiciones de fondo fijo.'))

    def action_load_vouchers(self):
        self._load_vouchers()
        return True

    def action_submit(self):
        for report in self:
            if report.state != 'draft':
                raise UserError(self.env._('La rendición %s ya fue enviada.', report.name))
            report._load_vouchers()
            vouchers = report.voucher_ids.filtered(lambda v: v.state == 'draft')
            problems = []
            for voucher in vouchers:
                errors = voucher._submission_errors()
                duplicates = voucher._l10n_bo_find_duplicates()
                if duplicates:
                    errors.append(self.env._('documento ya registrado (%s)', '; '.join(duplicates)))
                if errors:
                    problems.append('%s - %s: %s' % (voucher.name, voucher.description, '; '.join(errors)))
            if problems:
                raise UserError(self.env._(
                    'Complete los comprobantes antes de enviar la rendición:\n%s',
                    '\n'.join('• %s' % p for p in problems)))
            vouchers.with_context(l10n_bo_petty_cash_internal=True).write({'state': 'reported'})
            report.state = 'submitted'
            report.message_post(body=self.env._(
                'Rendición enviada: %(count)s comprobantes por %(amount)s; efectivo contado %(cash)s; diferencia %(diff)s.',
                count=len(vouchers), amount=report.amount_paid, cash=report.cash_counted, diff=report.difference))
        return True

    def action_reset_draft(self):
        for report in self:
            if report.state != 'submitted':
                raise UserError(self.env._('Solo se devuelven a borrador rendiciones enviadas.'))
            report.voucher_ids.filtered(lambda v: v.state == 'reported').with_context(
                l10n_bo_petty_cash_internal=True).write({'state': 'draft'})
            report.state = 'draft'
        return True

    def action_approve(self):
        self._check_accountant()
        for report in self:
            if report.state != 'submitted':
                raise UserError(self.env._('Solo se aprueban rendiciones enviadas por el custodio.'))
            fund = report.fund_id
            if fund.state != 'open':
                raise UserError(self.env._('El fondo %s no está abierto.', fund.name))
            fund._check_config()
            for voucher in report.voucher_ids.filtered(lambda v: v.state == 'reported'):
                voucher._create_bill_and_pay()
            report._post_replenishment()
            report.write({
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approval_date': fields.Date.context_today(self),
            })
        return True

    def _post_replenishment(self):
        """Un asiento: Debe fondo (lo necesario para volver al monto fijo) / Haber banco
        (reposición) y la diferencia de arqueo contra cuenta por cobrar al custodio,
        faltantes o sobrantes de caja."""
        self.ensure_one()
        fund = self.fund_id
        currency = fund.currency_id
        to_fixed = currency.round(fund.amount_fixed - fund._get_account_balance())
        difference = currency.round(self.difference)
        replenish = currency.round(to_fixed - difference)
        label = self.env._('Reposición del fondo fijo %(fund)s - %(report)s', fund=fund.name, report=self.name)
        lines = []
        if not currency.is_zero(to_fixed):
            lines.append({'account_id': fund.account_id.id, 'balance': to_fixed})
        if not currency.is_zero(replenish):
            lines.append({'account_id': fund.bank_journal_id.default_account_id.id, 'balance': -replenish})
        if difference < 0 and not currency.is_zero(difference):
            if fund.shortage_policy == 'custodian':
                account = fund.shortage_receivable_account_id
                partner = fund.custodian_partner_id
            else:
                account = fund.shortage_expense_account_id
                partner = self.env['res.partner']
            if not account:
                raise UserError(self.env._('Configure la cuenta de faltantes en el fondo %s.', fund.name))
            lines.append({
                'account_id': account.id, 'balance': -difference, 'partner_id': partner.id or False,
                'name': self.env._('Faltante de caja - %(fund)s - %(report)s', fund=fund.name, report=self.name),
            })
        elif difference > 0 and not currency.is_zero(difference):
            if not fund.surplus_account_id:
                raise UserError(self.env._('Configure la cuenta de sobrantes en el fondo %s.', fund.name))
            lines.append({
                'account_id': fund.surplus_account_id.id, 'balance': -difference,
                'name': self.env._('Sobrante de caja - %(fund)s - %(report)s', fund=fund.name, report=self.name),
            })
        if not lines:
            return self.env['account.move']
        move = fund._post_entry(label, lines, date=fields.Date.context_today(self))
        self.write({'replenish_move_id': move.id, 'replenish_amount': replenish})
        return move

    def action_view_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Facturas de la rendición'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.voucher_ids.move_id.ids)],
            'context': {'create': False},
        }
