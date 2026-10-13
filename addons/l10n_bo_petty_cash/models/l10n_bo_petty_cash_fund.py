# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

ACCOUNTANT_GROUP = 'l10n_bo_purchase.group_spa_accountant'
FUND_ACCOUNT_XMLIDS = ('l10n_bo_spa_11121', 'l10n_bo_spa_11122', 'l10n_bo_spa_11123')


class L10nBoPettyCashFund(models.Model):
    """Fondo fijo (caja chica) con sistema imprest: la cuenta del fondo siempre vuelve a su
    monto fijo después de cada rendición y reposición."""
    _name = 'l10n_bo.petty.cash.fund'
    _description = 'Fondo fijo (caja chica)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection(
        [('draft', 'Borrador'), ('open', 'Abierto'), ('closed', 'Cerrado')],
        string='Estado', default='draft', required=True, tracking=True, copy=False)
    custodian_id = fields.Many2one(
        'res.users', string='Custodio', required=True, tracking=True, domain=[('share', '=', False)],
        help='Responsable del efectivo. Solo él (y el contador) ve el fondo y registra sus gastos.')
    custodian_employee_id = fields.Many2one('hr.employee', string='Empleado custodio',
                                            compute='_compute_custodian_partner')
    custodian_partner_id = fields.Many2one('res.partner', string='Contacto del custodio',
                                           compute='_compute_custodian_partner')
    amount_fixed = fields.Monetary(string='Monto fijo', required=True, tracking=True, copy=False)
    max_expense = fields.Monetary(
        string='Tope por gasto', tracking=True,
        help='Importe máximo de un comprobante. 0 = sin tope.')
    require_receipt = fields.Boolean(
        string='Exigir foto del comprobante', default=True,
        help='La rendición no se puede enviar si algún comprobante no tiene foto.')
    account_id = fields.Many2one(
        'account.account', string='Cuenta del fondo', required=True, check_company=True, tracking=True,
        domain="[('account_type', '=', 'asset_cash')]", default=lambda self: self._default_account_id(),
        help='Cuenta de efectivo del fondo (111210, 111220, 111230…). Una cuenta por fondo.')
    journal_id = fields.Many2one(
        'account.journal', string='Diario de caja del fondo', readonly=True, copy=False, check_company=True,
        help='Diario de efectivo creado para el fondo: los gastos aprobados se pagan desde aquí.')
    bank_journal_id = fields.Many2one(
        'account.journal', string='Banco de origen', required=True, check_company=True,
        domain="[('type', '=', 'bank')]", default=lambda self: self._default_journal('bank'),
        help='Banco desde el que se entrega y repone el fondo.')
    entry_journal_id = fields.Many2one(
        'account.journal', string='Diario de asientos', required=True, check_company=True,
        domain="[('type', '=', 'general')]", default=lambda self: self._default_entry_journal(),
        help='Diario de los asientos de apertura, reposición y ajuste (por defecto FFIJ).')
    purchase_journal_id = fields.Many2one(
        'account.journal', string='Diario de compras', check_company=True,
        domain="[('type', '=', 'purchase')]", default=lambda self: self._default_journal('purchase'),
        help='Diario donde se registran las facturas de los gastos aprobados.')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Área analítica',
        help='Área por defecto de los gastos del fondo.')
    allowed_account_ids = fields.Many2many(
        'account.account', string='Cuentas de gasto permitidas', check_company=True,
        help='Si se indica, los comprobantes solo pueden usar estas cuentas de gasto.')
    shortage_policy = fields.Selection(
        [('custodian', 'Cobrar al custodio (cuenta por cobrar al personal)'),
         ('company', 'Asume la empresa (faltantes de caja)')],
        string='Faltantes de caja', default='custodian', required=True, tracking=True)
    shortage_receivable_account_id = fields.Many2one(
        'account.account', string='Cuenta por cobrar al custodio', check_company=True,
        default=lambda self: self._chart_ref('l10n_bo_spa_11221'))
    shortage_expense_account_id = fields.Many2one(
        'account.account', string='Cuenta de faltantes', check_company=True,
        default=lambda self: self._chart_ref('l10n_bo_spa_5607'))
    surplus_account_id = fields.Many2one(
        'account.account', string='Cuenta de sobrantes', check_company=True,
        default=lambda self: self._chart_ref('l10n_bo_spa_43041'))
    voucher_ids = fields.One2many('l10n_bo.petty.cash.voucher', 'fund_id', string='Comprobantes')
    report_ids = fields.One2many('l10n_bo.petty.cash.report', 'fund_id', string='Rendiciones')
    move_ids = fields.One2many('account.move', 'l10n_bo_petty_cash_fund_id', string='Asientos y facturas')
    opening_move_id = fields.Many2one('account.move', string='Asiento de apertura', readonly=True, copy=False)
    balance = fields.Monetary(string='Saldo contable', compute='_compute_balance')
    pending_amount = fields.Monetary(string='Gastos por rendir', compute='_compute_pending')
    cash_expected = fields.Monetary(string='Efectivo esperado', compute='_compute_pending')
    voucher_count = fields.Integer(compute='_compute_counts')
    report_count = fields.Integer(compute='_compute_counts')
    move_count = fields.Integer(compute='_compute_counts')

    _account_unique = models.Constraint(
        'UNIQUE (company_id, account_id)', 'Cada fondo fijo debe tener su propia cuenta contable.')
    _amount_positive = models.Constraint(
        'CHECK (amount_fixed > 0)', 'El monto fijo del fondo debe ser mayor que cero.')

    # ------------------------------------------------------------------
    # Valores por defecto
    # ------------------------------------------------------------------
    @api.model
    def _chart_ref(self, xmlid):
        return self.env['account.chart.template'].ref(xmlid, raise_if_not_found=False)

    @api.model
    def _default_account_id(self):
        used = self.with_context(active_test=False).search([('company_id', '=', self.env.company.id)]).account_id
        for xmlid in FUND_ACCOUNT_XMLIDS:
            account = self._chart_ref(xmlid)
            if account and account not in used:
                return account
        return self.env['account.account']

    @api.model
    def _default_journal(self, journal_type):
        return self.env['account.journal'].search([
            ('type', '=', journal_type), ('company_id', '=', self.env.company.id),
        ], limit=1)

    @api.model
    def _default_entry_journal(self):
        return self._chart_ref('l10n_bo_spa_journal_petty_cash') or self._default_journal('general')

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    @api.depends('custodian_id')
    def _compute_custodian_partner(self):
        for fund in self:
            employee = fund.custodian_id.sudo().employee_ids.filtered(lambda e: e.company_id == fund.company_id)[:1]
            fund.custodian_employee_id = employee
            fund.custodian_partner_id = employee.work_contact_id or fund.custodian_id.partner_id

    def _get_account_balance(self):
        self.ensure_one()
        if not self.account_id:
            return 0.0
        result = self.env['account.move.line'].sudo()._read_group(
            [('account_id', '=', self.account_id.id), ('company_id', '=', self.company_id.id),
             ('parent_state', '=', 'posted')],
            [], ['balance:sum'])
        return result[0][0] or 0.0

    def _compute_balance(self):
        for fund in self:
            fund.balance = fund._get_account_balance()

    @api.depends('voucher_ids.state', 'voucher_ids.amount_paid', 'amount_fixed')
    def _compute_pending(self):
        for fund in self:
            pending = fund.voucher_ids.filtered(lambda v: v.state in ('draft', 'reported'))
            fund.pending_amount = sum(pending.mapped('amount_paid'))
            fund.cash_expected = fund.amount_fixed - fund.pending_amount

    def _compute_counts(self):
        for fund in self:
            fund.voucher_count = len(fund.voucher_ids)
            fund.report_count = len(fund.report_ids)
            fund.move_count = len(fund.sudo().move_ids)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        funds = super().create(vals_list)
        funds._create_cash_journal()
        return funds

    def write(self, vals):
        if 'account_id' in vals and self.filtered(lambda f: f.state != 'draft'):
            raise UserError(self.env._(
                'No se puede cambiar la cuenta de un fondo abierto o cerrado. Cierre el fondo y cree uno nuevo.'))
        if 'amount_fixed' in vals and not self.env.context.get('l10n_bo_petty_cash_amount_change'):
            if self.filtered(lambda f: f.state != 'draft'):
                raise UserError(self.env._(
                    'Para cambiar el monto fijo de un fondo abierto use el botón "Cambiar monto": '
                    'así se registra el asiento de ajuste contra el banco.'))
        res = super().write(vals)
        if 'account_id' in vals:
            self._sync_journal_account()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda f: f.state != 'draft' or f.voucher_ids):
            raise UserError(self.env._('Solo se pueden eliminar fondos en borrador y sin comprobantes. Archive o cierre el fondo.'))

    def _next_journal_code(self):
        self.ensure_one()
        Journal = self.env['account.journal'].sudo().with_context(active_test=False)
        codes = set(Journal.search([('company_id', '=', self.company_id.id)]).mapped('code'))
        number = 1
        while 'FF%d' % number in codes:
            number += 1
        return 'FF%d' % number

    def _create_cash_journal(self):
        for fund in self.filtered(lambda f: not f.journal_id):
            journal = self.env['account.journal'].sudo().create({
                'name': self.env._('Fondo fijo - %s', fund.name),
                'code': fund._next_journal_code(),
                'type': 'cash',
                'company_id': fund.company_id.id,
                'default_account_id': fund.account_id.id,
                'show_on_dashboard': False,
            })
            fund.sudo().journal_id = journal
            fund._sync_journal_account()

    def _sync_journal_account(self):
        """El diario del fondo paga directamente contra la cuenta del fondo (sin cuenta de
        pagos pendientes): Debe proveedor / Haber 1112x0."""
        for fund in self.filtered('journal_id'):
            journal = fund.journal_id.sudo()
            journal.default_account_id = fund.account_id
            (journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids).write({
                'payment_account_id': fund.account_id.id,
            })

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _check_accountant(self):
        if not self.env.su and not self.env.user.has_group(ACCOUNTANT_GROUP):
            raise AccessError(self.env._('Solo el contador puede realizar esta operación del fondo fijo.'))

    def _check_config(self):
        self.ensure_one()
        missing = []
        if not self.bank_journal_id.default_account_id:
            missing.append(self.env._('el banco de origen (con cuenta contable)'))
        if not self.entry_journal_id:
            missing.append(self.env._('el diario de asientos'))
        if not self.journal_id:
            missing.append(self.env._('el diario de caja del fondo'))
        if missing:
            raise UserError(self.env._('Configure %(missing)s en el fondo %(fund)s.',
                                       missing=', '.join(missing), fund=self.name))

    def _post_entry(self, label, lines, date=None):
        """Crea y publica un asiento del fondo en el diario de asientos (FFIJ)."""
        self.ensure_one()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.entry_journal_id.id,
            'date': date or fields.Date.context_today(self),
            'ref': label,
            'l10n_bo_petty_cash_fund_id': self.id,
            'line_ids': [Command.create(dict(line, name=line.get('name') or label)) for line in lines],
        })
        move.action_post()
        return move

    def _transfer_lines(self, amount):
        """Debe fondo / Haber banco por ``amount`` (negativo: al revés)."""
        self.ensure_one()
        return [
            {'account_id': self.account_id.id, 'balance': amount},
            {'account_id': self.bank_journal_id.default_account_id.id, 'balance': -amount},
        ]

    def action_open(self):
        self._check_accountant()
        for fund in self:
            if fund.state != 'draft':
                raise UserError(self.env._('El fondo %s ya está abierto o cerrado.', fund.name))
            fund._check_config()
            move = fund._post_entry(self.env._('Apertura del fondo fijo %s', fund.name),
                                    fund._transfer_lines(fund.amount_fixed))
            fund.write({'state': 'open', 'opening_move_id': move.id})
            fund.message_post(body=self.env._('Fondo abierto con %(amount)s (asiento %(move)s).',
                                               amount=fund.amount_fixed, move=move.name))
        return True

    def _change_amount(self, new_amount, date=None, reason=None):
        self.ensure_one()
        self._check_accountant()
        if self.state != 'open':
            raise UserError(self.env._('Solo se puede cambiar el monto de un fondo abierto.'))
        if new_amount <= 0:
            raise ValidationError(self.env._('El nuevo monto fijo debe ser mayor que cero.'))
        delta = new_amount - self.amount_fixed
        if self.currency_id.is_zero(delta):
            return self.env['account.move']
        label = self.env._('Cambio de monto del fondo fijo %(fund)s: %(old)s → %(new)s',
                           fund=self.name, old=self.amount_fixed, new=new_amount)
        if reason:
            label = '%s (%s)' % (label, reason)
        move = self._post_entry(label, self._transfer_lines(delta), date=date)
        self.with_context(l10n_bo_petty_cash_amount_change=True).amount_fixed = new_amount
        self.message_post(body=label)
        return move

    def action_change_amount(self):
        self.ensure_one()
        self._check_accountant()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cambiar monto del fondo'),
            'res_model': 'l10n_bo.petty.cash.amount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_fund_id': self.id, 'default_new_amount': self.amount_fixed},
        }

    def action_close(self):
        self._check_accountant()
        for fund in self:
            if fund.state != 'open':
                raise UserError(self.env._('Solo se puede cerrar un fondo abierto.'))
            if fund.voucher_ids.filtered(lambda v: v.state in ('draft', 'reported')):
                raise UserError(self.env._(
                    'El fondo %s tiene comprobantes sin rendir: apruebe o anule la rendición antes de cerrarlo.', fund.name))
            balance = fund._get_account_balance()
            if not fund.currency_id.is_zero(balance):
                fund._post_entry(self.env._('Cierre del fondo fijo %s: devolución al banco', fund.name),
                                 fund._transfer_lines(-balance))
            fund.state = 'closed'
        return True

    # ------------------------------------------------------------------
    # Botones inteligentes
    # ------------------------------------------------------------------
    def action_view_vouchers(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('l10n_bo_petty_cash.l10n_bo_petty_cash_voucher_action')
        action['domain'] = [('fund_id', '=', self.id)]
        action['context'] = {'default_fund_id': self.id}
        return action

    def action_view_reports(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('l10n_bo_petty_cash.l10n_bo_petty_cash_report_action')
        action['domain'] = [('fund_id', '=', self.id)]
        action['context'] = {'default_fund_id': self.id}
        return action

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Asientos y facturas del fondo'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('l10n_bo_petty_cash_fund_id', '=', self.id)],
            'context': {'create': False},
        }
