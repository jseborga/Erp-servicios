# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

from .spa_report_occupancy import BOOKED_STATES


class SpaReportDashboard(models.TransientModel):
    """Tablero «Resumen» del spa: indicadores del día y del mes con acceso a cada reporte.

    Los indicadores se calculan al abrir o actualizar la pantalla con unas pocas consultas
    agrupadas (sin recorrer registros), para las compañías seleccionadas por el usuario.
    """
    _name = 'spa.report.dashboard'
    _description = 'Resumen del spa'
    _transient_max_hours = 12.0

    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company,
                                 readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    as_of = fields.Datetime('Actualizado', compute='_compute_kpis')
    today = fields.Date('Hoy', compute='_compute_kpis')
    # Hoy
    people_inside = fields.Integer('Personas dentro', compute='_compute_kpis')
    capacity_total = fields.Integer('Aforo de los espacios operativos', compute='_compute_kpis')
    occupancy_now = fields.Float('Ocupación ahora (%)', compute='_compute_kpis', digits=(16, 1))
    bookings_today = fields.Integer('Reservas de hoy', compute='_compute_kpis')
    payments_pending = fields.Integer('Pagos por validar', compute='_compute_kpis')
    payments_pending_amount = fields.Monetary('Monto por validar', compute='_compute_kpis')
    # Socios
    members_active = fields.Integer('Socios activos', compute='_compute_kpis')
    members_grace = fields.Integer('Socios en gracia', compute='_compute_kpis')
    members_suspended = fields.Integer('Socios suspendidos', compute='_compute_kpis')
    members_new = fields.Integer('Socios nuevos del mes', compute='_compute_kpis')
    members_overdue = fields.Integer('Socios en mora', compute='_compute_kpis')
    amount_overdue = fields.Monetary('Deuda vencida', compute='_compute_kpis')
    # Ingresos
    mrr = fields.Monetary('Ingreso mensual recurrente', compute='_compute_kpis',
                          help='Suma de precio del período / meses de las membresías activas o en gracia.')
    revenue_month = fields.Monetary('Ingresos del mes', compute='_compute_kpis',
                                    help='Ingreso devengado del mes (sin impuestos): facturas, devengo de '
                                         'planes prepagados y ventas del POS.')
    # CRM
    leads_month = fields.Integer('Prospectos del mes', compute='_compute_kpis')
    leads_won = fields.Integer('Convertidos (de los prospectos del mes)', compute='_compute_kpis')
    conversion_rate = fields.Float('Conversión del mes (%)', compute='_compute_kpis', digits=(16, 1))

    def _compute_display_name(self):
        # Migas de pan legibles («Resumen del spa» en vez de «spa.report.dashboard,7»).
        for dashboard in self:
            dashboard.display_name = self.env._('Resumen del spa')

    # ------------------------------------------------------------------
    # Fechas
    # ------------------------------------------------------------------
    @api.model
    def _spa_ranges(self):
        """Hoy y el mes en curso (hora local del spa), como fechas y como límites UTC."""
        tools = self.env['spa.tools']
        today = tools.local_today()
        month_start, month_end = tools.month_bounds(today)
        return {
            'today': today,
            'day_from': tools.local_combine(today, 0.0),
            'day_to': tools.local_combine(today + timedelta(days=1), 0.0),
            'month_start': month_start,
            'month_end': month_end,
            'month_from': tools.local_combine(month_start, 0.0),
            'month_to': tools.local_combine(month_end + timedelta(days=1), 0.0),
        }

    @api.model
    def _spa_company_domain(self, field='company_id', allow_empty=False):
        domain = Domain(field, 'in', self.env.companies.ids)
        return domain | Domain(field, '=', False) if allow_empty else domain

    # ------------------------------------------------------------------
    # Indicadores
    # ------------------------------------------------------------------
    @api.model
    def _spa_kpi_values(self):
        r = self._spa_ranges()
        company = self._spa_company_domain()
        values = {'today': r['today'], 'as_of': fields.Datetime.now()}

        [(inside,)] = self.env['spa.access.log']._read_group(
            company & Domain('state', '=', 'open'), [], ['people:sum'])
        [(capacity,)] = self.env['spa.space']._read_group(
            company & Domain('state', '=', 'active'), [], ['capacity:sum'])
        values.update(people_inside=inside or 0, capacity_total=capacity or 0,
                      occupancy_now=100.0 * (inside or 0) / capacity if capacity else 0.0)

        values['bookings_today'] = self.env['spa.booking'].search_count(
            company & Domain('state', 'in', BOOKED_STATES)
            & Domain('start', '>=', r['day_from']) & Domain('start', '<', r['day_to']))

        [(pending_count, pending_amount)] = self.env['spa.payment.request']._read_group(
            company & Domain('state', '=', 'pending'), [], ['__count', 'amount:sum'])
        values.update(payments_pending=pending_count, payments_pending_amount=pending_amount or 0.0)

        Membership = self.env['spa.membership']
        by_state = dict(Membership._read_group(
            company & Domain('state', 'in', ('active', 'grace', 'suspended')), ['state'], ['__count']))
        values.update(members_active=by_state.get('active', 0), members_grace=by_state.get('grace', 0),
                      members_suspended=by_state.get('suspended', 0))
        values['members_new'] = Membership.search_count(
            company & Domain('state', 'not in', ('draft', 'cancelled'))
            & Domain('date_start', '>=', r['month_start']) & Domain('date_start', '<=', r['month_end']))
        mrr = 0.0
        for period, count in Membership._read_group(
                company & Domain('state', 'in', ('active', 'grace')), ['period_id'], ['__count']):
            if period.months:
                mrr += count * period.price / period.months
        values['mrr'] = mrr

        [(overdue_amount, overdue_count)] = self.env['spa.report.member']._read_group(
            company & Domain('days_overdue', '>', 0), [], ['amount_overdue:sum', '__count'])
        values.update(amount_overdue=overdue_amount or 0.0, members_overdue=overdue_count)

        [(revenue,)] = self.env['spa.report.revenue']._read_group(
            company & Domain('date', '>=', r['month_start']) & Domain('date', '<=', r['month_end']),
            [], ['amount_recognized:sum'])
        values['revenue_month'] = revenue or 0.0

        leads = dict(self.env['crm.lead'].with_context(active_test=False)._read_group(
            self._spa_leads_domain(r), ['won_status'], ['__count']))
        total = sum(leads.values())
        values.update(leads_month=total, leads_won=leads.get('won', 0),
                      conversion_rate=100.0 * leads.get('won', 0) / total if total else 0.0)
        return values

    @api.model
    def _spa_leads_domain(self, ranges=None):
        r = ranges or self._spa_ranges()
        return (self._spa_company_domain(allow_empty=True)
                & Domain('spa_pipeline', '=', 'acquisition')
                & Domain('create_date', '>=', r['month_from']) & Domain('create_date', '<', r['month_to']))

    def _compute_kpis(self):
        values = self._spa_kpi_values()
        for dashboard in self:
            dashboard.update(values)

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    @api.model
    def action_open_dashboard(self):
        dashboard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Resumen del spa'),
            'res_model': self._name,
            'res_id': dashboard.id,
            'view_mode': 'form',
            'views': [(self.env.ref('spa_reports.spa_report_dashboard_view_form').id, 'form')],
            'target': 'current',
        }

    def action_refresh(self):
        # Nuevo registro (los transitorios se depuran) sin apilar migas de pan.
        return dict(self.action_open_dashboard(), target='main')

    def _spa_window(self, name, model, domain=None, views=('list', 'form'), context=None):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': ','.join(views),
            'views': [(False, view) for view in views],
            'domain': list(domain or []),
            'context': context or {},
            'target': 'current',
        }

    def _spa_report_action(self, xmlid, name=None, domain=None, context=None):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        if name:
            action['name'] = name
        if domain is not None:
            action['domain'] = list(domain)
        if context is not None:
            action['context'] = context
        return action

    def action_view_occupancy(self):
        return self._spa_report_action(
            'spa_reports.spa_report_occupancy_action', name=self.env._('Ocupación de hoy'),
            context={'search_default_filter_today': 1, 'search_default_filter_open': 1})

    def action_view_inside(self):
        return self._spa_report_action('spa_access.spa_access_log_open_action')

    def action_view_bookings_today(self):
        r = self._spa_ranges()
        return self._spa_window(
            self.env._('Reservas de hoy'), 'spa.booking',
            [('state', 'in', list(BOOKED_STATES)),
             ('start', '>=', fields.Datetime.to_string(r['day_from'])),
             ('start', '<', fields.Datetime.to_string(r['day_to']))],
            views=('list', 'calendar', 'form'))

    def action_view_payments(self):
        return self._spa_report_action('spa_billing.spa_payment_request_action')

    def _spa_member_action(self, name, domain, context=None):
        return self._spa_report_action('spa_reports.spa_report_member_action', name=name, domain=domain,
                                       context=context or {})

    def action_view_members_active(self):
        return self._spa_member_action(self.env._('Socios activos'), [('state', '=', 'active')])

    def action_view_members_grace(self):
        return self._spa_member_action(self.env._('Socios en gracia'), [('state', '=', 'grace')])

    def action_view_members_suspended(self):
        return self._spa_member_action(self.env._('Socios suspendidos'), [('state', '=', 'suspended')])

    def action_view_members_overdue(self):
        return self._spa_member_action(self.env._('Socios en mora'), [('days_overdue', '>', 0)])

    def action_view_mrr(self):
        action = self._spa_member_action(self.env._('Ingreso mensual recurrente por plan'),
                                         [('state', 'in', ['active', 'grace'])],
                                         context={'pivot_measures': ['mrr', '__count'],
                                                  'pivot_row_groupby': ['plan_id']})
        action['views'] = sorted(action['views'], key=lambda view: view[1] != 'pivot')
        return action

    def action_view_members_new(self):
        r = self._spa_ranges()
        return self._spa_window(
            self.env._('Socios nuevos del mes'), 'spa.membership',
            [('state', 'not in', ['draft', 'cancelled']),
             ('date_start', '>=', fields.Date.to_string(r['month_start'])),
             ('date_start', '<=', fields.Date.to_string(r['month_end']))])

    def action_view_revenue_month(self):
        r = self._spa_ranges()
        return self._spa_report_action(
            'spa_reports.spa_report_revenue_action', name=self.env._('Ingresos del mes'),
            domain=[('date', '>=', fields.Date.to_string(r['month_start'])),
                    ('date', '<=', fields.Date.to_string(r['month_end']))], context={})

    def action_view_leads(self):
        r = self._spa_ranges()
        domain = [('spa_pipeline', '=', 'acquisition'),
                  ('create_date', '>=', fields.Datetime.to_string(r['month_from'])),
                  ('create_date', '<', fields.Datetime.to_string(r['month_to']))]
        return self._spa_report_action('spa_crm.crm_lead_action_spa_conversion',
                                       name=self.env._('Prospectos del mes'), domain=domain,
                                       context={'active_test': False})
