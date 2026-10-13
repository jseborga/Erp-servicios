# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.tools import SQL

REVENUE_KINDS = [
    ('membership', 'Membresía (alta)'),
    ('renewal', 'Renovación'),
    ('single', 'Servicio suelto'),
    ('charges', 'Cargos (invitados, penalidades)'),
    ('pos', 'Restaurante y cafetería'),
    ('other', 'Otros'),
]


class SpaReportRevenue(models.Model):
    """Ingresos del spa sin impuestos, por fecha, tipo de cobro, plan y categoría de producto.

    Tres orígenes, sin duplicar montos:

    * **Factura**: líneas de producto de facturas y notas de crédito de cliente publicadas.
      «Facturado» es todo el importe sin impuestos; «Devengado» solo lo que fue a cuentas de
      ingreso (los planes prepagados van a 215100 Ingresos diferidos y se devengan mes a mes).
      Las facturas de órdenes del POS sin tipo de cobro del spa cuentan como restaurante y cafetería.
    * **Devengo de prepagados**: cuotas mensuales contabilizadas de ``spa.deferral.line``.
    * **Venta POS sin factura**: órdenes pagadas del POS que no se facturaron una por una.

    «Devengado» por mes = ingreso del estado de resultados que generó el spa en ese mes.
    """
    _name = 'spa.report.revenue'
    _description = 'Ingresos del spa'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'move_id'
    _depends = {
        'account.move': ['move_type', 'state', 'invoice_date', 'spa_invoice_kind', 'spa_membership_id',
                         'partner_id', 'company_id'],
        'account.move.line': ['move_id', 'balance', 'account_id', 'product_id', 'display_type'],
        'spa.deferral.line': ['membership_id', 'invoice_id', 'date', 'amount', 'state', 'move_id'],
        'spa.membership': ['plan_id', 'period_id', 'partner_id'],
        'pos.order': ['state', 'account_move', 'date_order', 'partner_id', 'company_id'],
        'pos.order.line': ['order_id', 'product_id', 'price_subtotal'],
    }

    source = fields.Selection([
        ('invoice', 'Factura'),
        ('deferral', 'Devengo de prepagados'),
        ('pos', 'Venta POS sin factura'),
    ], string='Origen', readonly=True)
    date = fields.Date('Fecha', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    kind = fields.Selection(REVENUE_KINDS, string='Tipo de ingreso', readonly=True)
    membership_id = fields.Many2one('spa.membership', string='Membresía', readonly=True)
    plan_id = fields.Many2one('spa.plan', string='Plan', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    categ_id = fields.Many2one('product.category', string='Categoría de producto', readonly=True)
    account_id = fields.Many2one('account.account', string='Cuenta', readonly=True)
    move_id = fields.Many2one('account.move', string='Documento contable', readonly=True)
    amount_invoiced = fields.Monetary('Facturado (sin impuestos)', readonly=True, aggregator='sum')
    amount_recognized = fields.Monetary('Ingreso devengado', readonly=True, aggregator='sum')

    @property
    def _table_query(self):
        tz = self.env['spa.tools'].spa_tz().zone
        return SQL("""
            SELECT aml.id::bigint * 3 AS id,
                   'invoice' AS source,
                   am.invoice_date AS date,
                   am.company_id,
                   aml.company_currency_id AS currency_id,
                   COALESCE(am.spa_invoice_kind,
                            CASE WHEN EXISTS (SELECT 1 FROM pos_order po_inv WHERE po_inv.account_move = am.id)
                                 THEN 'pos' END,
                            'other') AS kind,
                   am.spa_membership_id AS membership_id,
                   m.plan_id,
                   am.partner_id,
                   aml.product_id,
                   pt.categ_id,
                   aml.account_id,
                   am.id AS move_id,
                   -aml.balance AS amount_invoiced,
                   CASE WHEN aa.account_type IN ('income', 'income_other') THEN -aml.balance ELSE 0 END
                       AS amount_recognized
              FROM account_move_line aml
              JOIN account_move am ON am.id = aml.move_id
              JOIN account_account aa ON aa.id = aml.account_id
              LEFT JOIN spa_membership m ON m.id = am.spa_membership_id
              LEFT JOIN product_product pp ON pp.id = aml.product_id
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE am.move_type IN ('out_invoice', 'out_refund')
               AND am.state = 'posted'
               AND aml.display_type = 'product'

            UNION ALL

            SELECT dl.id::bigint * 3 + 1 AS id,
                   'deferral' AS source,
                   dl.date,
                   dl.company_id,
                   rc.currency_id,
                   COALESCE(inv.spa_invoice_kind, 'membership') AS kind,
                   dl.membership_id,
                   m.plan_id,
                   m.partner_id,
                   per.product_id,
                   pt.categ_id,
                   income.account_id,
                   dl.move_id,
                   0 AS amount_invoiced,
                   dl.amount AS amount_recognized
              FROM spa_deferral_line dl
              JOIN spa_membership m ON m.id = dl.membership_id
              JOIN res_company rc ON rc.id = dl.company_id
              LEFT JOIN account_move inv ON inv.id = dl.invoice_id
              LEFT JOIN spa_plan_period per ON per.id = m.period_id
              LEFT JOIN product_product pp ON pp.id = per.product_id
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
              LEFT JOIN LATERAL (SELECT line.account_id
                                   FROM account_move_line line
                                  WHERE line.move_id = dl.move_id AND line.credit > 0
                                  ORDER BY line.id
                                  LIMIT 1) income ON TRUE
             WHERE dl.state = 'posted'

            UNION ALL

            SELECT pol.id::bigint * 3 + 2 AS id,
                   'pos' AS source,
                   (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS date,
                   po.company_id,
                   rc.currency_id,
                   'pos' AS kind,
                   NULL::int AS membership_id,
                   NULL::int AS plan_id,
                   po.partner_id,
                   pol.product_id,
                   pt.categ_id,
                   NULL::int AS account_id,
                   NULL::int AS move_id,
                   pol.price_subtotal AS amount_invoiced,
                   pol.price_subtotal AS amount_recognized
              FROM pos_order_line pol
              JOIN pos_order po ON po.id = pol.order_id
              JOIN res_company rc ON rc.id = po.company_id
              LEFT JOIN product_product pp ON pp.id = pol.product_id
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE po.state IN ('paid', 'done')
               AND po.account_move IS NULL
        """, tz=tz)
