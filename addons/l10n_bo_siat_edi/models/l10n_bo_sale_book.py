# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models, tools
from odoo.tools import SQL

from .l10n_bo_siat_catalog import BO_TZ, BUYER_DOC_TYPES, SIAT_STATES


class L10nBoSaleBook(models.Model):
    """Libro de Ventas (Registro de Ventas del SIN) en solo lectura.

    Una fila por factura de venta con datos SIAT (aceptada, con anulación solicitada o anulada).
    Las facturas en línea se registran automáticamente en el RCV del SIN: este libro sirve para
    conciliar con el RCV y para el control interno. Se exporta con la exportación estándar.

    Supuestos (POR VERIFICAR con el formato vigente del SIN y el contador):

    * Columnas en el orden del Registro de Ventas estándar del RCV.
    * Facturas anuladas: estado "A" e importes en cero (el SIN indica que el RCV "no totaliza las
      facturas registradas como anuladas"; los importes en cero vienen del formato LCV anterior).
    * ICE, IEHD, IPJ, tasas y gift card no se modelan: 0. Exentas, tasa cero y no sujetas al IVA se
      obtienen del grupo de impuesto de l10n_bo de cada línea.
    * Descuentos sujetos al IVA: descuento de línea de Odoo (precio con IVA incluido). El importe
      total se informa antes de descuentos; la base para débito fiscal es el neto.
    * Débito fiscal: importe de las líneas de IVA 13 % del asiento (13 % del precio con IVA incluido).
    * No incluye notas de crédito-débito (tienen su propio registro), ventas sin factura ni facturas
      pendientes de registro.
    """
    _name = 'l10n_bo.sale.book'
    _description = 'Libro de Ventas (Bolivia)'
    _auto = False
    _order = 'date, invoice_number_int, id'
    _rec_name = 'invoice_number'
    # Campos a escribir en la base antes de leer la vista (no se usa para recalcular).
    _depends = {
        'account.move': [
            'move_type', 'state', 'company_id', 'commercial_partner_id', 'invoice_date', 'amount_total_signed',
            'invoice_currency_rate', 'l10n_bo_sale_doc', 'l10n_bo_siat_state', 'l10n_bo_siat_number',
            'l10n_bo_siat_cuf', 'l10n_bo_siat_emission_date', 'l10n_bo_siat_simulated',
            'l10n_bo_sale_buyer_doc_type', 'l10n_bo_sale_buyer_number', 'l10n_bo_sale_buyer_complement',
            'l10n_bo_sale_buyer_name',
        ],
        'account.move.line': [
            'move_id', 'balance', 'display_type', 'tax_line_id', 'tax_ids', 'discount', 'price_unit', 'quantity',
            'price_total',
        ],
    }

    move_id = fields.Many2one('account.move', string='Factura', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    specification = fields.Integer(string='Especificación', readonly=True, help='2 = ventas (formato RCV).')
    date = fields.Date(string='Fecha de la factura', readonly=True, help='Fecha de emisión SIAT (hora de Bolivia).')
    period = fields.Char(string='Período (AAAA-MM)', readonly=True)
    invoice_number = fields.Char(string='N.º de factura', readonly=True)
    invoice_number_int = fields.Integer(string='N.º (orden)', readonly=True)
    auth_code = fields.Char(string='Código de autorización (CUF)', readonly=True)
    buyer_doc_type = fields.Selection(BUYER_DOC_TYPES, string='Tipo de documento', readonly=True)
    buyer_number = fields.Char(string='NIT/CI cliente', readonly=True)
    buyer_complement = fields.Char(string='Complemento', readonly=True)
    buyer_name = fields.Char(string='Nombre o razón social', readonly=True)
    amount_total = fields.Monetary(string='Importe total de la venta', readonly=True)
    amount_ice = fields.Monetary(string='Importe ICE', readonly=True)
    amount_iehd = fields.Monetary(string='Importe IEHD', readonly=True)
    amount_ipj = fields.Monetary(string='Importe IPJ', readonly=True)
    amount_fees = fields.Monetary(string='Tasas', readonly=True)
    amount_not_subject = fields.Monetary(string='Otros no sujetos al IVA', readonly=True)
    amount_exempt = fields.Monetary(string='Exportaciones y operaciones exentas', readonly=True)
    amount_zero_rate = fields.Monetary(string='Ventas gravadas a tasa cero', readonly=True)
    amount_subtotal = fields.Monetary(string='Subtotal', readonly=True)
    amount_discount = fields.Monetary(string='Descuentos, bonificaciones y rebajas sujetas al IVA', readonly=True)
    amount_gift_card = fields.Monetary(string='Importe gift card', readonly=True)
    amount_base = fields.Monetary(string='Importe base para débito fiscal', readonly=True)
    amount_debit = fields.Monetary(string='Débito fiscal (13 %)', readonly=True)
    state = fields.Selection([('V', 'V - Válida'), ('A', 'A - Anulada')], string='Estado', readonly=True)
    control_code = fields.Char(string='Código de control', readonly=True, help='0 para facturas en línea (con CUF).')
    sale_type = fields.Char(string='Tipo de venta', readonly=True, help='0 = otros; 1 = gift card (no se usa).')
    siat_state = fields.Selection(SIAT_STATES, string='Estado SIAT', readonly=True)
    simulated = fields.Boolean(string='Simulado (no válido)', readonly=True)

    def _query(self):
        return SQL("""
            SELECT m.id AS id,
                   m.id AS move_id,
                   m.company_id AS company_id,
                   c.currency_id AS currency_id,
                   m.commercial_partner_id AS partner_id,
                   2 AS specification,
                   d.day AS date,
                   to_char(d.day, 'YYYY-MM') AS period,
                   m.l10n_bo_siat_number AS invoice_number,
                   CASE WHEN m.l10n_bo_siat_number ~ '^[0-9]{1,9}$'
                        THEN m.l10n_bo_siat_number::integer ELSE 0 END AS invoice_number_int,
                   m.l10n_bo_siat_cuf AS auth_code,
                   m.l10n_bo_sale_buyer_doc_type AS buyer_doc_type,
                   m.l10n_bo_sale_buyer_number AS buyer_number,
                   m.l10n_bo_sale_buyer_complement AS buyer_complement,
                   m.l10n_bo_sale_buyer_name AS buyer_name,
                   x.k * (m.amount_total_signed + a.discount) AS amount_total,
                   0.0 AS amount_ice,
                   0.0 AS amount_iehd,
                   0.0 AS amount_ipj,
                   0.0 AS amount_fees,
                   x.k * a.not_subject AS amount_not_subject,
                   x.k * a.exempt AS amount_exempt,
                   x.k * a.zero_rate AS amount_zero_rate,
                   x.k * (m.amount_total_signed + a.discount - a.not_subject - a.exempt - a.zero_rate) AS amount_subtotal,
                   x.k * a.discount AS amount_discount,
                   0.0 AS amount_gift_card,
                   x.k * (m.amount_total_signed - a.not_subject - a.exempt - a.zero_rate) AS amount_base,
                   x.k * a.debit AS amount_debit,
                   CASE WHEN m.l10n_bo_siat_state = 'cancelled' THEN 'A' ELSE 'V' END AS state,
                   '0' AS control_code,
                   '0' AS sale_type,
                   m.l10n_bo_siat_state AS siat_state,
                   COALESCE(m.l10n_bo_siat_simulated, FALSE) AS simulated
              FROM account_move m
              JOIN res_company c ON c.id = m.company_id
              CROSS JOIN LATERAL (
                    SELECT CASE WHEN m.l10n_bo_siat_state = 'cancelled' THEN 0.0 ELSE 1.0 END AS k
              ) x
              CROSS JOIN LATERAL (
                    SELECT COALESCE(
                        (timezone(%(tz)s, m.l10n_bo_siat_emission_date AT TIME ZONE 'UTC'))::date,
                        m.invoice_date) AS day
              ) d
              LEFT JOIN LATERAL (
                    SELECT COALESCE(-SUM(l.balance) FILTER (WHERE l.display_type = 'tax' AND k.kind = 'iva'), 0.0) AS debit,
                           COALESCE(-SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'exempt'), 0.0) AS exempt,
                           COALESCE(-SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'zero'), 0.0) AS zero_rate,
                           COALESCE(-SUM(l.balance) FILTER (WHERE l.display_type = 'product' AND k.kind = 'other'), 0.0) AS not_subject,
                           COALESCE(SUM(
                               CASE WHEN l.discount >= 100 THEN l.price_unit * l.quantity
                                    ELSE l.price_total * l.discount / (100.0 - l.discount) END
                               / CASE WHEN COALESCE(m.invoice_currency_rate, 0) > 0 THEN m.invoice_currency_rate ELSE 1.0 END
                           ) FILTER (WHERE l.display_type = 'product' AND k.kind = 'iva' AND l.discount > 0), 0.0) AS discount
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
             WHERE m.move_type = 'out_invoice'
               AND m.state = 'posted'
               AND m.l10n_bo_sale_doc = 'siat'
               AND m.l10n_bo_siat_state IN ('accepted', 'cancel_requested', 'cancelled')
        """, tz=BO_TZ)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("CREATE OR REPLACE VIEW %s AS (%s)", SQL.identifier(self._table), self._query()))

    def action_open_move(self):
        self.ensure_one()
        return self.move_id._get_records_action()
