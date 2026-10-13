# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .l10n_bo_petty_cash_fund import ACCOUNTANT_GROUP

# Campos de negocio que no cambian fuera del borrador (el contador puede corregirlos
# mientras la rendición está enviada y aún no aprobada).
PROTECTED_FIELDS = {
    'fund_id', 'date', 'partner_id', 'supplier_name', 'description', 'amount', 'product_id',
    'account_id', 'tax_ids', 'analytic_distribution', 'receipt', 'receipt_filename',
    'l10n_bo_doc_type', 'l10n_bo_supplier_nit', 'l10n_bo_invoice_number', 'l10n_bo_cuf',
    'l10n_bo_auth_number', 'l10n_bo_control_code', 'l10n_bo_purchase_type',
    'l10n_bo_withholding_mode', 'l10n_bo_purchase_kind',
}


class L10nBoPettyCashVoucher(models.Model):
    """Gasto pagado con el fondo fijo. No genera asientos mientras está en borrador: la
    factura de proveedor y el pago se crean al aprobar la rendición."""
    _name = 'l10n_bo.petty.cash.voucher'
    _description = 'Comprobante de gasto de fondo fijo'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin', 'l10n_bo.fiscal.document.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Número', readonly=True, copy=False, default='/')
    fund_id = fields.Many2one(
        'l10n_bo.petty.cash.fund', string='Fondo fijo', required=True, index=True, ondelete='restrict',
        check_company=True, domain="[('state', '=', 'open')]", default=lambda self: self._default_fund())
    company_id = fields.Many2one(related='fund_id.company_id', store=True, index=True, precompute=True)
    currency_id = fields.Many2one(related='fund_id.currency_id')
    custodian_id = fields.Many2one(related='fund_id.custodian_id', store=True, string='Custodio')
    report_id = fields.Many2one('l10n_bo.petty.cash.report', string='Rendición', readonly=True, copy=False,
                                index='btree_not_null', ondelete='set null')
    state = fields.Selection(
        [('draft', 'Borrador'), ('reported', 'En rendición'), ('posted', 'Contabilizado'), ('cancel', 'Anulado')],
        string='Estado', default='draft', required=True, tracking=True, copy=False)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Proveedor', tracking=True,
                                 help='Proveedor registrado. Si no existe, escriba el nombre y el NIT: '
                                      'el contacto se crea al aprobar la rendición.')
    supplier_name = fields.Char(string='Nombre del proveedor')
    description = fields.Char(string='Concepto', required=True)
    amount = fields.Monetary(
        string='Importe del documento', required=True, tracking=True,
        help='Total de la factura o del recibo. En compras sin factura con retención al proveedor, '
             'el importe bruto acordado (el proveedor recibe el neto).')
    amount_paid = fields.Monetary(
        string='Pagado en efectivo', compute='_compute_amount_paid', store=True,
        help='Efectivo que salió del fondo: importe menos retenciones al proveedor.')
    product_id = fields.Many2one('product.product', string='Producto / concepto',
                                 domain="[('purchase_ok', '=', True)]")
    account_id = fields.Many2one(
        'account.account', string='Cuenta de gasto', compute='_compute_account_id', store=True,
        readonly=False, precompute=True, check_company=True,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost', 'asset_current'))]")
    tax_ids = fields.Many2many(
        'account.tax', string='Impuestos', compute='_compute_tax_ids', store=True, readonly=False,
        precompute=True, check_company=True,
        help='IVA crédito fiscal (con factura) o retención (sin factura). Se calculan solos.')
    receipt = fields.Binary(string='Foto del comprobante', attachment=True, copy=False)
    receipt_filename = fields.Char(string='Nombre del archivo', copy=False)
    move_id = fields.Many2one('account.move', string='Factura de proveedor', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    note = fields.Text(string='Notas')

    _amount_positive = models.Constraint('CHECK (amount > 0)', 'El importe del comprobante debe ser mayor que cero.')

    # ------------------------------------------------------------------
    # Valores por defecto y cálculos
    # ------------------------------------------------------------------
    @api.model
    def _default_fund(self):
        funds = self.env['l10n_bo.petty.cash.fund'].search([
            ('custodian_id', '=', self.env.uid), ('state', '=', 'open'), ('company_id', '=', self.env.company.id),
        ], limit=2)
        return funds if len(funds) == 1 else self.env['l10n_bo.petty.cash.fund']

    @api.depends('company_id')
    def _compute_l10n_bo_doc_type(self):
        return super()._compute_l10n_bo_doc_type()

    @api.depends('partner_id')
    def _compute_l10n_bo_supplier_nit(self):
        return super()._compute_l10n_bo_supplier_nit()

    @api.depends('l10n_bo_doc_type')
    def _compute_l10n_bo_purchase_type(self):
        return super()._compute_l10n_bo_purchase_type()

    @api.depends('fund_id')
    def _compute_analytic_distribution(self):
        for voucher in self:
            area = voucher.fund_id.analytic_account_id
            if area and not voucher.analytic_distribution:
                voucher.analytic_distribution = {str(area.id): 100}
            else:
                voucher.analytic_distribution = voucher.analytic_distribution

    @api.depends('product_id', 'company_id')
    def _compute_account_id(self):
        for voucher in self:
            account = voucher.account_id
            if voucher.product_id and voucher.company_id:
                accounts = voucher.product_id.product_tmpl_id.with_company(voucher.company_id).sudo()._get_product_accounts()
                account = accounts.get('expense') or account
            voucher.account_id = account

    @api.depends('l10n_bo_doc_type', 'l10n_bo_withholding_mode', 'l10n_bo_purchase_kind', 'company_id')
    def _compute_tax_ids(self):
        for voucher in self:
            company = voucher.company_id
            taxes = self.env['account.tax']
            if company and voucher.l10n_bo_doc_type in ('siat_online', 'dosificacion', 'manual'):
                taxes = self._l10n_bo_purchase_vat_tax(company)
            elif company and voucher.l10n_bo_doc_type == 'none':
                taxes = self._l10n_bo_withholding_tax(
                    company, voucher.l10n_bo_withholding_mode, voucher.l10n_bo_purchase_kind)
            voucher.tax_ids = taxes

    @api.depends('amount', 'tax_ids', 'currency_id')
    def _compute_amount_paid(self):
        for voucher in self:
            if voucher.tax_ids and voucher.amount:
                result = voucher.tax_ids.sudo().compute_all(voucher.amount, currency=voucher.currency_id, quantity=1.0)
                voucher.amount_paid = result['total_included']
            else:
                voucher.amount_paid = voucher.amount

    # ------------------------------------------------------------------
    # Restricciones
    # ------------------------------------------------------------------
    @api.constrains('amount', 'fund_id')
    def _check_max_expense(self):
        for voucher in self:
            fund = voucher.fund_id
            if fund.max_expense and voucher.currency_id.compare_amounts(voucher.amount, fund.max_expense) > 0:
                raise ValidationError(self.env._(
                    'El gasto de %(amount)s supera el tope por gasto del fondo %(fund)s (%(max)s). '
                    'Para compras mayores use una orden de compra o pida autorización al contador.',
                    amount=voucher.amount, fund=fund.name, max=fund.max_expense))

    @api.constrains('account_id', 'fund_id')
    def _check_allowed_account(self):
        for voucher in self:
            allowed = voucher.fund_id.allowed_account_ids
            if allowed and voucher.account_id and voucher.account_id not in allowed:
                raise ValidationError(self.env._(
                    'La cuenta %(account)s no está permitida en el fondo %(fund)s. Cuentas permitidas: %(allowed)s.',
                    account=voucher.account_id.display_name, fund=voucher.fund_id.name,
                    allowed=', '.join(allowed.mapped('display_name'))))

    @api.constrains('l10n_bo_doc_type', 'l10n_bo_supplier_nit', 'l10n_bo_invoice_number', 'l10n_bo_doc_key', 'state')
    def _check_l10n_bo_unique_document(self):
        for voucher in self:
            if voucher.state in ('draft', 'reported') and not voucher.move_id:
                voucher._l10n_bo_raise_if_duplicate()

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._l10n_bo_normalize_vals(vals)
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('l10n_bo.petty.cash.voucher') or '/'
        vouchers = super().create(vals_list)
        for voucher in vouchers:
            if voucher.fund_id.state != 'open':
                raise UserError(self.env._('El fondo %s no está abierto: no se pueden registrar gastos.', voucher.fund_id.name))
        return vouchers

    def write(self, vals):
        self._l10n_bo_normalize_vals(vals)
        if PROTECTED_FIELDS & set(vals) and not self.env.context.get('l10n_bo_petty_cash_internal'):
            is_accountant = self.env.su or self.env.user.has_group(ACCOUNTANT_GROUP)
            for voucher in self:
                if voucher.state in ('posted', 'cancel') or (voucher.state == 'reported' and not is_accountant):
                    raise UserError(self.env._(
                        'El comprobante %(name)s está %(state)s: no se puede modificar. '
                        'Pida al contador que devuelva la rendición a borrador.',
                        name=voucher.name, state=dict(self._fields['state'].selection)[voucher.state].lower()))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda v: v.state != 'draft'):
            raise UserError(self.env._('Solo se pueden eliminar comprobantes en borrador; los demás se anulan.'))

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def action_cancel(self):
        for voucher in self:
            if voucher.state != 'draft':
                raise UserError(self.env._('Solo se anulan comprobantes en borrador.'))
        self.with_context(l10n_bo_petty_cash_internal=True).write({'state': 'cancel', 'report_id': False})
        return True

    def action_draft(self):
        for voucher in self:
            if voucher.state != 'cancel':
                raise UserError(self.env._('Solo se reactivan comprobantes anulados.'))
        self.with_context(l10n_bo_petty_cash_internal=True).write({'state': 'draft'})
        return True

    def action_l10n_bo_open_qr_wizard(self):
        self.ensure_one()
        return self.env['l10n_bo.qr.wizard']._action_open(self)

    def _l10n_bo_apply_qr_data(self, data):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._('Solo se pueden completar con el QR comprobantes en borrador.'))
        vals = self._l10n_bo_qr_values(data)
        if data.get('date'):
            vals['date'] = data['date']
        if data.get('amount_total'):
            vals['amount'] = data['amount_total']
        if not self.partner_id:
            partner = self._l10n_bo_partner_from_nit(data.get('nit'))
            if partner:
                vals['partner_id'] = partner.id
        self.write(vals)
        if data.get('nit') and self.l10n_bo_supplier_nit != data['nit']:
            self.l10n_bo_supplier_nit = data['nit']
        return True

    def _submission_errors(self):
        """Datos que faltan para rendir el comprobante (lista de textos)."""
        self.ensure_one()
        _ = self.env._
        errors = []
        if not self.account_id and not (
            self.l10n_bo_doc_type == 'none' and self.l10n_bo_withholding_mode == 'no_withholding'
        ):
            errors.append(_('falta la cuenta de gasto o el producto'))
        if not (self.partner_id or self.supplier_name):
            errors.append(_('falta el proveedor'))
        if self.fund_id.require_receipt and not self.receipt:
            errors.append(_('falta la foto del comprobante'))
        errors += self._l10n_bo_document_errors()
        return errors

    # ------------------------------------------------------------------
    # Contabilización (al aprobar la rendición)
    # ------------------------------------------------------------------
    def _get_bill_partner(self):
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        partner = self._l10n_bo_partner_from_nit(self.l10n_bo_supplier_nit)
        if not partner:
            Partner = self.env['res.partner'].sudo()
            name = self.supplier_name or self.env._('Proveedor de fondo fijo')
            if not self.l10n_bo_supplier_nit:
                partner = Partner.search([('name', '=ilike', name), ('vat', '=', False), ('parent_id', '=', False)], limit=1)
            partner = partner or Partner.create({'name': name, 'vat': self.l10n_bo_supplier_nit or False})
        self.with_context(l10n_bo_petty_cash_internal=True).partner_id = partner
        return partner

    def _prepare_bill_vals(self):
        self.ensure_one()
        fund = self.fund_id
        partner = self._get_bill_partner()
        account = self.account_id
        if self.l10n_bo_doc_type == 'none' and self.l10n_bo_withholding_mode == 'no_withholding':
            account = self.company_id._l10n_bo_get_nodoc_account() or account
        line_vals = {
            'name': self.description,
            'quantity': 1.0,
            'price_unit': self.amount,
            'account_id': account.id,
            'tax_ids': [Command.set(self.tax_ids.ids)],
            'l10n_bo_purchase_kind': self.l10n_bo_purchase_kind,
        }
        if self.product_id:
            line_vals['product_id'] = self.product_id.id
        if self.analytic_distribution:
            line_vals['analytic_distribution'] = self.analytic_distribution
        vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': self.date,
            'date': self.date,
            'ref': self.l10n_bo_invoice_number or self.name,
            'invoice_origin': self.name,
            'l10n_bo_petty_cash_fund_id': fund.id,
            'l10n_bo_doc_type': self.l10n_bo_doc_type,
            'l10n_bo_supplier_nit': self.l10n_bo_supplier_nit,
            'l10n_bo_invoice_number': self.l10n_bo_invoice_number,
            'l10n_bo_cuf': self.l10n_bo_cuf,
            'l10n_bo_auth_number': self.l10n_bo_auth_number,
            'l10n_bo_control_code': self.l10n_bo_control_code,
            'l10n_bo_purchase_type': self.l10n_bo_purchase_type,
            'l10n_bo_withholding_mode': self.l10n_bo_withholding_mode,
            'l10n_bo_purchase_kind': self.l10n_bo_purchase_kind,
            'invoice_line_ids': [Command.create(line_vals)],
        }
        if fund.purchase_journal_id:
            vals['journal_id'] = fund.purchase_journal_id.id
        return vals

    def _create_bill_and_pay(self):
        """Factura de proveedor publicada (entra al Libro de Compras y a la unicidad) y
        pagada desde el diario del fondo."""
        self.ensure_one()
        bill = self.env['account.move'].create(self._prepare_bill_vals())
        if self.receipt:
            self.env['ir.attachment'].sudo().create({
                'name': self.receipt_filename or '%s.jpg' % self.name,
                'datas': self.receipt,
                'res_model': 'account.move',
                'res_id': bill.id,
            })
        # La factura se enlaza antes de publicarla para no detectarse a sí misma como duplicada.
        self.with_context(l10n_bo_petty_cash_internal=True).move_id = bill
        bill.action_post()
        payments = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.fund_id.journal_id.id,
            'payment_date': self.date,
        })._create_payments()
        self.with_context(l10n_bo_petty_cash_internal=True).write({
            'payment_id': payments[:1].id,
            'state': 'posted',
        })
        return bill
