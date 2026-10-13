# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.tools import SQL

AREA_PLAN_XMLID = 'l10n_bo_spa.analytic_plan_areas'

SECTIONS = [
    ('income', 'Ingresos (41)'),
    ('direct_cost', 'Costos directos (51)'),
    ('selling', 'Gastos de comercialización (52)'),
    ('admin', 'Gastos de administración (53)'),
    ('other_income', 'Otros ingresos (42-49)'),
    ('other_expense', 'Otros gastos (54-59)'),
    ('other', 'Otras cuentas'),
]


class SpaReportAreaMove(models.Model):
    """Apuntes analíticos del plan «Áreas del negocio» con forma de apunte contable.

    Cada fila es un apunte analítico (ya prorrateado por el modelo de reparto) con su cuenta
    financiera, la sección del estado de resultados y debe/haber equivalentes. Sirve para:

    * el pivote «Rentabilidad por área» (filas = área, columnas = sección), y
    * como origen de datos de MIS Builder (plantilla «Estado de resultados por área»), que necesita
      un modelo con ``debit``, ``credit``, ``account_id``, ``date`` y ``company_id``.

    La columna del plan analítico en ``account.analytic.line`` es dinámica (``x_plan<N>_id``): se
    resuelve en cada consulta con ``plan._column_name()``.
    """
    _name = 'spa.report.area.move'
    _description = 'Resultado por área (apuntes analíticos)'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'name'
    _depends = {
        'account.analytic.line': ['amount', 'date', 'company_id', 'general_account_id', 'partner_id',
                                  'product_id', 'journal_id', 'move_line_id', 'name'],
        'account.move.line': ['move_id'],
        'account.move': ['state'],
    }

    date = fields.Date('Fecha', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    area_id = fields.Many2one('account.analytic.account', string='Área', readonly=True)
    account_id = fields.Many2one('account.account', string='Cuenta', readonly=True)
    account_code = fields.Char('Código de cuenta', readonly=True)
    section = fields.Selection(SECTIONS, string='Sección del estado de resultados', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Contacto', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Diario', readonly=True)
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True)
    name = fields.Char('Descripción', readonly=True)
    parent_state = fields.Selection([
        ('draft', 'Borrador'),
        ('posted', 'Publicado'),
        ('cancel', 'Cancelado'),
    ], string='Estado del asiento', readonly=True)
    debit = fields.Monetary('Debe', readonly=True, aggregator='sum')
    credit = fields.Monetary('Haber', readonly=True, aggregator='sum')
    balance = fields.Monetary('Saldo (debe − haber)', readonly=True, aggregator='sum')
    amount = fields.Monetary('Resultado', readonly=True, aggregator='sum',
                             help='Positivo = ingreso; negativo = costo o gasto. La suma por área es su resultado.')

    @api.model
    def _area_plan(self):
        return self.env.ref(AREA_PLAN_XMLID, raise_if_not_found=False)

    @api.model
    def _area_column(self):
        """Nombre de la columna del plan «Áreas del negocio» en ``account.analytic.line`` (o None)."""
        plan = self._area_plan()
        if not plan:
            return None
        column = plan.sudo()._column_name()
        return column if column in self.env['account.analytic.line']._fields else None

    @property
    def _table_query(self):
        column = self._area_column()
        area = SQL.identifier('aal', column) if column else SQL('NULL::int')
        return SQL("""
            SELECT aal.id,
                   aal.date,
                   aal.company_id,
                   rc.currency_id,
                   %(area)s AS area_id,
                   aal.general_account_id AS account_id,
                   code.acc_code AS account_code,
                   CASE WHEN code.acc_code LIKE '41%%' THEN 'income'
                        WHEN code.acc_code LIKE '51%%' THEN 'direct_cost'
                        WHEN code.acc_code LIKE '52%%' THEN 'selling'
                        WHEN code.acc_code LIKE '53%%' THEN 'admin'
                        WHEN code.acc_code LIKE '4%%' THEN 'other_income'
                        WHEN code.acc_code LIKE '5%%' THEN 'other_expense'
                        ELSE 'other' END AS section,
                   aal.partner_id,
                   aal.product_id,
                   aal.journal_id,
                   aml.move_id,
                   aal.name,
                   COALESCE(am.state, 'posted') AS parent_state,
                   CASE WHEN aal.amount < 0 THEN -aal.amount ELSE 0 END AS debit,
                   CASE WHEN aal.amount > 0 THEN aal.amount ELSE 0 END AS credit,
                   -aal.amount AS balance,
                   aal.amount
              FROM account_analytic_line aal
              JOIN res_company rc ON rc.id = aal.company_id
              JOIN account_account aa ON aa.id = aal.general_account_id
              LEFT JOIN account_move_line aml ON aml.id = aal.move_line_id
              LEFT JOIN account_move am ON am.id = aml.move_id
             CROSS JOIN LATERAL (
                   SELECT COALESCE(aa.code_store ->> split_part(rc.parent_path, '/', 1),
                                   aa.code_store ->> rc.id::text) AS acc_code
             ) code
             WHERE %(area)s IS NOT NULL
        """, area=area)

    @api.model
    def action_open_analytic_lines(self):
        """Pivote de apuntes analíticos: filas = área (columna dinámica del plan), columnas = cuenta."""
        column = self._area_column()
        context = {
            'pivot_measures': ['amount'],
            'pivot_column_groupby': ['general_account_id'],
        }
        domain = []
        if column:
            context['pivot_row_groupby'] = [column]
            domain = [(column, '!=', False)]
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Apuntes analíticos por área'),
            'res_model': 'account.analytic.line',
            'view_mode': 'pivot,graph,list',
            'views': [(False, 'pivot'), (False, 'graph'), (False, 'list')],
            'domain': domain,
            'context': context,
            'help': self.env._('<p>Aún no hay apuntes con área. Las facturas de proveedor de las cuentas 51, '
                               '52 y 53 exigen el área; las ventas toman el área del espacio o del punto de '
                               'venta.</p>'),
        }
