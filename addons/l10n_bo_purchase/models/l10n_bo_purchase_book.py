# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models, tools
from odoo.tools import SQL

from .l10n_bo_fiscal_document import DOC_TYPES, PURCHASE_TYPES


class L10nBoPurchaseBook(models.Model):
    """Libro de Compras (Registro de Compras del SIN) en solo lectura.

    Una fila por factura de proveedor publicada con documento fiscal (se excluyen las
    compras sin factura y las notas de crédito). Se exporta con la exportación estándar de
    la lista. El orden y formato de columnas del archivo oficial del SIAT deben verificarse
    con la versión vigente del SIN antes de presentarlo.

    Importes en moneda de la compañía (Bs). ICE, IEHD, IPJ, tasas, descuentos y gift card
    no se modelan por separado: se informan en 0 (los descuentos ya vienen netos en la línea).
    """
    _name = 'l10n_bo.purchase.book'
    _description = 'Libro de Compras (Bolivia)'
    _auto = False
    _order = 'date, id'
    _rec_name = 'invoice_number'

    move_id = fields.Many2one('account.move', string='Factura de proveedor', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Proveedor', readonly=True)
    specification = fields.Integer(string='Especificación', readonly=True, help='1 = compras (formato LCV).')
    date = fields.Date(string='Fecha de la factura', readonly=True)
    period = fields.Char(string='Período (AAAA-MM)', readonly=True)
    supplier_nit = fields.Char(string='NIT proveedor', readonly=True)
    supplier_name = fields.Char(string='Razón social proveedor', readonly=True)
    auth_number = fields.Char(
        string='Código de autorización', readonly=True,
        help='Número de autorización; para facturas con CUF se informa "1" (verificar formato vigente del SIN).')
    invoice_number = fields.Char(string='Número de factura', readonly=True)
    dui_dim = fields.Char(string='Número DUI/DIM', readonly=True)
    control_code = fields.Char(
        string='Código de control / CUF', readonly=True,
        help='CUF para facturas en línea; código de control para computarizadas; 0 para manuales.')
    doc_type = fields.Selection(DOC_TYPES, string='Tipo de documento', readonly=True)
    amount_total = fields.Monetary(string='Importe total de la compra', readonly=True)
    amount_ice = fields.Monetary(string='Importe ICE', readonly=True)
    amount_iehd = fields.Monetary(string='Importe IEHD', readonly=True)
    amount_ipj = fields.Monetary(string='Importe IPJ', readonly=True)
    amount_fees = fields.Monetary(string='Tasas', readonly=True)
    amount_not_subject = fields.Monetary(string='Otro no sujeto a crédito fiscal', readonly=True)
    amount_exempt = fields.Monetary(string='Importes exentos', readonly=True)
    amount_zero_rate = fields.Monetary(string='Compras gravadas a tasa cero', readonly=True)
    amount_subtotal = fields.Monetary(string='Subtotal', readonly=True)
    amount_discount = fields.Monetary(string='Descuentos, bonificaciones y rebajas', readonly=True)
    amount_gift_card = fields.Monetary(string='Importe gift card', readonly=True)
    amount_base = fields.Monetary(string='Importe base para crédito fiscal', readonly=True)
    amount_credit = fields.Monetary(string='Crédito fiscal (13 %)', readonly=True)
    purchase_type = fields.Selection(PURCHASE_TYPES, string='Tipo de compra', readonly=True)

    def _query(self):
        return SQL("""
            SELECT m.id AS id,
                   m.id AS move_id,
                   m.company_id AS company_id,
                   c.currency_id AS currency_id,
                   m.commercial_partner_id AS partner_id,
                   1 AS specification,
                   m.invoice_date AS date,
                   to_char(m.invoice_date, 'YYYY-MM') AS period,
                   m.l10n_bo_supplier_nit AS supplier_nit,
                   p.name AS supplier_name,
                   CASE WHEN m.l10n_bo_doc_type = 'siat_online' THEN '1' ELSE m.l10n_bo_auth_number END AS auth_number,
                   m.l10n_bo_invoice_number AS invoice_number,
                   '0' AS dui_dim,
                   CASE m.l10n_bo_doc_type
                        WHEN 'siat_online' THEN m.l10n_bo_cuf
                        WHEN 'dosificacion' THEN m.l10n_bo_control_code
                        ELSE '0' END AS control_code,
                   m.l10n_bo_doc_type AS doc_type,
                   -m.amount_total_signed AS amount_total,
                   0.0 AS amount_ice,
                   0.0 AS amount_iehd,
                   0.0 AS amount_ipj,
                   0.0 AS amount_fees,
                   a.not_subject AS amount_not_subject,
                   a.exempt AS amount_exempt,
                   a.zero_rate AS amount_zero_rate,
                   -m.amount_total_signed - a.not_subject - a.exempt - a.zero_rate AS amount_subtotal,
                   0.0 AS amount_discount,
                   0.0 AS amount_gift_card,
                   -m.amount_total_signed - a.not_subject - a.exempt - a.zero_rate AS amount_base,
                   a.credit AS amount_credit,
                   m.l10n_bo_purchase_type AS purchase_type
              FROM account_move m
              JOIN res_company c ON c.id = m.company_id
              JOIN res_partner p ON p.id = m.commercial_partner_id
              LEFT JOIN LATERAL (
                    SELECT COALESCE(SUM(l.balance) FILTER (WHERE l.display_type = 'tax' AND k.kind = 'iva'), 0.0) AS credit,
                           COALESCE(SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'exempt'), 0.0) AS exempt,
                           COALESCE(SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'zero'), 0.0) AS zero_rate,
                           COALESCE(SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'other'), 0.0) AS not_subject
                      FROM account_move_line l
                      LEFT JOIN LATERAL (
                            -- Clasifica la línea por el grupo de impuesto de l10n_bo (xmlid de la plantilla)
                            SELECT CASE WHEN bool_or(imd.name ~ '_tax_group_iva_(13|mixed)$') THEN 'iva'
                                        WHEN bool_or(imd.name ~ '_tax_group_iva_0_exempt$') THEN 'exempt'
                                        WHEN bool_or(imd.name ~ '_tax_group_iva_0$') THEN 'zero'
                                        ELSE 'other' END AS kind
                              FROM account_tax t
                              JOIN ir_model_data imd ON imd.model = 'account.tax.group'
                                                    AND imd.module = 'account'
                                                    AND imd.res_id = t.tax_group_id
                             WHERE t.id = l.tax_line_id
                                OR t.id IN (SELECT rel.account_tax_id
                                              FROM account_move_line_account_tax_rel rel
                                             WHERE rel.account_move_line_id = l.id)
                      ) k ON TRUE
                     WHERE l.move_id = m.id
              ) a ON TRUE
             WHERE m.move_type = 'in_invoice'
               AND m.state = 'posted'
               AND m.l10n_bo_doc_type IN ('siat_online', 'dosificacion', 'manual')
        """)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("CREATE OR REPLACE VIEW %s AS (%s)", SQL.identifier(self._table), self._query()))

    def action_open_move(self):
        self.ensure_one()
        return self.move_id._get_records_action()
