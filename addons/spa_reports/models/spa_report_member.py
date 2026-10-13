# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.tools import SQL

from .spa_report_plan import MEMBERSHIP_STATES

AGING = [
    ('none', 'Sin deuda'),
    ('current', 'Por vencer'),
    ('1_30', '1 a 30 días'),
    ('31_60', '31 a 60 días'),
    ('61_90', '61 a 90 días'),
    ('90_plus', 'Más de 90 días'),
]


class SpaReportMember(models.Model):
    """Socios por estado y plan, con su saldo por cobrar y días de mora.

    La deuda son las facturas de cliente publicadas de la membresía con saldo pendiente (alta, renovación,
    cargos y consumos del restaurante cargados a su cuenta) más los cobros pendientes aún sin factura
    (renovación, cambio de plan y alta: se facturan al cobrar). Los días de mora se cuentan desde el
    vencimiento más antiguo hasta hoy (hora local del spa); una renovación pendiente vence con la membresía
    (días desde su vencimiento) y un alta pendiente no genera mora (es una oferta).
    """
    _name = 'spa.report.member'
    _description = 'Socios y mora'
    _auto = False
    _order = 'days_overdue desc, amount_due desc, id desc'
    _depends = {
        'spa.membership': ['name', 'partner_id', 'plan_id', 'period_id', 'company_id', 'state', 'date_start',
                           'date_end', 'grace_until'],
        'spa.plan.period': ['price', 'months'],
        'account.move': ['move_type', 'state', 'spa_membership_id', 'amount_residual_signed',
                         'invoice_date_due', 'invoice_date', 'spa_invoice_kind'],
    }

    name = fields.Char('Membresía', readonly=True)
    membership_id = fields.Many2one('spa.membership', string='Ficha de la membresía', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Socio', readonly=True)
    phone = fields.Char(related='partner_id.phone', string='Celular')
    plan_id = fields.Many2one('spa.plan', string='Plan', readonly=True)
    period_id = fields.Many2one('spa.plan.period', string='Duración', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    state = fields.Selection(MEMBERSHIP_STATES, string='Estado', readonly=True)
    date_start = fields.Date('Inicio', readonly=True)
    date_end = fields.Date('Vence', readonly=True)
    grace_until = fields.Date('Gracia hasta', readonly=True)
    mrr = fields.Monetary('Ingreso mensual recurrente', readonly=True, aggregator='sum',
                          help='Precio del período / meses, solo membresías activas o en gracia.')
    amount_due = fields.Monetary('Saldo por cobrar', readonly=True, aggregator='sum')
    amount_overdue = fields.Monetary('Vencido', readonly=True, aggregator='sum')
    oldest_due_date = fields.Date('Vencimiento más antiguo impago', readonly=True)
    days_overdue = fields.Integer('Días de mora', readonly=True, aggregator='max')
    aging = fields.Selection(AGING, string='Antigüedad de la deuda', readonly=True)

    @property
    def _table_query(self):
        tz = self.env['spa.tools'].spa_tz().zone
        return SQL("""
            WITH params AS (
                SELECT (NOW() AT TIME ZONE %(tz)s)::date AS today
            ),
            due AS (
                SELECT am.spa_membership_id AS membership_id,
                       SUM(am.amount_residual_signed) AS amount_due,
                       SUM(CASE WHEN dd.due_date < p.today
                                THEN am.amount_residual_signed ELSE 0 END) AS amount_overdue,
                       MIN(dd.due_date) AS oldest_due
                  FROM account_move am
                  JOIN spa_membership mm ON mm.id = am.spa_membership_id
                 CROSS JOIN params p
                 CROSS JOIN LATERAL (
                       SELECT CASE
                                -- Renovación pendiente (aún sin factura): vence con la membresía.
                                WHEN am.state = 'draft' AND am.spa_invoice_kind = 'renewal'
                                    THEN COALESCE(mm.date_end, am.invoice_date_due, am.invoice_date)
                                -- Alta pendiente: es una oferta, aún no hay deuda vencida.
                                WHEN am.state = 'draft' AND am.spa_invoice_kind = 'membership'
                                    THEN NULL
                                ELSE COALESCE(am.invoice_date_due, am.invoice_date)
                              END AS due_date
                 ) dd
                 WHERE am.move_type = 'out_invoice'
                   AND (am.state = 'posted'
                        OR (am.state = 'draft' AND am.spa_invoice_kind IN ('membership', 'renewal', 'upgrade')))
                   AND am.amount_residual_signed > 0
                 GROUP BY am.spa_membership_id
            )
            SELECT m.id,
                   m.name,
                   m.id AS membership_id,
                   m.partner_id,
                   m.plan_id,
                   m.period_id,
                   m.company_id,
                   rc.currency_id,
                   m.state,
                   m.date_start,
                   m.date_end,
                   m.grace_until,
                   CASE WHEN m.state IN ('active', 'grace') AND per.months > 0
                        THEN per.price / per.months ELSE 0 END AS mrr,
                   COALESCE(d.amount_due, 0) AS amount_due,
                   COALESCE(d.amount_overdue, 0) AS amount_overdue,
                   d.oldest_due AS oldest_due_date,
                   CASE WHEN d.oldest_due < p.today THEN p.today - d.oldest_due ELSE 0 END AS days_overdue,
                   CASE WHEN d.membership_id IS NULL THEN 'none'
                        WHEN d.oldest_due IS NULL OR d.oldest_due >= p.today THEN 'current'
                        WHEN p.today - d.oldest_due <= 30 THEN '1_30'
                        WHEN p.today - d.oldest_due <= 60 THEN '31_60'
                        WHEN p.today - d.oldest_due <= 90 THEN '61_90'
                        ELSE '90_plus' END AS aging
              FROM spa_membership m
             CROSS JOIN params p
              JOIN res_company rc ON rc.id = m.company_id
              LEFT JOIN spa_plan_period per ON per.id = m.period_id
              LEFT JOIN due d ON d.membership_id = m.id
        """, tz=tz)

    def action_open_membership(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'spa.membership',
            'res_id': self.membership_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
