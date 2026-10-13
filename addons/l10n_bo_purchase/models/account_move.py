# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .l10n_bo_fiscal_document import INVOICE_DOC_TYPES, PURCHASE_KINDS

# Campos fiscales que no se modifican en un documento publicado.
L10N_BO_LOCKED_FIELDS = (
    'l10n_bo_doc_type', 'l10n_bo_supplier_nit', 'l10n_bo_invoice_number', 'l10n_bo_cuf',
    'l10n_bo_auth_number', 'l10n_bo_control_code', 'l10n_bo_withholding_mode',
)


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'l10n_bo.fiscal.document.mixin']

    l10n_bo_duplicate_warning = fields.Text(compute='_compute_l10n_bo_duplicate_warning')

    # Un documento de proveedor publicado (no cancelado) es único por compañía, NIT, número y
    # CUF/autorización. La restricción en Python da un mensaje con el documento existente;
    # el índice único protege también frente a registros simultáneos.
    _l10n_bo_purchase_document_unique = models.UniqueIndex(
        "(company_id, l10n_bo_supplier_nit, l10n_bo_invoice_number, l10n_bo_doc_key) "
        "WHERE state = 'posted' AND move_type IN ('in_invoice', 'in_refund') AND l10n_bo_doc_key IS NOT NULL",
        "Ya existe un documento de proveedor publicado con el mismo NIT, número y CUF/autorización. "
        "No se puede registrar dos veces la misma factura.",
    )

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    def _l10n_bo_applies(self):
        self.ensure_one()
        return self.move_type in ('in_invoice', 'in_refund') and self.country_code == 'BO'

    def _l10n_bo_default_doc_type(self):
        # Las notas de crédito de proveedor (reversiones) no reciben tipo por defecto: el
        # usuario lo indica solo si registra una nota de crédito-débito del proveedor.
        if self.move_type != 'in_invoice':
            return False
        return super()._l10n_bo_default_doc_type()

    @api.depends('move_type', 'company_id')
    def _compute_l10n_bo_doc_type(self):
        return super()._compute_l10n_bo_doc_type()

    @api.depends('partner_id', 'move_type')
    def _compute_l10n_bo_supplier_nit(self):
        return super()._compute_l10n_bo_supplier_nit()

    @api.depends('l10n_bo_doc_type', 'move_type')
    def _compute_l10n_bo_purchase_type(self):
        return super()._compute_l10n_bo_purchase_type()

    @api.depends('state', 'l10n_bo_doc_type', 'l10n_bo_supplier_nit', 'l10n_bo_invoice_number',
                 'l10n_bo_cuf', 'l10n_bo_auth_number')
    def _compute_l10n_bo_duplicate_warning(self):
        for move in self:
            warning = False
            if move.state == 'draft' and move._l10n_bo_applies():
                duplicates = move._l10n_bo_find_duplicates()
                if duplicates:
                    warning = self.env._(
                        'Este documento ya está registrado: %s. No podrá validarse.', '; '.join(duplicates))
            move.l10n_bo_duplicate_warning = warning

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._l10n_bo_normalize_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._l10n_bo_normalize_vals(vals)
        if any(fname in vals for fname in L10N_BO_LOCKED_FIELDS):
            for move in self:
                if move.state == 'posted' and move._l10n_bo_applies() and any(
                    move[fname] != vals[fname] for fname in L10N_BO_LOCKED_FIELDS if fname in vals
                ):
                    raise UserError(self.env._(
                        'No se pueden cambiar los datos fiscales de %s porque está publicado. '
                        'Restablézcalo a borrador, corrija los datos y vuelva a validarlo.', move.display_name))
        return super().write(vals)

    @api.constrains('state', 'l10n_bo_doc_key', 'l10n_bo_supplier_nit', 'l10n_bo_invoice_number', 'company_id')
    def _check_l10n_bo_unique_document(self):
        for move in self:
            if move.state == 'posted' and move._l10n_bo_applies():
                move._l10n_bo_raise_if_duplicate()

    # ------------------------------------------------------------------
    # Validación al publicar
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        for move in self:
            if move._l10n_bo_applies():
                move._l10n_bo_check_before_post()
        return super()._post(soft=soft)

    def _l10n_bo_product_lines(self):
        return self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

    def _l10n_bo_has_purchase_kind(self):
        lines = self._l10n_bo_product_lines()
        return bool(self.l10n_bo_purchase_kind) or bool(lines and all(lines.mapped('l10n_bo_purchase_kind')))

    def _l10n_bo_check_before_post(self):
        self.ensure_one()
        if self.move_type == 'in_refund' and not self.l10n_bo_doc_type:
            return  # reversión interna, sin documento del proveedor
        if not self.company_id.l10n_bo_purchase_check:
            self._l10n_bo_raise_if_duplicate()
            return
        errors = self._l10n_bo_document_errors() + self._l10n_bo_tax_errors()
        if errors:
            raise UserError(self.env._(
                'No se puede validar %(doc)s de %(partner)s:\n%(errors)s',
                doc=self.display_name, partner=self.partner_id.display_name or '-',
                errors='\n'.join('• %s' % e for e in errors)))
        self._l10n_bo_raise_if_duplicate()

    def _l10n_bo_tax_errors(self):
        self.ensure_one()
        _ = self.env._
        company = self.company_id
        lines = self._l10n_bo_product_lines()
        taxes = lines.tax_ids
        vat_taxes = self._l10n_bo_is_vat_credit_tax(taxes, company)
        whh_taxes = self._l10n_bo_is_withholding_tax(taxes, company)
        errors = []
        if self.l10n_bo_doc_type in INVOICE_DOC_TYPES:
            if whh_taxes:
                errors.append(_('Una compra con factura no lleva retenciones (%s): las retenciones son para compras sin factura.',
                                ', '.join(whh_taxes.mapped('name'))))
            return errors
        if self.l10n_bo_doc_type != 'none':
            return errors
        if vat_taxes:
            errors.append(_('Una compra sin factura no genera crédito fiscal IVA: quite el impuesto %s de las líneas.',
                            ', '.join(vat_taxes.mapped('name'))))
        mode = self.l10n_bo_withholding_mode
        if mode in ('supplier_bears', 'company_bears'):
            for line in lines:
                kind = line.l10n_bo_purchase_kind or self.l10n_bo_purchase_kind
                expected = self._l10n_bo_withholding_tax(company, mode, kind)
                if kind and not expected:
                    errors.append(_('No se encontró el impuesto de retención para "%s". Configúrelo en Ajustes de Contabilidad.',
                                    dict(PURCHASE_KINDS)[kind]))
                elif expected and expected not in line.tax_ids:
                    errors.append(_('La línea "%(line)s" no tiene la retención %(tax)s. Use el botón "Aplicar retenciones".',
                                    line=line.name or line.product_id.display_name, tax=expected.name))
        elif mode == 'no_withholding':
            if whh_taxes:
                errors.append(_('Eligió "sin retención" pero hay impuestos de retención (%s).', ', '.join(whh_taxes.mapped('name'))))
            account = company._l10n_bo_get_nodoc_account()
            wrong = lines.filtered(lambda l: account and l.account_id != account)
            if wrong:
                errors.append(_('Una compra sin factura ni retención se registra como gasto no deducible en %(account)s. '
                                'Use el botón "Aplicar retenciones" para corregir las líneas.', account=account.display_name))
        return errors

    # ------------------------------------------------------------------
    # Ayudante de retenciones
    # ------------------------------------------------------------------
    def _l10n_bo_tax_without_fiscal_taxes(self, taxes):
        """Quita IVA (crédito fiscal) y retenciones; conserva los demás impuestos."""
        company = self.company_id
        vat_groups = self._l10n_bo_vat_tax_groups(company)
        fiscal = self._l10n_bo_is_withholding_tax(taxes, company) | taxes.filtered(
            lambda t: t.flatten_taxes_hierarchy().tax_group_id & vat_groups)
        return taxes - fiscal

    def _l10n_bo_withholding_line_values(self, line):
        """Impuestos y cuenta que corresponden a una línea según el tratamiento sin factura."""
        self.ensure_one()
        company = self.company_id
        mode = self.l10n_bo_withholding_mode
        keep = self._l10n_bo_tax_without_fiscal_taxes(line.tax_ids)
        if mode in ('supplier_bears', 'company_bears'):
            kind = line.l10n_bo_purchase_kind or self.l10n_bo_purchase_kind
            if not kind:
                raise UserError(self.env._(
                    'Indique el tipo de compra para retención (bienes, servicios profesionales o servicios '
                    'eventuales/alquileres) en el documento o en la línea "%s".', line.name or '-'))
            tax = self._l10n_bo_withholding_tax(company, mode, kind)
            if not tax:
                raise UserError(self.env._(
                    'No se encontró el impuesto de retención para "%s". Configúrelo en Ajustes de Contabilidad '
                    '(Compras Bolivia).', dict(PURCHASE_KINDS)[kind]))
            return {'tax_ids': keep | tax}
        values = {'tax_ids': keep}
        account = company._l10n_bo_get_nodoc_account()
        if mode == 'no_withholding' and account:
            values['account_id'] = account
        return values

    def _l10n_bo_apply_withholding_lines(self):
        self.ensure_one()
        commands = []
        for line in self._l10n_bo_product_lines():
            values = self._l10n_bo_withholding_line_values(line)
            values = {
                'tax_ids': [Command.set(values['tax_ids'].ids)],
                **({'account_id': values['account_id'].id} if 'account_id' in values else {}),
            }
            commands.append(Command.update(line.id, values))
        if commands:
            self.write({'invoice_line_ids': commands})

    def action_l10n_bo_apply_withholding(self):
        for move in self:
            if move.state != 'draft':
                raise UserError(self.env._('Solo se pueden aplicar retenciones a documentos en borrador.'))
            if move.l10n_bo_doc_type != 'none':
                raise UserError(self.env._('Las retenciones se aplican solo a compras sin factura.'))
            if not move.l10n_bo_withholding_mode:
                raise UserError(self.env._(
                    'Indique el tratamiento de la compra sin factura (retener al proveedor, asumir la retención '
                    'o gasto no deducible sin retención).'))
            move._l10n_bo_apply_withholding_lines()
        return True

    @api.onchange('l10n_bo_doc_type', 'l10n_bo_withholding_mode', 'l10n_bo_purchase_kind')
    def _onchange_l10n_bo_withholding(self):
        if self.state != 'draft' or self.l10n_bo_doc_type != 'none' or not self.l10n_bo_withholding_mode:
            return
        lines = self._l10n_bo_product_lines()
        if self.l10n_bo_withholding_mode != 'no_withholding' and not self._l10n_bo_has_purchase_kind():
            for line in lines:
                line.tax_ids = self._l10n_bo_tax_without_fiscal_taxes(line.tax_ids)
            return
        for line in lines:
            line.update(self._l10n_bo_withholding_line_values(line))

    # ------------------------------------------------------------------
    # Lector QR
    # ------------------------------------------------------------------
    def _l10n_bo_apply_qr_data(self, data):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._('Solo se pueden completar con el QR documentos en borrador.'))
        vals = self._l10n_bo_qr_values(data)
        if data.get('date'):
            vals['invoice_date'] = data['date']
        if not self.partner_id:
            partner = self._l10n_bo_partner_from_nit(data.get('nit'))
            if partner:
                vals['partner_id'] = partner.id
        if not self.ref and data.get('number'):
            vals['ref'] = data['number']
        self.write(vals)
        if data.get('nit') and self.l10n_bo_supplier_nit != data['nit']:
            self.l10n_bo_supplier_nit = data['nit']
        amount = data.get('amount_total')
        if amount and not self._l10n_bo_product_lines():
            tax = self._l10n_bo_purchase_vat_tax(self.company_id) if self.l10n_bo_has_invoice else self.env['account.tax']
            self.write({'invoice_line_ids': [Command.create({
                'name': self.env._('Factura n.º %s', data.get('number') or ''),
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.set(tax.ids)],
            })]})
        return True

    def action_l10n_bo_open_qr_wizard(self):
        self.ensure_one()
        return self.env['l10n_bo.qr.wizard']._action_open(self)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    l10n_bo_purchase_kind = fields.Selection(
        PURCHASE_KINDS, string='Tipo de compra (retención)',
        help='Compras sin factura: tipo de compra de esta línea. Si se deja vacío se usa el del documento.')
