# Part of ERP Servicios Spa. License LGPL-3.
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestSpaPos(SpaCommon):
    """Restaurante y cafetería: precios de socio, cargo a cuenta, facturación y analítica.

    Las órdenes se crean con ``pos.order.sync_from_ui``, la misma llamada que hace la interfaz
    del POS al validar el pago; los precios de las líneas se calculan con la lista de precios del
    cliente, como lo hace la interfaz.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        PosConfig = cls.env['pos.config']
        cls.restaurant = PosConfig._spa_get_config('restaurant')
        cls.cafe = PosConfig._spa_get_config('cafe')
        cls.coffee = cls.env.ref('spa_pos.product_coffee')
        cls.salad = cls.env.ref('spa_pos.product_salad')
        cls.trout = cls.env.ref('spa_pos.product_trout')
        cls.cash_restaurant = cls.env.ref('spa_pos.pm_cash_restaurant')
        cls.cash_cafe = cls.env.ref('spa_pos.pm_cash_cafe')
        cls.qr = cls.env.ref('spa_pos.pm_qr')
        cls.member_account = cls.env.ref('spa_pos.pm_member_account')
        cls.public_pricelist = cls.env.ref('spa_membership.pricelist_public')
        cls.area_restaurant = cls.env.ref('l10n_bo_spa.analytic_area_restaurante')
        cls.area_cafe = cls.env.ref('l10n_bo_spa.analytic_area_cafeteria')
        cls.income_account = cls.env['account.chart.template'].ref('l10n_bo_spa_41015')
        cls.plan_premium.pos_credit_limit = 300.0
        cls.plan_vip.pos_credit_limit = 1000.0
        cls.plan_basic.pos_credit_limit = 0.0
        cls.stranger = cls.env['res.partner'].create({'name': 'Cliente sin plan (prueba)', 'vat': '1234567'})
        cls.cashier = cls.env['res.users'].create({
            'name': 'Cajera (prueba)',
            'login': 'cajera.pos.prueba',
            'email': 'cajera.pos@example.com',
            'group_ids': [Command.set([cls.env.ref('spa_base.group_spa_cashier').id])],
        })
        # Cajero solo del POS (sin grupos del spa).
        cls.pos_user = cls.env['res.users'].create({
            'name': 'Mesero cajero (prueba)',
            'login': 'mesero.pos.prueba',
            'group_ids': [Command.set([cls.env.ref('base.group_user').id,
                                       cls.env.ref('point_of_sale.group_pos_user').id])],
        })

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _open(self, config):
        if not config.current_session_id:
            config.open_ui()
            config.current_session_id.set_opening_control(0, None)
        return config.current_session_id

    def _ui_pricelist(self, config, partner):
        """Lista de precios que la interfaz del POS asigna al elegir al cliente."""
        if partner and partner.property_product_pricelist in config.available_pricelist_ids:
            return partner.property_product_pricelist
        return config.pricelist_id

    def _ui_order(self, config, lines, partner=None, payments=None, pricelist=None, user=None):
        """Simula el pago de una orden en la interfaz del POS (``sync_from_ui``)."""
        session = self._open(config)
        currency = session.currency_id
        pricelist = pricelist or self._ui_pricelist(config, partner)
        order_lines, total, untaxed = [], 0.0, 0.0
        for product, qty in lines:
            price = pricelist._get_product_price(product, qty) if pricelist else product.lst_price
            taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company)
            amounts = taxes.compute_all(price, currency, qty, product=product, partner=partner)
            total += amounts['total_included']
            untaxed += amounts['total_excluded']
            order_lines.append(Command.create({
                'product_id': product.id,
                'qty': qty,
                'price_unit': price,
                'discount': 0.0,
                'price_subtotal': amounts['total_excluded'],
                'price_subtotal_incl': amounts['total_included'],
                'tax_ids': [Command.set(taxes.ids)],
            }))
        cash = config.payment_method_ids.filtered('is_cash_count')
        payments = payments or [(cash, total)]
        now = fields.Datetime.to_string(fields.Datetime.now())
        data = {
            'uuid': str(uuid4()),
            'session_id': session.id,
            'user_id': (user or self.env.user).id,
            'partner_id': partner.id if partner else False,
            'pricelist_id': pricelist.id if pricelist else False,
            'fiscal_position_id': False,
            'date_order': now,
            'lines': order_lines,
            'payment_ids': [Command.create({'amount': amount, 'name': now, 'payment_method_id': method.id})
                            for method, amount in payments],
            'amount_total': total,
            'amount_tax': total - untaxed,
            'amount_paid': sum(amount for _method, amount in payments),
            'amount_return': 0.0,
            'to_invoice': False,
            'last_order_preparation_change': '{}',
        }
        result = self.env['pos.order'].with_user(user or self.env.user).sync_from_ui([data])
        return self.env['pos.order'].browse(result['pos.order'][0]['id'])

    def _close(self, session):
        cash = session.order_ids.payment_ids.filtered(lambda p: p.payment_method_id.is_cash_count)
        session.post_closing_cash_details(sum(cash.mapped('amount')))
        result = session.close_session_from_ui()
        self.assertTrue(result.get('successful'), result)
        self.assertEqual(session.state, 'closed')
        return session.move_id

    def _assert_balanced(self, move):
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')), places=2)

    def _area_lines(self, move_lines, area):
        column = area.plan_id._column_name()
        return self.env['account.analytic.line'].search([('move_line_id', 'in', move_lines.ids)]) \
            .filtered(lambda line: line[column] == area)

    def _assert_refused(self, config, lines, partner, payments, message, pricelist=None, user=None):
        with self.assertRaisesRegex(UserError, message), self.env.cr.savepoint():
            self._ui_order(config, lines, partner=partner, payments=payments, pricelist=pricelist, user=user)

    # ------------------------------------------------------------------
    # Configuración inicial
    # ------------------------------------------------------------------
    def test_setup_creates_restaurant_and_cafe(self):
        self.assertTrue(self.restaurant.module_pos_restaurant)
        self.assertEqual(len(self.restaurant.floor_ids), 1)
        self.assertEqual(len(self.restaurant.floor_ids.table_ids), 8)
        self.assertFalse(self.cafe.module_pos_restaurant)
        self.assertFalse(self.cafe.floor_ids)
        self.assertEqual(self.restaurant.spa_analytic_account_id, self.area_restaurant)
        self.assertEqual(self.cafe.spa_analytic_account_id, self.area_cafe)
        for config, cash in ((self.restaurant, self.cash_restaurant), (self.cafe, self.cash_cafe)):
            self.assertEqual(config.payment_method_ids, cash | self.qr | self.member_account)
            self.assertTrue(config.use_pricelist)
            self.assertEqual(config.pricelist_id, self.public_pricelist)
            self.assertIn(self.plan_premium.pricelist_id, config.available_pricelist_ids)
            self.assertIn(self.plan_vip.pricelist_id, config.available_pricelist_ids)
        self.assertEqual(self.cash_restaurant.journal_id.type, 'cash')
        self.assertNotEqual(self.cash_restaurant.journal_id, self.cash_cafe.journal_id)
        self.assertEqual(self.qr.type, 'bank')
        self.assertEqual(self.member_account.type, 'pay_later')
        self.assertTrue(self.member_account.split_transactions)
        self.assertEqual(self.coffee.taxes_id, self.company._spa_sale_taxes())
        self.assertTrue(self.env['res.groups']._is_feature_enabled('product.group_product_pricelist'))
        # Idempotente: volver a ejecutarlo no duplica nada.
        counts = (self.env['pos.config'].search_count([]), self.env['pos.payment.method'].search_count([]),
                  self.env['restaurant.table'].search_count([]))
        self.env['pos.config']._spa_setup_company(self.company)
        self.assertEqual(counts, (self.env['pos.config'].search_count([]),
                                  self.env['pos.payment.method'].search_count([]),
                                  self.env['restaurant.table'].search_count([])))

    def test_post_init_waits_for_chart_on_new_database(self):
        """En una base nueva el plan contable se carga al final: el POS se crea después."""
        from odoo.addons.spa_pos import _spa_pos_post_init
        calls = []
        registry = self.env.registry
        registry._auto_install_template = lambda env: calls.append('chart')
        try:
            with patch.object(type(self.env['pos.config']), '_spa_setup_all_companies',
                              lambda self: calls.append('pos')):
                _spa_pos_post_init(self.env)
                self.assertEqual(calls, [])
                registry._auto_install_template(self.env)
        finally:
            del registry._auto_install_template
        self.assertEqual(calls, ['chart', 'pos'])

    def test_member_label_loaded_in_pos(self):
        self._membership(self.plan_premium)
        self.assertEqual(self.partner.spa_pos_member_label, 'Premium · Activa')
        self.assertTrue(self.partner.spa_pos_member_live)
        self.assertFalse(self.stranger.spa_pos_member_label)
        fields_loaded = self.env['res.partner']._load_pos_data_fields(self.restaurant)
        self.assertIn('spa_pos_member_label', fields_loaded)
        self.assertIn('vat', fields_loaded)  # búsqueda por CI/NIT del estándar
        session = self._open(self.restaurant)
        # El cajero del POS no lee membresías, pero ve el plan y estado del socio.
        data = self.env['res.partner'].with_user(self.pos_user)._load_pos_data_read(
            self.partner.with_user(self.pos_user), session.config_id)
        self.assertEqual(data[0]['spa_pos_member_label'], 'Premium · Activa')

    # ------------------------------------------------------------------
    # Descuento por plan y cierre con analítica
    # ------------------------------------------------------------------
    def test_premium_discount_and_restaurant_closing(self):
        self._membership(self.plan_premium)
        premium = self.plan_premium.pricelist_id
        self.assertEqual(self.partner.property_product_pricelist, premium)
        self.assertEqual(self.stranger.property_product_pricelist, self.public_pricelist)

        order = self._ui_order(self.restaurant, [(self.coffee, 1), (self.salad, 1)], partner=self.partner)
        self.assertEqual(order.state, 'paid')
        self.assertEqual(order.pricelist_id, premium)
        self.assertEqual(order.lines.mapped('price_unit'), [13.5, 40.5])  # 10 % sobre 15 y 45
        self.assertAlmostEqual(order.amount_total, 54.0, places=2)
        stranger_order = self._ui_order(self.restaurant, [(self.coffee, 1)], partner=self.stranger)
        self.assertAlmostEqual(stranger_order.amount_total, 15.0, places=2)

        move = self._close(order.session_id)
        self._assert_balanced(move)
        income = move.line_ids.filtered(lambda l: l.account_id == self.income_account)
        self.assertTrue(income)
        # 13,50 + 40,50 + 15,00 = 69,00 con IVA incluido; ingreso neto ≈ 87 % (± redondeo del IVA).
        self.assertAlmostEqual(-sum(income.mapped('balance')), 69.0 * 0.87, delta=0.02)
        self.assertTrue(all(line.analytic_distribution == {str(self.area_restaurant.id): 100.0}
                            for line in income))
        analytic = self._area_lines(income, self.area_restaurant)
        self.assertAlmostEqual(sum(analytic.mapped('amount')), -sum(income.mapped('balance')), places=2)
        self.assertFalse(self._area_lines(income, self.area_cafe))

    def test_cafe_closing_uses_cafe_area(self):
        order = self._ui_order(self.cafe, [(self.coffee, 2)], partner=self.stranger,
                               payments=[(self.qr, 30.0)])
        self.assertEqual(order.state, 'paid')
        move = self._close(order.session_id)
        self._assert_balanced(move)
        income = move.line_ids.filtered(lambda l: l.account_id == self.income_account)
        analytic = self._area_lines(income, self.area_cafe)
        self.assertAlmostEqual(sum(analytic.mapped('amount')), 26.1, places=2)

    def test_member_pricelist_only_for_its_members(self):
        premium = self.plan_premium.pricelist_id
        # El cajero elige a mano la lista Premium para un cliente sin plan o de otro plan.
        self._assert_refused(self.restaurant, [(self.coffee, 1)], self.stranger, None, 'solo para socios',
                             pricelist=premium)
        self._membership(self.plan_vip)
        self._assert_refused(self.restaurant, [(self.coffee, 1)], self.partner, None, 'solo para socios',
                             pricelist=premium)
        # El socio VIP sí paga con la lista VIP que le asigna el POS (15 %).
        order = self._ui_order(self.restaurant, [(self.coffee, 1)], partner=self.partner)
        self.assertNotEqual(order.pricelist_id, premium)
        self.assertAlmostEqual(order.amount_total, 12.75, places=2)

    def test_new_plan_pricelist_added_to_pos(self):
        pricelist = self.env['product.pricelist'].create({'name': 'Socios Corporativos (prueba)'})
        self.plan_basic.pricelist_id = pricelist
        self.assertIn(pricelist, self.restaurant.available_pricelist_ids)
        self.assertIn(pricelist, self.cafe.available_pricelist_ids)

    # ------------------------------------------------------------------
    # Cargo a la cuenta del socio
    # ------------------------------------------------------------------
    def test_member_account_invoice_paid_from_portal_request(self):
        membership = self._membership(self.plan_premium)
        order = self._ui_order(self.cafe, [(self.coffee, 2)], partner=self.partner,
                               payments=[(self.member_account, 27.0)])
        invoice = order.account_move
        self.assertTrue(invoice, 'El cargo a la cuenta del socio debe facturarse.')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.spa_invoice_kind, 'pos')
        self.assertEqual(invoice.spa_membership_id, membership)
        self.assertEqual(invoice.partner_id, self.partner)
        self.assertAlmostEqual(invoice.amount_residual, 27.0, places=2)
        product_lines = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertEqual(product_lines.account_id, self.income_account)
        self.assertEqual(product_lines.analytic_distribution, {str(self.area_cafe.id): 100.0})
        self.assertAlmostEqual(sum(self._area_lines(product_lines, self.area_cafe).mapped('amount')),
                               23.49, places=2)
        # La web del socio lista las facturas abiertas con tipo de cobro del spa.
        open_invoices = self.env['account.move'].search([
            ('partner_id', '=', self.partner.id), ('spa_invoice_kind', '!=', False),
            ('state', '=', 'posted'), ('payment_state', 'not in', ('paid', 'reversed'))])
        self.assertIn(invoice, open_invoices)
        self.assertAlmostEqual(self.partner._spa_pos_open_debt(self.company), 27.0, places=2)

        # El socio informa el pago (QR) y caja lo valida.
        request = self.env['spa.payment.request'].create({
            'partner_id': self.partner.id, 'membership_id': membership.id, 'invoice_id': invoice.id,
            'amount': invoice.amount_residual, 'method': 'qr', 'channel': 'portal', 'reference': 'QR-POS-1'})
        request.with_user(self.cashier).action_validate()
        self.assertEqual(request.state, 'validated')
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        self.assertAlmostEqual(invoice.amount_residual, 0.0, places=2)
        self.assertAlmostEqual(self.partner._spa_pos_open_debt(self.company), 0.0, places=2)
        self.assertEqual(membership.state, 'active')

        session = order.session_id
        self._close(session)
        if session.move_id:
            self._assert_balanced(session.move_id)

    def test_member_account_by_pos_only_cashier(self):
        membership = self._membership(self.plan_vip)
        order = self._ui_order(self.restaurant, [(self.trout, 1)], partner=self.partner,
                               payments=[(self.member_account, 72.25)], user=self.pos_user)
        self.assertEqual(order.user_id, self.pos_user)
        self.assertEqual(order.account_move.spa_invoice_kind, 'pos')
        self.assertEqual(order.account_move.spa_membership_id, membership)
        self.assertAlmostEqual(order.account_move.amount_residual, 72.25, places=2)  # 15 % sobre 85
        self._assert_refused(self.restaurant, [(self.salad, 1)], self.stranger, [(self.member_account, 45.0)],
                             'no tiene una membresía vigente', user=self.pos_user)

    def test_member_account_refused(self):
        lines = [(self.trout, 1)]  # Bs 85 (Premium: 76,50)
        # Cliente sin membresía.
        self._assert_refused(self.restaurant, lines, self.stranger, [(self.member_account, 85.0)],
                             'no tiene una membresía vigente')
        # Sin cliente en la orden.
        self._assert_refused(self.restaurant, lines, None, [(self.member_account, 85.0)], 'seleccione al socio')
        # Plan sin crédito (Básica).
        basic_partner = self.env['res.partner'].create({'name': 'Socio Básica (prueba)'})
        self._membership(self.plan_basic, partner=basic_partner)
        self._assert_refused(self.restaurant, lines, basic_partner, [(self.member_account, 85.0)],
                             'no permite cargar consumos')
        # Socio Premium: límite de crédito con la deuda pendiente.
        membership = self._membership(self.plan_premium)
        self.plan_premium.pos_credit_limit = 150.0
        first = self._ui_order(self.restaurant, lines, partner=self.partner,
                               payments=[(self.member_account, 76.5)])
        # Con el redondeo "por impuesto" de la compañía, la factura de 76,50 puede salir en 76,51
        # (IVA 13 % incluido de tipo división, ver el informe); la deuda es lo que dice la factura.
        invoice = first.account_move
        self.assertAlmostEqual(invoice.amount_total, 76.5, delta=0.011)
        self.assertAlmostEqual(invoice.amount_residual, invoice.amount_total, places=2)
        self._assert_refused(self.restaurant, lines, self.partner, [(self.member_account, 76.5)],
                             'supera el crédito disponible')
        # Pago mixto dentro del crédito: 70 a cuenta y el resto en efectivo.
        mixed = self._ui_order(self.restaurant, lines, partner=self.partner,
                               payments=[(self.member_account, 70.0), (self.cash_restaurant, 6.5)])
        self.assertAlmostEqual(mixed.account_move.amount_residual, mixed.account_move.amount_total - 6.5,
                               places=2)
        # Socio suspendido.
        membership.action_suspend()
        self._assert_refused(self.restaurant, [(self.coffee, 1)], self.partner, [(self.member_account, 15.0)],
                             'no tiene una membresía vigente')
        self._close(first.session_id)
