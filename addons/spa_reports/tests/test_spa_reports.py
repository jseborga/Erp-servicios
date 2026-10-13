# Part of ERP Servicios Spa. License LGPL-3.
from collections import defaultdict
from datetime import timedelta
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.mis_builder.models.accounting_none import AccountingNone
from odoo.addons.spa_membership.tests.common import SpaCommon

REPORT_MODELS = [
    'spa.report.occupancy',
    'spa.report.plan.usage',
    'spa.report.plan.profitability',
    'spa.report.revenue',
    'spa.report.member',
    'spa.report.area.move',
]


def _num(value):
    if value is None or value is AccountingNone:
        return 0.0
    return float(value)


def _section(code):
    for prefix, section in (('41', 'income'), ('51', 'direct_cost'), ('52', 'selling'), ('53', 'admin')):
        if code.startswith(prefix):
            return section
    if code.startswith('4'):
        return 'other_income'
    if code.startswith('5'):
        return 'other_expense'
    return 'other'


@tagged('post_install', '-at_install', 'spa')
class TestSpaReports(SpaCommon):
    """Escenario pequeño y comprobación de cada reporte contra los datos de origen."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.chart = cls.env['account.chart.template']
        cls.Request = cls.env['spa.payment.request']
        cls.Booking = cls.env['spa.booking']
        cls.AccessLog = cls.env['spa.access.log']
        Partner = cls.env['res.partner']

        # Valores previos (el escenario se compara por diferencia).
        cls.kpi_before = cls.env['spa.report.dashboard']._spa_kpi_values()
        cls.mis_before = cls._mis_values()

        cls.partner_b = Partner.create({'name': 'Bruno Mora (prueba)', 'phone': '+59170000002'})
        cls.partner_c = Partner.create({'name': 'Carla de paso (prueba)', 'phone': '+59170000003'})
        cls.partner_d = Partner.create({'name': 'Diego Anual (prueba)', 'phone': '+59170000004'})
        cls.partner_e = Partner.create({'name': 'Elena Gracia (prueba)', 'phone': '+59170000005'})

        # Costos de servir (Costo del producto de cada servicio).
        cls.massage.product_id.standard_price = 100.0
        cls.jacuzzi.product_id.standard_price = 20.0
        cls.pool.product_id.standard_price = 5.0

        # CRM: un prospecto de Ana (se gana al activar su membresía) y otro sin convertir.
        team = cls.env.ref('spa_crm.team_acquisition')
        cls.lead_won = cls.env['crm.lead'].create({
            'name': 'Ana quiere ser socia', 'type': 'opportunity', 'team_id': team.id,
            'partner_id': cls.partner.id})
        cls.lead_open = cls.env['crm.lead'].create({
            'name': 'Consulta por WhatsApp', 'type': 'opportunity', 'team_id': team.id,
            'contact_name': 'Prospecto (prueba)', 'phone': '+59170000099'})

        # A: Premium mensual pagado.
        cls.mem_a = cls._membership(cls.plan_premium, activate=False)
        cls.inv_a = cls.mem_a.action_create_invoice()
        cls._pay(cls.inv_a)
        # B: Básica mensual con factura impaga vencida hace 40 días.
        cls.mem_b = cls._membership(cls.plan_basic, partner=cls.partner_b, activate=False)
        cls.inv_b = cls.mem_b.action_create_invoice(post=False)
        overdue_date = cls.today - timedelta(days=40)
        cls.inv_b.write({'invoice_date': overdue_date, 'invoice_date_due': overdue_date})
        cls.inv_b.action_post()
        # D: Básica anual pagada (ingreso diferido, primer devengo contabilizado).
        cls.mem_d = cls._membership(cls.plan_basic, months=12, partner=cls.partner_d, activate=False)
        cls.inv_d = cls.mem_d.action_create_invoice()
        cls._pay(cls.inv_d)
        cls.env['spa.deferral.line']._cron_post_deferrals()
        cls.deferral_d = cls.mem_d.deferral_line_ids.filtered(lambda line: line.state == 'posted')
        # E: Básica mensual en gracia.
        cls.mem_e = cls._membership(cls.plan_basic, partner=cls.partner_e)
        cls.mem_e.state = 'grace'
        # Pago informado por validar de B.
        cls.request_b = cls.Request.create({
            'partner_id': cls.partner_b.id, 'membership_id': cls.mem_b.id, 'invoice_id': cls.inv_b.id,
            'amount': 100.0, 'method': 'transfer', 'reference': 'TRX-REP'})

        # C: masaje suelto pagado al reservar (cobro pendiente → factura al cobrar, área Spa y masajes).
        cls.booking_c = cls.Booking.create({
            'partner_id': cls.partner_c.id, 'payment_mode': 'single', 'service_id': cls.massage.id,
            'start': cls._dt_cls(cls.today + timedelta(days=2), 11.0)})
        cls.booking_c.action_confirm()
        cls.inv_c = cls.booking_c.invoice_id
        cls._pay(cls.inv_c)

        # Consumos de A en el mes: 1 masaje, 2 jacuzzi, 3 piscina (ilimitada).
        now = fields.Datetime.now()
        cls.mem_a._spa_consume(cls.massage, now, 'booking')
        cls.mem_a._spa_consume(cls.jacuzzi, now, 'booking', qty=2)
        cls.mem_a._spa_consume(cls.pool, now, 'checkin', qty=3)

        # Ocupación hace 3 días: jacuzzi (aforo 5) y sauna (aforo 5, acceso libre).
        cls.day0 = cls.today - timedelta(days=3)
        jacuzzi_vals = {'service_id': cls.jacuzzi.id, 'payment_mode': 'single'}
        cls.Booking.create([
            dict(jacuzzi_vals, partner_id=cls.partner.id, start=cls._dt_cls(cls.day0, 10.0), state='done'),
            dict(jacuzzi_vals, partner_id=cls.partner_c.id, start=cls._dt_cls(cls.day0, 10.0), state='checked_in'),
            dict(jacuzzi_vals, partner_id=cls.partner_b.id, start=cls._dt_cls(cls.day0, 10.0), state='cancelled'),
            dict(jacuzzi_vals, partner_id=cls.partner.id, start=cls._dt_cls(cls.day0, 12.5), state='confirmed'),
        ])
        cls.sauna_space = cls.sauna.space_id
        cls.AccessLog.create({
            'partner_id': cls.partner.id, 'membership_id': cls.mem_a.id, 'space_id': cls.sauna_space.id,
            'people': 2, 'check_in': cls._dt_cls(cls.day0, 15.0 + 20 / 60.0),
            'check_out': cls._dt_cls(cls.day0, 16.0 + 10 / 60.0), 'state': 'closed'})
        # Hoy: E está dentro de la sauna con 2 invitados; A reservó piscina a las 19:00.
        cls.AccessLog.create({
            'partner_id': cls.partner_e.id, 'membership_id': cls.mem_e.id, 'space_id': cls.sauna_space.id,
            'people': 3, 'check_in': now, 'state': 'open'})
        cls.booking_today = cls.Booking.create({
            'partner_id': cls.partner.id, 'membership_id': cls.mem_a.id, 'service_id': cls.pool.id,
            'start': cls._dt_cls(cls.today, 19.0), 'state': 'confirmed'})

        # Cafetería: una venta sin factura y otra facturada a C (cliente sin membresía).
        cls.pos_order = cls._pos_cash_order()
        cls.partner_c.vat = '7654321'
        cls.pos_invoiced = cls._pos_cash_order(partner=cls.partner_c, to_invoice=True)
        cls.pos_invoice = cls.pos_invoiced.account_move

        # Gastos con área: luz repartida 60/40, contador 100 % administración, publicidad 50/50.
        cls.area_pis = cls.env.ref('l10n_bo_spa.analytic_area_piscina')
        cls.area_saj = cls.env.ref('l10n_bo_spa.analytic_area_sauna_jacuzzi')
        cls.area_spa = cls.env.ref('l10n_bo_spa.analytic_area_spa')
        cls.area_adm = cls.env.ref('l10n_bo_spa.analytic_area_administracion')
        journal = cls.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cls.company.id)], limit=1)
        cls.entry = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': cls.today,
            'ref': 'Gastos del mes (prueba)',
            'line_ids': [
                Command.create({'account_id': cls.chart.ref('l10n_bo_spa_5121').id, 'debit': 1000.0,
                                'name': 'Electricidad', 'analytic_distribution': {
                                    str(cls.area_pis.id): 60, str(cls.area_saj.id): 40}}),
                Command.create({'account_id': cls.chart.ref('l10n_bo_spa_53017').id, 'debit': 500.0,
                                'name': 'Honorarios contables', 'analytic_distribution': {
                                    str(cls.area_adm.id): 100}}),
                Command.create({'account_id': cls.chart.ref('l10n_bo_spa_52061').id, 'debit': 200.0,
                                'name': 'Publicidad', 'analytic_distribution': {
                                    str(cls.area_pis.id): 50, str(cls.area_spa.id): 50}}),
                Command.create({'account_id': cls.chart.ref('l10n_bo_spa_1115').id, 'credit': 1700.0,
                                'name': 'Pagos'}),
            ],
        })
        cls.entry.action_post()
        cls.scenario_moves = (cls.inv_a | cls.inv_b | cls.inv_c | cls.inv_d | cls.deferral_d.move_id | cls.entry
                              | cls.pos_invoice)
        # Ingresos de membresías con área (reparto del plan): facturas mensuales y devengo de prepagados.
        cls.membership_moves = cls.inv_a | cls.inv_b | cls.deferral_d.move_id
        cls.env.flush_all()

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    @classmethod
    def _dt_cls(cls, day, hour):
        return cls.tools.local_combine(day, hour)

    @classmethod
    def _pay(cls, invoice):
        request = cls.Request.create({
            'partner_id': invoice.partner_id.id, 'membership_id': invoice.spa_membership_id.id,
            'invoice_id': invoice.id, 'amount': invoice.amount_residual, 'method': 'qr', 'reference': 'QR-1'})
        request.action_validate()
        return request

    @classmethod
    def _pos_cash_order(cls, partner=None, to_invoice=False):
        config = cls.env['pos.config']._spa_get_config('cafe')
        if not config.current_session_id:
            config.open_ui()
            config.current_session_id.set_opening_control(0, None)
        session = config.current_session_id
        product = cls.env.ref('spa_pos.product_coffee')
        pricelist = config.pricelist_id
        price = pricelist._get_product_price(product, 2) if pricelist else product.lst_price
        taxes = product.taxes_id.filtered(lambda t: t.company_id == cls.company)
        amounts = taxes.compute_all(price, session.currency_id, 2, product=product)
        cash = config.payment_method_ids.filtered('is_cash_count')[:1]
        now = fields.Datetime.to_string(fields.Datetime.now())
        result = cls.env['pos.order'].sync_from_ui([{
            'uuid': str(uuid4()),
            'session_id': session.id,
            'user_id': cls.env.user.id,
            'partner_id': partner.id if partner else False,
            'pricelist_id': pricelist.id if pricelist else False,
            'fiscal_position_id': False,
            'date_order': now,
            'lines': [Command.create({
                'product_id': product.id, 'qty': 2, 'price_unit': price, 'discount': 0.0,
                'price_subtotal': amounts['total_excluded'], 'price_subtotal_incl': amounts['total_included'],
                'tax_ids': [Command.set(taxes.ids)]})],
            'payment_ids': [Command.create({'amount': amounts['total_included'], 'name': now,
                                            'payment_method_id': cash.id})],
            'amount_total': amounts['total_included'],
            'amount_tax': amounts['total_included'] - amounts['total_excluded'],
            'amount_paid': amounts['total_included'],
            'amount_return': 0.0,
            'to_invoice': to_invoice,
            'last_order_preparation_change': '{}',
        }])
        return cls.env['pos.order'].browse(result['pos.order'][0]['id'])

    @classmethod
    def _mis_values(cls):
        """{(kpi, columna): valor} de la instancia MIS «Estado de resultados por área»."""
        instance = cls.env.ref('spa_reports.mis_instance_area_pl')
        matrix = instance._compute_matrix()
        values = {}
        for row in matrix.iter_rows():
            if row.account_id:
                continue
            for col in matrix.iter_cols():
                cells = col.get_cell_tuple_for_row(row)
                values[(row.kpi.name, col.label)] = _num(cells[0].val if cells and cells[0] else None)
        return values

    def _income(self, invoices):
        """Ingreso sin impuestos de las líneas de producto que van a cuentas de ingreso."""
        lines = invoices.line_ids.filtered(
            lambda l: l.display_type == 'product' and l.account_id.account_type in ('income', 'income_other'))
        return -sum(lines.mapped('balance'))

    def _analytic(self, moves, area, prefix):
        """Suma de apuntes analíticos del ``area`` en cuentas que empiezan con ``prefix``."""
        column = self.env['spa.report.area.move']._area_column()
        lines = self.env['account.analytic.line'].search([
            ('move_line_id.move_id', 'in', moves.ids), (column, '=', area.id)])
        return sum(lines.filtered(lambda l: l.general_account_id.code.startswith(prefix)).mapped('amount'))

    def _it_spa(self):
        """IT (3 %) imputado al área Spa y masajes (cuentas 52): masaje suelto y parte de las membresías."""
        return -self._analytic(self.inv_c | self.membership_moves, self.area_spa, '52')

    def _untaxed(self, invoices):
        return -sum(invoices.line_ids.filtered(lambda l: l.display_type == 'product').mapped('balance'))

    # ------------------------------------------------------------------
    # Pruebas
    # ------------------------------------------------------------------
    def test_all_views_and_reports_load(self):
        """Cada reporte se lee, se agrupa y sus vistas se cargan sin errores de SQL."""
        for model in REPORT_MODELS:
            Report = self.env[model]
            rows = Report.search_read([], limit=5)
            self.assertTrue(rows, f'{model} debería tener filas con el escenario')
            groupable = [name for name, field in Report._fields.items()
                         if field.type in ('many2one', 'selection') and field.store and name != 'company_id'][:2]
            for groupby in groupable:
                self.assertTrue(Report._read_group([], [groupby], ['__count']))
            Report.get_views([(False, 'list'), (False, 'pivot'), (False, 'graph'), (False, 'search')])
        dashboard = self.env['spa.report.dashboard'].create({})
        dashboard.get_views([(False, 'form')])
        self.assertTrue(dashboard.read(list(dashboard._fields)))

    def test_occupancy(self):
        Occupancy = self.env['spa.report.occupancy']
        jacuzzi_space = self.jacuzzi.space_id
        day = [('date', '=', self.day0)]
        rows = {row.hour: row for row in Occupancy.search(day + [('space_id', '=', jacuzzi_space.id)])}
        # Horario 10:00-20:00: una fila por hora aunque no haya movimiento.
        self.assertEqual(sorted(rows), ['%02d' % h for h in range(10, 20)])
        self.assertTrue(all(row.is_open and row.capacity == 5 for row in rows.values()))
        self.assertEqual(rows['10'].booked_seats, 2, 'Hecha + en curso; la cancelada no cuenta')
        self.assertAlmostEqual(rows['10'].occupancy_pct, 40.0)
        self.assertEqual(rows['10'].free_seats, 3)
        self.assertEqual(rows['11'].booked_seats, 0)
        self.assertEqual(rows['12'].booked_seats, 1, '12:30-13:30 ocupa las horas 12 y 13')
        self.assertEqual(rows['13'].booked_seats, 1)
        self.assertEqual(rows['10'].weekday, str(self.day0.isoweekday()))
        # Promedio del día: (40 + 20 + 20) / 10 horas.
        [(avg_pct, booked)] = Occupancy._read_group(
            day + [('space_id', '=', jacuzzi_space.id)], [], ['occupancy_pct:avg', 'booked_seats:sum'])
        self.assertAlmostEqual(avg_pct, 8.0)
        self.assertEqual(booked, 4)
        # Sauna (acceso libre): ingreso 15:20, salida 16:10, 2 personas.
        sauna = {row.hour: row for row in Occupancy.search(day + [('space_id', '=', self.sauna_space.id)])}
        self.assertEqual(sauna['15'].checkin_people, 2)
        self.assertEqual(sauna['15'].present_people, 2)
        self.assertEqual(sauna['16'].checkin_people, 0)
        self.assertEqual(sauna['16'].present_people, 2)
        self.assertEqual(sauna['17'].present_people, 0)
        self.assertAlmostEqual(sauna['16'].occupancy_pct, 40.0)
        # Hoy: E dentro de la sauna con 2 invitados.
        today_sauna = Occupancy._read_group(
            [('date', '=', self.today), ('space_id', '=', self.sauna_space.id)], [], ['checkin_people:sum'])
        self.assertGreaterEqual(today_sauna[0][0], 3)

    def test_plan_usage(self):
        Usage = self.env['spa.report.plan.usage']
        rows = {row.service_id: row for row in Usage.search([('membership_id', '=', self.mem_a.id)])}
        massage, jacuzzi, pool = rows[self.massage], rows[self.jacuzzi], rows[self.pool]
        self.assertEqual((massage.available, massage.used, massage.remaining), (4, 1, 3))
        self.assertAlmostEqual(massage.utilization, 25.0)
        self.assertEqual((jacuzzi.available, jacuzzi.used, jacuzzi.remaining), (5, 2, 3))
        self.assertAlmostEqual(jacuzzi.utilization, 40.0)
        self.assertTrue(pool.unlimited)
        self.assertEqual((pool.available, pool.used), (0, 3))
        self.assertFalse(pool.utilization)
        self.assertEqual(massage.plan_id, self.plan_premium)
        self.assertEqual(massage.month, self.tools.month_bounds(self.today)[0])
        # Promedio del plan: solo los servicios con cupo (ilimitados sin %).
        [(avg,)] = Usage._read_group([('membership_id', '=', self.mem_a.id)], [], ['utilization:avg'])
        self.assertAlmostEqual(avg, 32.5)
        # La entidad de origen coincide.
        entitlements = self.mem_a.entitlement_ids
        self.assertEqual(sum(rows[e.service_id].used for e in entitlements), sum(entitlements.mapped('used')))

    def test_plan_profitability(self):
        Profit = self.env['spa.report.plan.profitability']
        row_a = Profit.search([('membership_id', '=', self.mem_a.id)])
        self.assertEqual(len(row_a), 1, 'Una fila por socio y mes')
        self.assertAlmostEqual(row_a.revenue, 890.0)
        self.assertAlmostEqual(row_a.service_cost, 1 * 100.0 + 2 * 20.0 + 3 * 5.0)
        self.assertAlmostEqual(row_a.margin, 890.0 - 155.0)
        self.assertAlmostEqual(row_a.margin_pct, 100.0 * 735.0 / 890.0, places=2)
        self.assertEqual(row_a.uses, 6)
        self.assertEqual((row_a.sessions_available, row_a.sessions_used), (9, 3))
        self.assertAlmostEqual(row_a.utilization, 100.0 / 3, places=2)
        row_d = Profit.search([('membership_id', '=', self.mem_d.id)])
        self.assertAlmostEqual(row_d.revenue, 4590.0 / 12, places=2)
        self.assertEqual(row_d.uses, 0)
        groups = dict((plan, revenue) for plan, revenue in Profit._read_group(
            [('membership_id', 'in', (self.mem_a | self.mem_d | self.mem_e).ids)], ['plan_id'], ['revenue:sum']))
        self.assertAlmostEqual(groups[self.plan_basic], 4590.0 / 12 + 450.0, places=2)

    def test_revenue(self):
        Revenue = self.env['spa.report.revenue']

        def totals(domain):
            [(invoiced, recognized)] = Revenue._read_group(
                domain, [], ['amount_invoiced:sum', 'amount_recognized:sum'])
            return invoiced, recognized

        # Alta mensual: facturado = devengado.
        invoiced, recognized = totals([('move_id', '=', self.inv_a.id)])
        self.assertAlmostEqual(invoiced, self._untaxed(self.inv_a))
        self.assertAlmostEqual(recognized, invoiced)
        self.assertGreater(invoiced, 0)
        row = Revenue.search([('move_id', '=', self.inv_a.id)], limit=1)
        self.assertEqual((row.kind, row.plan_id, row.source), ('membership', self.plan_premium, 'invoice'))
        # Anual: se factura todo a diferidos y se devenga 1/12 por mes.
        invoiced, recognized = totals([('move_id', '=', self.inv_d.id)])
        self.assertAlmostEqual(invoiced, self._untaxed(self.inv_d))
        self.assertAlmostEqual(recognized, 0.0)
        self.assertEqual(len(self.deferral_d), 1)
        deferral = Revenue.search([('source', '=', 'deferral'), ('membership_id', '=', self.mem_d.id)])
        self.assertEqual(len(deferral), 1)
        self.assertAlmostEqual(deferral.amount_recognized, self.deferral_d.amount)
        self.assertEqual(deferral.kind, 'membership')
        self.assertEqual(deferral.account_id.code, '410110')
        # Servicio suelto con su categoría.
        row_c = Revenue.search([('move_id', '=', self.inv_c.id)])
        self.assertEqual(row_c.kind, 'single')
        self.assertEqual(row_c.categ_id, self.env.ref('l10n_bo_spa.categ_massage'))
        self.assertAlmostEqual(row_c.amount_recognized, self._income(self.inv_c))
        # POS sin factura: importe sin impuestos de las líneas.
        pos_rows = Revenue.search([('source', '=', 'pos'), ('date', '=', self.today)])
        pos_untaxed = sum(self.pos_order.lines.mapped('price_subtotal'))
        self.assertGreater(pos_untaxed, 0)
        self.assertAlmostEqual(sum(pos_rows.mapped('amount_recognized')), pos_untaxed)
        self.assertTrue(all(r.kind == 'pos' for r in pos_rows))
        # POS facturado: sale como factura, tipo restaurante y cafetería, sin duplicar la orden.
        self.assertTrue(self.pos_invoice)
        pos_invoice_rows = Revenue.search([('move_id', '=', self.pos_invoice.id)])
        self.assertTrue(pos_invoice_rows)
        self.assertEqual(set(pos_invoice_rows.mapped('kind')), {'pos'})
        self.assertEqual(set(pos_invoice_rows.mapped('source')), {'invoice'})
        self.assertAlmostEqual(sum(pos_invoice_rows.mapped('amount_recognized')), self._income(self.pos_invoice))
        self.assertAlmostEqual(sum(pos_rows.mapped('amount_recognized')) + sum(
            pos_invoice_rows.mapped('amount_recognized')), pos_untaxed + self._income(self.pos_invoice))
        # Por tipo: la suma de cada tipo coincide con sus documentos.
        by_kind = dict((kind, recognized) for kind, recognized in Revenue._read_group(
            [('partner_id', 'in', (self.partner | self.partner_b | self.partner_c | self.partner_d).ids)],
            ['kind'], ['amount_recognized:sum']))
        self.assertAlmostEqual(by_kind['membership'], self._income(self.inv_a | self.inv_b) + self.deferral_d.amount)
        self.assertAlmostEqual(by_kind['single'], self._income(self.inv_c))

    def test_members_and_overdue(self):
        Member = self.env['spa.report.member']
        row_b = Member.search([('membership_id', '=', self.mem_b.id)])
        self.assertEqual(self.inv_b.invoice_date_due, self.today - timedelta(days=40))
        self.assertAlmostEqual(row_b.amount_due, self.inv_b.amount_residual)
        self.assertAlmostEqual(row_b.amount_overdue, 450.0)
        self.assertEqual(row_b.days_overdue, 40)
        self.assertEqual(row_b.aging, '31_60')
        self.assertEqual(row_b.oldest_due_date, self.today - timedelta(days=40))
        row_a = Member.search([('membership_id', '=', self.mem_a.id)])
        self.assertEqual((row_a.state, row_a.aging, row_a.days_overdue), ('active', 'none', 0))
        self.assertAlmostEqual(row_a.amount_due, 0.0)
        self.assertAlmostEqual(row_a.mrr, 890.0)
        row_e = Member.search([('membership_id', '=', self.mem_e.id)])
        self.assertEqual(row_e.state, 'grace')
        self.assertAlmostEqual(row_e.mrr, 450.0)
        self.assertAlmostEqual(Member.search([('membership_id', '=', self.mem_d.id)]).mrr, 382.5)
        self.assertAlmostEqual(Member.search([('membership_id', '=', self.mem_b.id)]).mrr, 0.0, msg='Por activar')
        # Pivote por estado y plan = conteo de membresías.
        mine = (self.mem_a | self.mem_b | self.mem_d | self.mem_e)
        groups = Member._read_group([('membership_id', 'in', mine.ids)], ['state', 'plan_id'], ['__count'])
        expected = defaultdict(int)
        for membership in mine:
            expected[(membership.state, membership.plan_id)] += 1
        self.assertEqual({(state, plan): count for state, plan, count in groups}, dict(expected))
        # Orden por mora: B primero entre los del escenario.
        ordered = Member.search([('membership_id', 'in', mine.ids)])
        self.assertEqual(ordered[0].membership_id, self.mem_b)
        self.assertEqual(row_b.action_open_membership()['res_id'], self.mem_b.id)

    def test_overdue_includes_pending_renewal(self):
        """Una renovación impaga aún sin factura (cobro pendiente) cuenta como mora desde el vencimiento."""
        Member = self.env['spa.report.member']
        partner_f = self.env['res.partner'].create({'name': 'Fabio Renueva (prueba)', 'phone': '+59170000006'})
        mem_f = self._membership(self.plan_premium, partner=partner_f, activate=False)
        self._pay(mem_f.action_create_invoice())
        mem_f.write({'date_end': self.today - timedelta(days=10), 'state': 'grace'})
        renewal = mem_f.action_create_invoice()
        self.assertEqual((renewal.state, renewal.spa_invoice_kind), ('draft', 'renewal'))
        self.env.flush_all()
        row_f = Member.search([('membership_id', '=', mem_f.id)])
        self.assertAlmostEqual(row_f.amount_due, 890.0)
        self.assertAlmostEqual(row_f.amount_overdue, 890.0)
        self.assertEqual(row_f.days_overdue, 10)
        self.assertEqual(row_f.oldest_due_date, self.today - timedelta(days=10))
        self.assertEqual(row_f.aging, '1_30')
        # Alta pendiente (oferta aún no pagada): saldo por cobrar, sin mora.
        partner_g = self.env['res.partner'].create({'name': 'Gina Prospecto (prueba)', 'phone': '+59170000007'})
        mem_g = self._membership(self.plan_basic, partner=partner_g, activate=False)
        mem_g.action_create_invoice()
        self.env.flush_all()
        row_g = Member.search([('membership_id', '=', mem_g.id)])
        self.assertEqual((row_g.amount_due, row_g.days_overdue, row_g.aging), (450.0, 0, 'current'))
        # Al pagar, se emite la factura y sale de la mora.
        self._pay(renewal)
        self.env.flush_all()
        self.env.invalidate_all()  # filas del reporte SQL ya leídas
        row_f = Member.search([('membership_id', '=', mem_f.id)])
        self.assertEqual((row_f.amount_due, row_f.days_overdue, row_f.aging), (0.0, 0, 'none'))

    def test_area_profitability(self):
        Area = self.env['spa.report.area.move']
        column = Area._area_column()
        self.assertTrue(column and column.startswith('x_plan'))
        lines = self.env['account.analytic.line'].search(
            [('move_line_id.move_id', 'in', self.scenario_moves.ids), (column, '!=', False)])
        expected = defaultdict(float)
        for line in lines:
            expected[(line[column].id, _section(line.general_account_id.code))] += line.amount
        got = {(area.id, section): amount for area, section, amount in Area._read_group(
            [('move_id', 'in', self.scenario_moves.ids)], ['area_id', 'section'], ['amount:sum'])}
        self.assertEqual(set(got), set(expected))
        for key, amount in expected.items():
            self.assertAlmostEqual(got[key], amount, msg=f'Área/sección {key}')
        # Reparto del asiento de gastos.
        self.assertAlmostEqual(got[(self.area_pis.id, 'direct_cost')], -600.0)
        self.assertAlmostEqual(got[(self.area_saj.id, 'direct_cost')], -400.0)
        self.assertAlmostEqual(got[(self.area_adm.id, 'admin')], -500.0)
        # Publicidad 100 + IT (3 %) de las ventas con área (membresías según el reparto del plan).
        it_pool = -self._analytic(self.membership_moves, self.area_pis, '52')
        self.assertGreater(it_pool, 0)
        self.assertAlmostEqual(got[(self.area_pis.id, 'selling')], -100.0 - it_pool, places=2)
        # Spa y masajes: publicidad 100 + IT del masaje suelto y de su parte de las membresías.
        self.assertAlmostEqual(got[(self.area_spa.id, 'selling')], -100.0 - self._it_spa(), places=2)
        # Ingresos de membresías por área: Premium (A) 40/30/30, Básica (B y devengo de D) 60/40.
        income_a, income_b = self._income(self.inv_a), self._income(self.inv_b)
        deferral = self.deferral_d.amount
        self.assertAlmostEqual(got[(self.area_pis.id, 'income')], 0.4 * income_a + 0.6 * (income_b + deferral),
                               delta=0.03)
        self.assertAlmostEqual(got[(self.area_saj.id, 'income')], 0.3 * income_a + 0.4 * (income_b + deferral),
                               delta=0.03)
        self.assertAlmostEqual(got[(self.area_spa.id, 'income')], self._income(self.inv_c) + 0.3 * income_a,
                               delta=0.03)
        # Debe/haber equivalentes al apunte contable.
        [(debit, credit, balance, amount)] = Area._read_group(
            [('move_id', '=', self.entry.id)], [], ['debit:sum', 'credit:sum', 'balance:sum', 'amount:sum'])
        self.assertAlmostEqual(debit, 1700.0)
        self.assertAlmostEqual(credit, 0.0)
        self.assertAlmostEqual(balance, -amount)
        # Acción de apuntes analíticos con la columna dinámica del plan.
        action = Area.action_open_analytic_lines()
        self.assertEqual(action['res_model'], 'account.analytic.line')
        self.assertEqual(action['context']['pivot_row_groupby'], [column])
        self.env['account.analytic.line'].search(action['domain'], limit=1)

    def test_mis_area_income_statement(self):
        after = self._mis_values()

        def delta(kpi, col):
            return after.get((kpi, col), 0.0) - self.mis_before.get((kpi, col), 0.0)

        income_spa = self._analytic(self.inv_c | self.membership_moves, self.area_spa, '41')
        income_pool = self._analytic(self.membership_moves, self.area_pis, '41')
        it_pool = -self._analytic(self.membership_moves, self.area_pis, '52')
        self.assertGreater(income_pool, 0, 'El ingreso de las membresías se reparte por área')
        self.assertAlmostEqual(delta('ingresos', 'Piscina'), income_pool, places=2)
        self.assertAlmostEqual(delta('costos_directos', 'Piscina'), 600.0)
        self.assertAlmostEqual(delta('gastos_comercializacion', 'Piscina'), 100.0 + it_pool, places=2)
        self.assertAlmostEqual(delta('resultado', 'Piscina'), income_pool - 700.0 - it_pool, places=2)
        self.assertAlmostEqual(delta('costos_directos', 'Sauna y jacuzzi'), 400.0)
        self.assertAlmostEqual(delta('ingresos', 'Spa y masajes'), income_spa, places=2)
        self.assertAlmostEqual(delta('gastos_comercializacion', 'Spa y masajes'), 100.0 + self._it_spa(), places=2)
        self.assertAlmostEqual(delta('gastos_administracion', 'Administración'), 500.0)
        self.assertAlmostEqual(delta('costos_directos', 'Total por áreas'), 1000.0)
        self.assertAlmostEqual(delta('gastos_administracion', 'Total por áreas'), 500.0)
        # Total contable = todos los apuntes del año (incluye membresías sin área).
        year_start = self.today.replace(month=1, day=1)
        income_lines = self.env['account.move.line'].search([
            ('move_id', 'in', self.scenario_moves.ids), ('parent_state', '=', 'posted'),
            ('date', '>=', year_start), ('account_id.code', '=like', '41%')])
        self.assertAlmostEqual(delta('ingresos', 'Total contable'), -sum(income_lines.mapped('balance')))
        self.assertAlmostEqual(delta('costos_directos', 'Total contable'), 1000.0)
        # Sin área = total contable − total por áreas.
        for kpi in ('ingresos', 'costos_directos', 'gastos_administracion', 'resultado'):
            self.assertAlmostEqual(after.get((kpi, 'Sin área asignada'), 0.0),
                                   after.get((kpi, 'Total contable'), 0.0) - after.get((kpi, 'Total por áreas'), 0.0),
                                   msg=kpi)
        # Las membresías (alta mensual y devengo de prepagados) ya no quedan «sin área».
        self.assertLess(delta('ingresos', 'Sin área asignada'), self._income(self.inv_a), 'Membresías con área')

    def test_dashboard(self):
        dashboard = self.env['spa.report.dashboard'].create({})
        before = self.kpi_before

        def delta(name):
            return dashboard[name] - before[name]

        self.assertEqual(delta('people_inside'), 3)
        self.assertEqual(dashboard.capacity_total, sum(self.env['spa.space'].search(
            [('state', '=', 'active')]).mapped('capacity')))
        self.assertEqual(delta('bookings_today'), 1)
        self.assertEqual(delta('payments_pending'), 1)
        self.assertAlmostEqual(delta('payments_pending_amount'), 100.0)
        self.assertEqual(delta('members_active'), 2)
        self.assertEqual(delta('members_grace'), 1)
        self.assertEqual(delta('members_suspended'), 0)
        self.assertEqual(delta('members_new'), 3)
        self.assertAlmostEqual(delta('mrr'), 890.0 + 4590.0 / 12 + 450.0, places=2)
        self.assertEqual(delta('members_overdue'), 1)
        self.assertAlmostEqual(delta('amount_overdue'), 450.0)
        pos_untaxed = sum(self.pos_order.lines.mapped('price_subtotal'))
        expected_revenue = (self._income(self.inv_a | self.inv_c | self.inv_d | self.pos_invoice)
                            + self.deferral_d.amount + pos_untaxed)
        self.assertAlmostEqual(delta('revenue_month'), expected_revenue, places=2)
        self.assertEqual(delta('leads_month'), 2)
        self.assertEqual(delta('leads_won'), 1)
        self.assertEqual(self.lead_won.won_status, 'won')
        self.assertAlmostEqual(dashboard.conversion_rate,
                               100.0 * dashboard.leads_won / dashboard.leads_month, places=2)
        # Cada indicador abre su reporte.
        for method in ('action_view_inside', 'action_view_occupancy', 'action_view_bookings_today',
                       'action_view_payments', 'action_view_members_active', 'action_view_members_grace',
                       'action_view_members_suspended', 'action_view_members_overdue', 'action_view_mrr',
                       'action_view_members_new', 'action_view_revenue_month', 'action_view_leads'):
            action = getattr(dashboard, method)()
            self.assertEqual(action['type'], 'ir.actions.act_window', method)
            self.env[action['res_model']].with_context(active_test=False).search_count(
                action.get('domain') or [])
        bookings = self.env['spa.booking'].search(dashboard.action_view_bookings_today()['domain'])
        self.assertIn(self.booking_today, bookings)
        opened = self.env['spa.report.dashboard'].action_open_dashboard()
        self.assertTrue(self.env['spa.report.dashboard'].browse(opened['res_id']).exists())

    def test_security_and_multicompany(self):
        def group(xmlid):
            return self.env.ref(xmlid).id

        Users = self.env['res.users'].with_context(no_reset_password=True)
        company2 = self.env['res.company'].create({'name': 'Spa sucursal (prueba)'})
        reception = Users.create({'name': 'Recepción (prueba)', 'login': 'recepcion.reportes',
                                  'group_ids': [Command.set([group('spa_base.group_spa_reception')])]})
        marketing = Users.create({'name': 'Marketing (prueba)', 'login': 'marketing.reportes',
                                  'group_ids': [Command.set([group('spa_base.group_spa_marketing')])]})
        manager = Users.create({'name': 'Gerente (prueba)', 'login': 'gerente.reportes',
                                'company_id': self.company.id,
                                'company_ids': [Command.set([self.company.id, company2.id])],
                                'group_ids': [Command.set([group('spa_base.group_spa_manager')])]})
        # Recepción: solo ocupación.
        self.assertTrue(self.env['spa.report.occupancy'].with_user(reception).search_count([]))
        for model in ('spa.report.revenue', 'spa.report.member', 'spa.report.plan.profitability',
                      'spa.report.area.move', 'spa.report.plan.usage'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(reception).search_count([])
        # Marketing: uso de los planes (riesgo de baja), sin datos económicos.
        self.assertTrue(self.env['spa.report.plan.usage'].with_user(marketing).search_count([]))
        with self.assertRaises(AccessError):
            self.env['spa.report.revenue'].with_user(marketing).search_count([])
        # Gerente: todo, filtrado por las compañías activas.
        for model in REPORT_MODELS:
            self.assertTrue(self.env[model].with_user(manager).search_count([]), model)
        mis = self.env.ref('spa_reports.mis_instance_area_pl').with_user(manager).compute()
        self.assertTrue(mis['body'])
        dashboard = self.env['spa.report.dashboard'].with_user(manager).create({})
        self.assertEqual(dashboard.members_active, self.env['spa.report.dashboard'].create({}).members_active)
        space2 = self.env['spa.space'].create({
            'name': 'Piscina sucursal', 'capacity': 10, 'access_mode': 'free', 'company_id': company2.id,
            'open_hour': 8.0, 'close_hour': 20.0})
        self.AccessLog.create({
            'partner_id': self.partner.id, 'space_id': space2.id, 'people': 4,
            'check_in': self._dt(self.day0, 9.0), 'check_out': self._dt(self.day0, 9.5), 'state': 'closed'})
        Occupancy = self.env['spa.report.occupancy'].with_user(manager)
        only_main = Occupancy.with_context(allowed_company_ids=[self.company.id])
        both = Occupancy.with_context(allowed_company_ids=[self.company.id, company2.id])
        self.assertFalse(only_main.search_count([('space_id', '=', space2.id)]))
        rows = both.search([('space_id', '=', space2.id), ('date', '=', self.day0), ('hour', '=', '09')])
        self.assertEqual(rows.checkin_people, 4)
        self.assertEqual(rows.company_id, company2)
