# Part of ERP Servicios Spa. License LGPL-3.
"""La demo cargada al instalar es consistente: estados, contabilidad, saldos, reportes y accesos.

Se ejecutan sobre la base donde se instaló ``spa_demo`` (post_install). Si la demo no se cargó
(p. ej. la base ya tenía operaciones) las pruebas se omiten.
"""
import unittest

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.l10n_bo_purchase.tools import siat
from odoo.addons.spa_demo.demo import SpaDemoBuilder, data


class SpaDemoMixin:

    @classmethod
    def _demo_setup(cls):
        if not cls.env['ir.config_parameter'].sudo().get_param(data.DEMO_PARAM):
            raise unittest.SkipTest('La demo no está cargada en esta base.')
        cls.company = cls.env.company
        cls.members = cls.env['spa.membership'].search([('partner_id.name', '=like', 'Demo – %')])
        cls.users = {login: cls.env['res.users'].search([('login', '=', login)])
                     for _role, login, _name, _phone in data.STAFF}
        # Fin del día de la carga: lo posterior es «futuro» en la historia de la demo.
        loaded_on = fields.Date.to_date(cls.env['ir.config_parameter'].sudo().get_param(data.DEMO_PARAM))
        cls.loaded_end = cls.env['spa.tools'].local_combine(loaded_on, 23.99)

    @classmethod
    def _acc(cls, xmlid):
        return cls.env['account.chart.template'].with_company(cls.company).ref(xmlid)

    def _balance(self, account):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('company_id', '=', self.company.id), ('parent_state', '=', 'posted')])
        return round(sum(lines.mapped('balance')), 2)


