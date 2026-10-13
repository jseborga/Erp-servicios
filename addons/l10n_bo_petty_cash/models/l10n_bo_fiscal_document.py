# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.tools import format_date

from odoo.addons.l10n_bo_purchase.models.l10n_bo_fiscal_document import INVOICE_DOC_TYPES


class L10nBoFiscalDocumentMixin(models.AbstractModel):
    _inherit = 'l10n_bo.fiscal.document.mixin'

    def _l10n_bo_find_duplicates(self):
        """Además de las facturas publicadas, busca comprobantes de fondo fijo pendientes
        (aún sin factura contable) con el mismo NIT, número y CUF/autorización."""
        duplicates = super()._l10n_bo_find_duplicates()
        key = self._l10n_bo_doc_key_value()
        if (
            self.l10n_bo_doc_type not in INVOICE_DOC_TYPES
            or not (self.l10n_bo_supplier_nit and self.l10n_bo_invoice_number and key)
        ):
            return duplicates
        domain = [
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('draft', 'reported')),
            ('move_id', '=', False),
            ('l10n_bo_supplier_nit', '=', self.l10n_bo_supplier_nit),
            ('l10n_bo_invoice_number', '=', self.l10n_bo_invoice_number),
            ('l10n_bo_doc_key', '=', key),
        ]
        if self._name == 'l10n_bo.petty.cash.voucher' and self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        vouchers = self.env['l10n_bo.petty.cash.voucher'].sudo().search(domain, limit=5)
        duplicates += [
            self.env._(
                'Comprobante de fondo fijo %(name)s (%(fund)s) del %(date)s',
                name=voucher.name, fund=voucher.fund_id.name, date=format_date(self.env, voucher.date))
            for voucher in vouchers
        ]
        return duplicates


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_bo_petty_cash_fund_id = fields.Many2one(
        'l10n_bo.petty.cash.fund', string='Fondo fijo', readonly=True, copy=False, index='btree_not_null',
        help='Fondo fijo que originó este asiento o factura (apertura, rendición, reposición o ajuste).')
