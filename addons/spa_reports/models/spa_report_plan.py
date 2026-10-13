# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.tools import SQL

MEMBERSHIP_STATES = [
    ('draft', 'Por activar'),
    ('active', 'Activa'),
    ('grace', 'En gracia'),
    ('suspended', 'Suspendida'),
    ('expired', 'Vencida'),
    ('cancelled', 'Cancelada'),
]


class SpaReportPlanUsage(models.Model):
    """Saldo de cada servicio del plan por socio y mes (a partir de ``spa.entitlement``).

    Responde «¿los socios usan lo que pagan?»: disponible (del plan + traslado), usado, sin usar y
    porcentaje de uso. En servicios ilimitados solo se informan los usos.
    """
    _name = 'spa.report.plan.usage'
    _description = 'Uso de los planes'
    _auto = False
    _order = 'month desc, plan_id, membership_id, service_id'
    _rec_name = 'membership_id'
    _depends = {
        'spa.entitlement': ['membership_id', 'plan_line_id', 'period_start', 'unlimited', 'granted',
                            'carried_in', 'used', 'remaining'],
        'spa.membership': ['partner_id', 'company_id', 'state'],
        'spa.plan.line': ['plan_id', 'service_id'],
    }

    membership_id = fields.Many2one('spa.membership', string='Membresía', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Socio', readonly=True)
    plan_id = fields.Many2one('spa.plan', string='Plan', readonly=True)
    service_id = fields.Many2one('spa.service', string='Servicio', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    month = fields.Date('Mes', readonly=True)
    membership_state = fields.Selection(MEMBERSHIP_STATES, string='Estado de la membresía', readonly=True)
    unlimited = fields.Boolean('Ilimitado', readonly=True)
    granted = fields.Integer('Del plan', readonly=True, aggregator='sum')
    carried_in = fields.Integer('Traslado del mes anterior', readonly=True, aggregator='sum')
    available = fields.Integer('Disponibles (plan + traslado)', readonly=True, aggregator='sum')
    used = fields.Integer('Usados', readonly=True, aggregator='sum')
    remaining = fields.Integer('Sin usar', readonly=True, aggregator='sum')
    utilization = fields.Float('Uso del saldo (%)', readonly=True, aggregator='avg', digits=(16, 1),
                               help='Usados / disponibles. Vacío en servicios ilimitados. Al agrupar se '
                                    'muestra el promedio de los socios.')

    @property
    def _table_query(self):
        return SQL("""
            SELECT e.id,
                   e.membership_id,
                   m.partner_id,
                   pl.plan_id,
                   pl.service_id,
                   m.company_id,
                   e.period_start AS month,
                   m.state AS membership_state,
                   COALESCE(e.unlimited, FALSE) AS unlimited,
                   CASE WHEN e.unlimited THEN 0 ELSE COALESCE(e.granted, 0) END AS granted,
                   CASE WHEN e.unlimited THEN 0 ELSE COALESCE(e.carried_in, 0) END AS carried_in,
                   CASE WHEN e.unlimited THEN 0 ELSE COALESCE(e.granted, 0) + COALESCE(e.carried_in, 0) END AS available,
                   COALESCE(e.used, 0) AS used,
                   CASE WHEN e.unlimited THEN 0 ELSE COALESCE(e.remaining, 0) END AS remaining,
                   CASE WHEN NOT COALESCE(e.unlimited, FALSE) AND COALESCE(e.granted, 0) + COALESCE(e.carried_in, 0) > 0
                        THEN 100.0 * COALESCE(e.used, 0) / (COALESCE(e.granted, 0) + COALESCE(e.carried_in, 0))
                   END AS utilization
              FROM spa_entitlement e
              JOIN spa_membership m ON m.id = e.membership_id
              JOIN spa_plan_line pl ON pl.id = e.plan_line_id
        """)


class SpaReportPlanProfitability(models.Model):
    """Rentabilidad por socio y mes de membresía.

    * Ingreso: precio del período de la membresía dividido entre sus meses (precio de lista).
    * Costo de servir: usos del mes × costo del producto del servicio (Costo en la ficha del producto).
    * Margen = ingreso − costo de servir.
    Al agrupar por plan, los campos «promedio» dan el uso y el margen típicos de un socio del plan.
    """
    _name = 'spa.report.plan.profitability'
    _description = 'Rentabilidad por plan'
    _auto = False
    _order = 'month desc, plan_id, membership_id'
    _rec_name = 'membership_id'
    _depends = {
        'spa.entitlement': ['membership_id', 'plan_line_id', 'period_start', 'unlimited', 'granted',
                            'carried_in', 'used'],
        'spa.membership': ['partner_id', 'company_id', 'state', 'period_id'],
        'spa.plan.line': ['plan_id', 'service_id'],
        'spa.plan.period': ['price', 'months'],
        'spa.service': ['product_id'],
        'product.product': ['standard_price'],
    }

    membership_id = fields.Many2one('spa.membership', string='Membresía', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Socio', readonly=True)
    plan_id = fields.Many2one('spa.plan', string='Plan', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    month = fields.Date('Mes', readonly=True)
    membership_state = fields.Selection(MEMBERSHIP_STATES, string='Estado de la membresía', readonly=True)
    revenue = fields.Monetary('Ingreso del mes', readonly=True, aggregator='sum',
                              help='Precio del período de la membresía / meses del período (precio de lista).')
    service_cost = fields.Monetary('Costo de servir', readonly=True, aggregator='sum',
                                   help='Usos × costo del producto de cada servicio.')
    margin = fields.Monetary('Margen', readonly=True, aggregator='sum')
    margin_pct = fields.Float('Margen (%) promedio', readonly=True, aggregator='avg', digits=(16, 1))
    uses = fields.Integer('Usos', readonly=True, aggregator='sum',
                          help='Sesiones e ingresos registrados en el mes (todos los servicios).')
    uses_avg = fields.Float('Usos por socio (promedio)', readonly=True, aggregator='avg', digits=(16, 1))
    sessions_available = fields.Integer('Sesiones disponibles (servicios con cupo)', readonly=True,
                                        aggregator='sum')
    sessions_used = fields.Integer('Sesiones usadas (servicios con cupo)', readonly=True, aggregator='sum')
    utilization = fields.Float('Uso del saldo (%) promedio', readonly=True, aggregator='avg', digits=(16, 1),
                               help='Sesiones usadas / disponibles en los servicios con cupo.')

    @property
    def _table_query(self):
        return SQL("""
            WITH member_month AS (
                SELECT MIN(e.id) AS id,
                       e.membership_id,
                       m.partner_id,
                       pl.plan_id,
                       m.company_id,
                       e.period_start AS month,
                       m.state AS membership_state,
                       COALESCE(MAX(per.price / NULLIF(per.months, 0)), 0) AS revenue,
                       SUM(COALESCE(e.used, 0)
                           * COALESCE((pp.standard_price ->> m.company_id::text)::numeric, 0)) AS service_cost,
                       SUM(COALESCE(e.used, 0)) AS uses,
                       SUM(CASE WHEN e.unlimited THEN 0
                                ELSE COALESCE(e.granted, 0) + COALESCE(e.carried_in, 0) END) AS sessions_available,
                       SUM(CASE WHEN e.unlimited THEN 0 ELSE COALESCE(e.used, 0) END) AS sessions_used
                  FROM spa_entitlement e
                  JOIN spa_membership m ON m.id = e.membership_id
                  JOIN spa_plan_line pl ON pl.id = e.plan_line_id
                  LEFT JOIN spa_plan_period per ON per.id = m.period_id
                  LEFT JOIN spa_service sv ON sv.id = pl.service_id
                  LEFT JOIN product_product pp ON pp.id = sv.product_id
                 GROUP BY e.membership_id, m.partner_id, pl.plan_id, m.company_id, e.period_start, m.state
            )
            SELECT mm.id,
                   mm.membership_id,
                   mm.partner_id,
                   mm.plan_id,
                   mm.company_id,
                   rc.currency_id,
                   mm.month,
                   mm.membership_state,
                   mm.revenue,
                   mm.service_cost,
                   mm.revenue - mm.service_cost AS margin,
                   CASE WHEN mm.revenue > 0 THEN 100.0 * (mm.revenue - mm.service_cost) / mm.revenue END AS margin_pct,
                   mm.uses,
                   mm.uses AS uses_avg,
                   mm.sessions_available,
                   mm.sessions_used,
                   CASE WHEN mm.sessions_available > 0
                        THEN 100.0 * mm.sessions_used / mm.sessions_available END AS utilization
              FROM member_month mm
              JOIN res_company rc ON rc.id = mm.company_id
        """)