@tagged('post_install', '-at_install', 'spa', 'spa_demo')
class TestSpaDemo(SpaDemoMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._demo_setup()

    def test_01_loaded_once(self):
        """La carga es idempotente: una segunda llamada no crea nada."""
        count = self.env['spa.membership'].search_count([])
        moves = self.env['account.move'].search_count([])
        self.assertFalse(SpaDemoBuilder(self.env).load())
        self.assertEqual(self.env['spa.membership'].search_count([]), count)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.company.name, 'Spa Demo Bolivia')

    def test_02_membership_states(self):
        self.assertGreaterEqual(len(self.members), 25)
        by_state = {state: len(self.members.filtered(lambda m, s=state: m.state == s))
                    for state in ('draft', 'active', 'grace', 'suspended', 'expired', 'cancelled')}
        for state, count in by_state.items():
            self.assertGreaterEqual(count, 1, 'Falta una membresía en estado %s: %s' % (state, by_state))
        self.assertGreaterEqual(by_state['active'], 12)
        periods = self.members.filtered(lambda m: m.state == 'active').period_id.mapped('months')
        self.assertTrue({1, 3, 12} <= set(periods), 'Activos mensuales, trimestrales y anuales')
        self.assertTrue(self.members.freeze_ids.filtered(lambda f: f.state == 'active'), 'Un socio congelado')
        self.assertTrue(self.members.filtered('spa_next_plan_id'), 'Una bajada de plan programada')
        self.assertTrue(self.members.invoice_ids.filtered(lambda m: m.spa_invoice_kind == 'upgrade'
                                                          and m.payment_state in ('paid', 'in_payment')))
        installments = self.members.invoice_ids.filtered(lambda m: m.spa_offer_id.offer_type == 'installments')
        self.assertEqual(installments.payment_state, 'partial', 'Plan anual en cuotas con la primera pagada')
        # Todos ficticios.
        for partner in self.members.partner_id:
            self.assertTrue(partner.name.startswith('Demo – '), partner.name)
            self.assertTrue(partner.email.endswith('@' + data.EMAIL_DOMAIN), partner.email)
            self.assertTrue((partner.phone or '').replace(' ', '').startswith('+5917000'), partner.phone)

    def test_03_accounting_is_balanced(self):
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT m.name, SUM(l.debit) - SUM(l.credit)
              FROM account_move m JOIN account_move_line l ON l.move_id = m.id
             WHERE m.state = 'posted'
          GROUP BY m.id, m.name
            HAVING ABS(SUM(l.debit) - SUM(l.credit)) > 0.001
        """)
        self.assertEqual(self.env.cr.fetchall(), [])
        posted = self.env['account.move'].search([('state', '=', 'posted'), ('company_id', '=', self.company.id)])
        self.assertGreater(len(posted), 100)
        # Balance de comprobación del contador (OCA): suma cero.
        accountant = self.users['contador.demo']
        dates = posted.mapped('date')
        wizard = self.env['trial.balance.report.wizard'].with_user(accountant).create({
            'date_from': min(dates), 'date_to': max(dates), 'target_move': 'posted',
            'hide_account_at_0': True, 'company_id': self.company.id})
        report = self.env['report.account_financial_report.trial_balance'].with_user(
            accountant)._get_report_values(wizard, wizard._prepare_report_data())
        accounts = [row for row in report['trial_balance'] if row.get('type') == 'account_type']
        self.assertAlmostEqual(sum(row['ending_balance'] for row in accounts), 0.0, places=2)
        # 215100 Ingresos diferidos = devengo aún no reconocido; hay devengos contabilizados.
        deferred = self._acc('l10n_bo_spa_2151')
        lines = self.env['spa.deferral.line'].search([('company_id', '=', self.company.id)])
        planned = lines.filtered(lambda line: line.state == 'planned')
        self.assertTrue(lines.filtered(lambda line: line.state == 'posted'))
        self.assertAlmostEqual(self._balance(deferred), -round(sum(planned.mapped('amount')), 2), places=2)
        # Ninguna factura cobrada queda con saldo de redondeo.
        dust = posted.filtered(lambda m: m.move_type == 'out_invoice' and 0 < m.amount_residual <= 0.011)
        self.assertFalse(dust, dust.mapped('name'))

    def test_04_entitlements_and_ledger(self):
        entitlements = self.env['spa.entitlement'].search([('membership_id', 'in', self.members.ids)])
        self.assertTrue(entitlements)
        for entitlement in entitlements.filtered(lambda e: not e.unlimited):
            self.assertLessEqual(entitlement.used, entitlement.granted + entitlement.carried_in,
                                 '%s %s' % (entitlement.membership_id.name, entitlement.display_name))
            self.assertEqual(entitlement.used, sum(entitlement.consumption_ids.mapped('qty')))
        bookings = self.env['spa.booking'].search([('partner_id.name', '=like', 'Demo – %')])
        states = set(bookings.mapped('state'))
        self.assertTrue({'done', 'confirmed', 'late_cancel', 'no_show', 'cancelled'} <= states, states)
        self.assertTrue(bookings.filtered(lambda b: b.state == 'confirmed' and b.start > self.loaded_end),
                        'Reservas de los próximos días')
        for booking in bookings.filtered(lambda b: b.state == 'done' and b.payment_mode == 'membership'):
            self.assertEqual(sum(booking.consumption_ids.mapped('qty')), 1, booking.name)
        guests = self.env['spa.guest'].search([('membership_id', 'in', self.members.ids)])
        self.assertEqual(set(guests.mapped('charge_type')), {'free_pass', 'fee'})
        self.assertTrue(guests.lead_id, 'Los invitados entran al CRM')
        passes = self.env['spa.courtesy.pass'].search([('guest_name', '=like', 'Demo – %')])
        self.assertTrue({'issued', 'redeemed', 'expired'} <= set(passes.mapped('state')))

    def test_05_billing_and_crm(self):
        requests = self.env['spa.payment.request'].search([('partner_id.name', '=like', 'Demo – %')])
        self.assertTrue(requests.filtered(lambda r: r.state == 'validated'))
        pending = requests.filtered(lambda r: r.state == 'pending')
        self.assertTrue(pending)
        self.assertTrue(all(request.receipt for request in pending.filtered(lambda r: r.channel == 'portal')))
        renewals = self.members.invoice_ids.filtered(lambda m: m.spa_invoice_kind == 'renewal' and m.state == 'draft')
        self.assertTrue(renewals, 'Renovaciones pendientes de cobro')
        logs = self.env['spa.dunning.log'].search([('membership_id', 'in', self.members.ids)])
        self.assertTrue({'notify', 'suspend'} <= set(logs.mapped('action')))
        Lead = self.env['crm.lead'].with_context(active_test=False)
        acquisition = Lead.search([('spa_pipeline', '=', 'acquisition')])
        self.assertGreaterEqual(len(acquisition.source_id), 5, 'Prospectos de varias fuentes')
        codes = set(acquisition.stage_id.mapped('spa_stage_code'))
        self.assertTrue({'interested', 'visit', 'proposal', 'member'} <= codes, codes)
        self.assertTrue(acquisition.filtered(lambda lead: lead.won_status == 'lost'))
        retention = Lead.search([('spa_pipeline', '=', 'retention')])
        self.assertTrue({'grace', 'suspended', 'expired'} <= set(retention.mapped('spa_risk_reason')))
        # SIAT: solo el simulador (nada se presenta como factura real).
        self.assertEqual(self.company.l10n_bo_siat_mode, 'provider')
        self.assertTrue(self.company.l10n_bo_siat_provider_id.is_simulated)
        accepted = self.env['account.move'].search([('l10n_bo_siat_state', '=', 'accepted')])
        self.assertTrue(accepted)
        self.assertTrue(all(move.l10n_bo_siat_simulated and move.l10n_bo_siat_cuf.startswith('SIMULADO')
                            for move in accepted))

    def test_06_purchases_petty_cash_pos_rentals_classes(self):
        bills = self.env['account.move'].search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted')])
        with_doc = bills.filtered(lambda m: m.l10n_bo_doc_type in ('siat_online', 'dosificacion'))
        self.assertGreaterEqual(len(with_doc), 6)
        for bill in with_doc.filtered(lambda m: m.l10n_bo_doc_type == 'siat_online'):
            decoded = siat.decode_cuf(bill.l10n_bo_cuf, nit=bill.l10n_bo_supplier_nit)
            self.assertTrue(decoded, bill.name)
            self.assertEqual(siat.normalize_nit(decoded['nit']), siat.normalize_nit(bill.l10n_bo_supplier_nit))
        without = bills.filtered(lambda m: m.l10n_bo_doc_type == 'none')
        self.assertEqual(set(without.mapped('l10n_bo_withholding_mode')), {'supplier_bears', 'company_bears'})
        self.env.flush_all()
        self.assertTrue(self.env['l10n_bo.purchase.book'].search_count([('move_id', 'in', with_doc.ids)]))
        # Fondo fijo: una rendición aprobada (repuesta) y otra por aprobar; la cuenta en su monto fijo.
        fund = self.env['l10n_bo.petty.cash.fund'].search([('name', '=like', 'Demo – %')])
        self.assertEqual(len(fund), 1)
        reports = self.env['l10n_bo.petty.cash.report'].search([('fund_id', '=', fund.id)])
        self.assertEqual(set(reports.mapped('state')), {'approved', 'submitted'})
        self.assertAlmostEqual(self._balance(fund.account_id), fund.amount_fixed)
        # POS: dos sesiones cerradas con unas 40 órdenes y consumos cargados a la cuenta del socio.
        sessions = self.env['pos.session'].search([('state', '=', 'closed')])
        self.assertGreaterEqual(len(sessions), 2)
        self.assertGreaterEqual(len(sessions.order_ids), 36)
        self.assertTrue(sessions.order_ids.account_move.filtered(lambda m: m.spa_invoice_kind == 'pos'))
        self.assertTrue(sessions.order_ids.filtered(lambda o: o.pricelist_id.id in self.env['spa.plan'].search(
            []).pricelist_id.ids), 'Descuentos de socio')
        # Eventos: uno realizado, cobrado y con garantía devuelta; otro confirmado a futuro.
        rentals = self.env['spa.rental'].search([('event_name', '=like', 'Demo – %')])
        done = rentals.filtered(lambda r: r.state == 'done')
        self.assertTrue(done)
        self.assertEqual(done.invoice_status, 'paid')
        self.assertEqual(done.deposit_state, 'settled')
        self.assertAlmostEqual(done.deposit_refunded, done.deposit_received)
        self.assertTrue(rentals.filtered(lambda r: r.state == 'confirmed' and r.start > self.loaded_end))
        # Clases: horario activo con sesiones e inscripciones.
        template = self.env.ref('spa_rental.class_template_swim')
        self.assertTrue(template.active)
        enrollments = self.env['spa.class.enrollment'].search([('template_id', '=', template.id)])
        self.assertTrue({'attended', 'enrolled'} <= set(enrollments.mapped('state')))

    def test_07_reports_and_roles(self):
        manager = self.users['gerente.demo']
        dashboard = self.env['spa.report.dashboard'].with_user(manager).create({})
        for fname in ('members_active', 'members_suspended', 'mrr', 'payments_pending', 'amount_overdue',
                      'members_overdue'):
            self.assertGreater(dashboard[fname], 0, fname)
        for model in ('spa.report.member', 'spa.report.revenue', 'spa.report.occupancy', 'spa.report.plan.usage',
                      'spa.report.plan.profitability', 'spa.report.area.move', 'l10n_bo.sale.book',
                      'l10n_bo.purchase.book'):
            records = self.env[model].with_user(manager).search([], limit=50)
            self.assertTrue(records, model)
            records.read([name for name, field in records._fields.items() if field.store][:15])
        expected = {
            'gerente.demo': 'spa_base.group_spa_manager', 'recepcion.demo': 'spa_base.group_spa_reception',
            'caja.demo': 'spa_base.group_spa_cashier', 'terapeuta.demo': 'spa_base.group_spa_therapist',
            'marketing.demo': 'spa_base.group_spa_marketing', 'compras.demo': 'l10n_bo_purchase.group_spa_buyer',
            'contador.demo': 'l10n_bo_purchase.group_spa_accountant',
            'custodio.demo': 'l10n_bo_petty_cash.group_petty_cash_custodian',
            'mesero.demo': 'point_of_sale.group_pos_user',
        }
        for login, group in expected.items():
            self.assertTrue(self.users[login].has_group(group), login)
        # La masajista ve solo sus sesiones.
        therapist = self.users['terapeuta.demo']
        visible = self.env['spa.booking'].with_user(therapist).search([])
        self.assertTrue(visible)
        self.assertEqual(visible.employee_id.user_id, therapist)


@tagged('post_install', '-at_install', 'spa', 'spa_demo')
class TestSpaDemoPortal(SpaDemoMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._demo_setup()

    def test_portal_member_sees_own_data(self):
        for login, name in (('ana.demo', 'Ana Rojas'), ('bruno.demo', 'Bruno Salinas'),
                            ('carla.demo', 'Carla Méndez')):
            self.authenticate(login, data.DEMO_PASSWORD)
            response = self.url_open('/my/spa')
            self.assertEqual(response.status_code, 200, login)
            self.assertIn(name, response.text)
        self.authenticate('yolanda.demo', data.DEMO_PASSWORD)
        response = self.url_open('/my/spa')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Yolanda Paredes', response.text)
