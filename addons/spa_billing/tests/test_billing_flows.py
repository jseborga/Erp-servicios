# Part of ERP Servicios Spa. License LGPL-3.
"""Cobro al cobrar (Ley 843 art. 4 b), permisos por rol, devengo, escalera de cobranza, cuotas,
analítica por área y cambio de plan."""
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import freeze_time, new_test_user, tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestBillingFlows(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Membership = cls.env['spa.membership']
        cls.Request = cls.env['spa.payment.request']
        cls.Message = cls.env['spa.message']
        cls.Log = cls.env['spa.dunning.log']
        cls.chart = cls.env['account.chart.template']
        cls.company = cls.env.company
        cls.reception = new_test_user(cls.env, login='bill_reception', name='Recepción (cobros)',
                                      groups='base.group_user,spa_base.group_spa_reception')
        cls.marketing = new_test_user(cls.env, login='bill_marketing', name='Marketing (cobros)',
                                      groups='base.group_user,spa_base.group_spa_marketing')
        cls.cashier = new_test_user(cls.env, login='bill_cashier', name='Caja (cobros)',
                                    groups='base.group_user,spa_base.group_spa_cashier')
        cls.manager = new_test_user(cls.env, login='bill_manager', name='Gerente (cobros)',
                                    groups='base.group_user,spa_base.group_spa_manager')
        cls.accountant = new_test_user(cls.env, login='bill_accountant', name='Contador (cobros)',
                                       groups='base.group_user,account.group_account_user')
        cls.area_pool = cls.env.ref('l10n_bo_spa.analytic_area_piscina')
        cls.area_wet = cls.env.ref('l10n_bo_spa.analytic_area_sauna_jacuzzi')
        cls.area_spa = cls.env.ref('l10n_bo_spa.analytic_area_spa')
        cls.company.write({'spa_installment_reminder_days': 3, 'spa_installment_suspend_days': 10,
                           'spa_renewal_days': 5})

    # ------------------------------------------------------------------
    # Ayudas
    # ------------------------------------------------------------------
    def _at(self, day, hour=11):
        """Congela la hora en ``day`` (hora de La Paz, UTC-4)."""
        return freeze_time(datetime.combine(day, time(hour + 4, 0)))

    def _pay(self, invoice, amount=None, method='qr', membership=None):
        request = self.Request.with_user(self.cashier).create({
            'partner_id': invoice.partner_id.id,
            'membership_id': (membership or invoice.spa_membership_id).id,
            'invoice_id': invoice.id, 'amount': amount or invoice.amount_residual, 'method': method,
            'reference': 'TRX-%s' % invoice.id})
        request.action_validate()
        return request

    def _member(self, plan, months=1, partner=None, offer=None, pay=True, amount=None):
        membership = self._membership(plan, months=months, partner=partner, activate=False)
        invoice = membership.action_create_invoice(offer=offer)
        if pay:
            self._pay(invoice, amount=amount)
        return membership, invoice

    def _partner_new(self, name, phone):
        return self.env['res.partner'].create({'name': name, 'phone': phone})

    def _web_read(self, user, records, view_type):
        self.env.invalidate_all()
        model = records.with_user(user)
        fields_info = model.get_views([(False, view_type)])['models'][records._name]['fields']
        spec = {name: ({'fields': {'display_name': {}}} if info['type'] in ('many2one', 'one2many', 'many2many')
                       else {}) for name, info in fields_info.items()}
        return model.web_read(spec)

    def _codes(self, partner):
        return self.Message.search([('partner_id', '=', partner.id)]).mapped('template_id.code')

    def _single_booking(self, partner, day, hour=10.0, service=None):
        booking = self.env['spa.booking'].create({
            'partner_id': partner.id, 'payment_mode': 'single', 'service_id': (service or self.pool).id,
            'start': self._dt(day, hour)})
        booking.action_confirm()
        return booking

    # ------------------------------------------------------------------
    # 1-2. Recepción, marketing y caja trabajan con membresías y cobros
    # ------------------------------------------------------------------
    def test_roles_read_membership_views(self):
        monthly, _invoice = self._member(self.plan_premium)
        annual, _annual_invoice = self._member(self.plan_premium, months=12, partner=self._partner_new('Anual', '70011001'))
        self.assertTrue(annual.deferral_line_ids)
        for user in (self.reception, self.marketing):
            self._web_read(user, monthly, 'list')
            self._web_read(user, monthly, 'form')
        rows = self._web_read(self.cashier, annual, 'form')
        self.assertNotIn('deferral_line_ids', rows[0], 'Caja no ve el devengo (contabilidad)')
        # Saldo por cobrar visible para recepción, incluido el cobro de renovación pendiente.
        monthly.date_end = self.today + timedelta(days=2)
        self.Membership._cron_billing_daily()
        self.env.invalidate_all()
        self.assertAlmostEqual(monthly.with_user(self.reception).amount_due, 890.0)

    def test_reception_creates_charge_and_registers_payment(self):
        membership = self.Membership.with_user(self.reception).create({
            'partner_id': self.partner.id, 'plan_id': self.plan_premium.id,
            'period_id': self.plan_premium.period_ids.filtered(lambda p: p.months == 1).id})
        self.env.invalidate_all()
        invoice = membership.with_user(self.reception).action_create_invoice()
        self.assertEqual(invoice.state, 'draft')
        self.env.invalidate_all()
        action = membership.with_user(self.reception).action_register_payment_request()
        self.assertEqual(action['context']['default_invoice_id'], invoice.id)
        request = self.Request.with_user(self.reception).with_context(**action['context']).create(
            {'method': 'cash', 'reference': 'REC-1'})
        self.assertAlmostEqual(request.amount, 890.0)
        self.assertEqual(request.invoice_label, 'Cobro pendiente %s' % membership.name)
        self._web_read(self.reception, request, 'form')
        with self.assertRaisesRegex(UserError, 'Solo caja'):
            request.with_user(self.reception).action_validate()
        request.with_user(self.cashier).action_validate()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.invoice_date, self.today)
        self.assertEqual(membership.state, 'active')
        # Pago suelto desde la reserva («Cobrar»).
        walk_in = self._partner_new('Visitante (cobros)', '70011002')
        booking = self.env['spa.booking'].with_user(self.reception).create({
            'partner_id': walk_in.id, 'payment_mode': 'single', 'service_id': self.pool.id,
            'start': self._dt(self.today + timedelta(days=1), 10.0)})
        booking.action_confirm()
        self._web_read(self.reception, booking, 'form')
        action = booking.with_user(self.reception).action_register_payment_request()
        request = self.Request.with_user(self.reception).with_context(**action['context']).create({'reference': 'R2'})
        self.assertAlmostEqual(request.amount, booking.invoice_id.amount_total)
        request.with_user(self.cashier).action_validate()
        self.assertEqual(booking.payment_state, 'paid')

    # ------------------------------------------------------------------
    # 3. Devengo: se detiene al cancelar o revertir
    # ------------------------------------------------------------------
    def test_deferral_stops_after_cancellation_and_refund(self):
        membership, invoice = self._member(self.plan_premium, months=12)
        lines = membership.deferral_line_ids
        self.env['spa.deferral.line']._cron_post_deferrals()
        membership.with_user(self.manager).action_cancel()
        self.assertEqual(len(lines.filtered(lambda l: l.state == 'cancelled')), 11)
        self.assertTrue(membership.activity_ids, 'Aviso para devolver o reconocer el saldo diferido')
        refund = invoice.with_user(self.accountant)._reverse_moves([{'date': self.today, 'invoice_date': self.today}])
        refund.with_user(self.accountant).action_post()
        with self._at(self.today + relativedelta(months=3)):
            self.env['spa.deferral.line']._cron_post_deferrals()
        self.assertEqual(len(lines.filtered(lambda l: l.state == 'posted')), 1)
        # Devolvió todo, también el mes ya devengado: ese ingreso se revierte (Debe ingresos / Haber 215100).
        reversal = membership.deferral_line_ids.filtered(lambda l: l.state == 'reversed')
        self.assertAlmostEqual(reversal.amount, -lines.filtered(lambda l: l.state == 'posted').amount)
        self.assertTrue(all(line.refund_move_id == refund for line in lines.filtered(lambda l: l.state == 'cancelled')))
        deferred = self.Membership._spa_deferred_account(self.company)
        balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', deferred.id), ('partner_id', '=', self.partner.id),
            ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance, 0.0, places=2, msg='215100 sin saldo después de la nota de crédito')

    def test_partial_refund_reduces_pending_deferral(self):
        membership, invoice = self._member(self.plan_basic, months=12)
        self.env['spa.deferral.line']._cron_post_deferrals()
        refund = invoice._reverse_moves([{'date': self.today, 'invoice_date': self.today}])
        refund.invoice_line_ids.price_unit = invoice.invoice_line_ids.price_unit / 2
        refund.action_post()
        planned = membership.deferral_line_ids.filtered(lambda l: l.state == 'planned')
        self.assertEqual(len(planned), 11)
        deferred = self.Membership._spa_deferred_account(self.company)
        balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', deferred.id), ('partner_id', '=', self.partner.id),
            ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance, -sum(planned.mapped('amount')), places=2,
                               msg='215100 = devengo pendiente después de la devolución parcial')

    def test_full_refund_cancels_deferral_and_recognize_without_refund(self):
        partner = self._partner_new('Devuelve', '70011003')
        _membership, invoice = self._member(self.plan_basic, months=12, partner=partner)
        refund = invoice._reverse_moves([{'date': self.today, 'invoice_date': self.today}])
        refund.action_post()
        self.assertTrue(all(line.state == 'cancelled' for line in invoice._spa_deferral_lines()))
        # Desiste sin devolución: el saldo diferido se reconoce como ingreso.
        partner2 = self._partner_new('Desiste', '70011004')
        membership2, invoice2 = self._member(self.plan_basic, months=12, partner=partner2)
        membership2.action_cancel()
        cancelled = membership2.deferral_line_ids
        self.assertTrue(all(line.state == 'cancelled' for line in cancelled))
        with self.assertRaisesRegex(UserError, 'contador o el gerente'):
            cancelled.with_user(self.cashier).action_recognize_now()
        cancelled.with_user(self.manager).action_recognize_now()
        self.assertTrue(all(line.state == 'posted' for line in cancelled))
        deferred = self.Membership._spa_deferred_account(self.company)
        balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', deferred.id), ('partner_id', '=', partner2.id),
            ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance, 0.0, places=2)
        self.assertEqual(invoice2.payment_state, 'paid')

    # ------------------------------------------------------------------
    # 4. Reserva suelta: cobro pendiente, prestación, cancelación
    # ------------------------------------------------------------------
    def test_single_booking_charge_lifecycle(self):
        tomorrow = self.today + timedelta(days=1)
        a, b, c, d, e = (self._partner_new('Suelto %s' % n, '7001200%s' % n) for n in range(5))
        # Cancelada sin pago: el cobro pendiente se anula (nunca fue factura).
        draft = self._single_booking(a, tomorrow, 9.0)
        invoice = draft.invoice_id
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(draft.charge_status, 'pending')
        draft.with_user(self.reception).action_cancel()
        self.assertEqual(invoice.state, 'cancel')
        self.assertEqual(draft.charge_status, 'cancelled')
        # Ingresa sin haber pagado: se emite la factura (servicio prestado).
        served = self._single_booking(b, tomorrow, 10.0)
        served.action_check_in()
        self.assertEqual(served.invoice_id.state, 'posted')
        self.assertEqual(served.invoice_id.invoice_date, self.today)
        self.assertEqual(served.charge_status, 'invoiced')
        # Pagada y cancelada: se conserva y se avisa a caja para el reembolso.
        paid = self._single_booking(c, tomorrow, 11.0)
        self._pay(paid.invoice_id, method='cash')
        self.assertEqual(paid.charge_status, 'paid')
        paid.action_cancel()
        self.assertEqual(paid.invoice_id.payment_state, 'paid')
        self.assertIn('Reembolsar', paid.activity_ids.mapped('summary')[0])
        # Emitida (p. ej. por contabilidad) sin pago y cancelada: nota de crédito.
        legacy = self._single_booking(d, tomorrow, 12.0)
        legacy.invoice_id._spa_post_pending()
        legacy.action_cancel()
        self.assertEqual(legacy.invoice_id.payment_state, 'reversed')
        self.assertEqual(legacy.charge_status, 'cancelled')
        # No se presentó, sin pago: se anula el cobro pendiente.
        absent = self._single_booking(e, tomorrow, 13.0)
        absent.action_no_show()
        self.assertEqual(absent.invoice_id.state, 'cancel')
        with self.assertRaisesRegex(UserError, 'anulado'):
            self.Request.create({'partner_id': e.id, 'invoice_id': absent.invoice_id.id, 'amount': 10,
                                 'method': 'cash'}).with_user(self.cashier).action_validate()

    # ------------------------------------------------------------------
    # 5. Caja no valida asientos manuales
    # ------------------------------------------------------------------
    def test_cashier_cannot_post_manual_entries(self):
        journal = self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', self.company.id)],
                                                     limit=1)
        cash = self.company._spa_journal('cash').default_account_id
        shortage = self.chart.ref('l10n_bo_spa_5607')
        vals = {'move_type': 'entry', 'journal_id': journal.id, 'line_ids': [
            Command.create({'account_id': shortage.id, 'debit': 50.0, 'name': 'Faltante'}),
            Command.create({'account_id': cash.id, 'credit': 50.0, 'name': 'Faltante'})]}
        move = self.env['account.move'].with_user(self.cashier).create(vals)
        with self.assertRaisesRegex(UserError, 'asientos manuales'):
            move.action_post()
        self.assertEqual(move.state, 'draft')
        manager_move = self.env['account.move'].with_user(self.manager).create(vals)
        manager_move.action_post()
        self.assertEqual(manager_move.state, 'posted')
        # Los cobros de caja (asientos de pago) siguen funcionando.
        _membership, invoice = self._member(self.plan_basic)
        self.assertEqual(invoice.payment_state, 'paid')

    # ------------------------------------------------------------------
    # 6. Cuotas iguales al centavo
    # ------------------------------------------------------------------
    def test_installments_equal_to_the_cent(self):
        offer = self.env['spa.payment.offer'].create({
            'name': 'Anual en 3 cuotas', 'offer_type': 'installments', 'installments': 3, 'months': 12,
            'date_from': self.today, 'date_to': self.today + timedelta(days=30)})
        membership = self._membership(self.plan_premium, months=12, activate=False)
        invoice = membership.action_create_invoice(offer=offer)
        receivable = invoice.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertEqual([round(line.balance, 2) for line in receivable.sorted('date_maturity')],
                         [3023.33, 3023.33, 3023.34])
        # Plazos de una versión anterior (33,33 %) se rehacen con 6 decimales.
        old_term = self.env['account.payment.term'].create({'name': 'Viejo', 'line_ids': [
            Command.create({'value': 'percent', 'value_amount': 33.33, 'nb_days': 0}),
            Command.create({'value': 'percent', 'value_amount': 33.33, 'nb_days': 30}),
            Command.create({'value': 'percent', 'value_amount': 33.34, 'nb_days': 60})]})
        offer.payment_term_id = old_term
        self.assertNotEqual(offer._get_payment_term(), old_term)
        self.assertEqual(offer._get_payment_term(), offer.payment_term_id)

    # ------------------------------------------------------------------
    # 7. Multiempresa
    # ------------------------------------------------------------------
    def test_multicompany_rules(self):
        self._member(self.plan_premium, months=12)
        self.env['spa.payment.offer'].create({'name': 'Oferta A', 'offer_type': 'discount', 'discount_percent': 5,
                                              'date_from': self.today, 'date_to': self.today + timedelta(days=5)})
        branch = self.env['res.company'].create({'name': 'Sucursal (cobros)'})
        other = new_test_user(self.env, login='bill_branch', groups='base.group_user,spa_base.group_spa_manager',
                              company_id=branch.id, company_ids=[branch.id])
        for model in ('spa.payment.offer', 'spa.deferral.line', 'spa.dunning.step', 'spa.dunning.log',
                      'spa.payment.request'):
            self.assertFalse(self.env[model].with_user(other).search([]), model)
        self.assertTrue(self.env['spa.dunning.step'].search([('company_id', '=', self.company.id)]))

    # ------------------------------------------------------------------
    # 8. Vencimiento en fecha local (no UTC)
    # ------------------------------------------------------------------
    def test_due_date_is_local_date(self):
        tomorrow = self.today + timedelta(days=1)
        # 02:30 UTC de mañana = 22:30 de hoy en La Paz.
        with freeze_time(datetime.combine(tomorrow, time(2, 30))):
            local = self.tools.local_today()
            self.assertEqual(local, self.today)
            membership = self._membership(self.plan_basic, activate=False)
            invoice = membership.action_create_invoice()
            self.assertEqual((invoice.invoice_date, invoice.invoice_date_due), (local, local))
            booking = self._single_booking(self._partner_new('Noche', '70011005'), tomorrow + timedelta(days=1))
            self.assertEqual(booking.invoice_id.invoice_date_due, local)
            line = membership._spa_add_charge(self.env.ref('spa_membership.product_guest_fee'), name='Invitado')
            self.assertEqual(line.move_id.invoice_date_due, local)
            self._pay(invoice)
            self.assertEqual((invoice.invoice_date, invoice.invoice_date_due), (local, local))

    # ------------------------------------------------------------------
    # Sección B: renovación sin documento fiscal hasta el cobro
    # ------------------------------------------------------------------
    def test_renewal_is_invoiced_when_paid_and_dropped_when_expired(self):
        membership, _invoice = self._member(self.plan_basic)
        membership.date_end = self.today + timedelta(days=3)
        self.Membership._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertRecordValues(renewal, [{'state': 'draft', 'spa_invoice_kind': 'renewal', 'invoice_date': self.today}])
        self.assertEqual(renewal._spa_payment_reference(), membership.name)
        pay_day = self.today + timedelta(days=2)
        with self._at(pay_day):
            self._pay(renewal)
        self.assertRecordValues(renewal, [{'state': 'posted', 'invoice_date': pay_day, 'payment_state': 'paid'}])
        self.assertEqual(membership.date_end, self.today + timedelta(days=3) + relativedelta(months=1))
        # Renovación impaga de una membresía que vence: el cobro pendiente se anula (sin factura).
        lapsed, _inv = self._member(self.plan_basic, partner=self._partner_new('Se va', '70011006'))
        lapsed.date_end = self.today + timedelta(days=2)
        self.Membership._cron_billing_daily()
        draft = lapsed._open_period_invoice()
        self.assertEqual(draft.state, 'draft')
        lapsed.write({'state': 'suspended', 'date_end': self.today - timedelta(days=200)})
        self.Membership._cron_membership_daily()
        self.assertEqual(lapsed.state, 'expired')
        self.assertEqual(draft.state, 'cancel')
        self.assertFalse(lapsed.invoice_ids.filtered(lambda m: m.spa_invoice_kind == 'renewal' and m.state == 'posted'))
        # Cancelada con cobro pendiente: también se anula.
        quitting = self._membership(self.plan_basic, partner=self._partner_new('Cancela', '70011007'), activate=False)
        pending = quitting.action_create_invoice()
        quitting.action_cancel()
        self.assertEqual(pending.state, 'cancel')

    # ------------------------------------------------------------------
    # C1. Escalera de cobranza
    # ------------------------------------------------------------------
    def test_dunning_ladder_timeline(self):
        membership, _invoice = self._member(self.plan_basic)  # gracia 5 días
        due = self.today + timedelta(days=5)
        membership.date_end = due
        expected = {
            due - timedelta(days=5): ['renewal_notice'],
            due: ['renewal_notice', 'membership_due'],
            due + timedelta(days=1): ['renewal_notice', 'membership_due', 'grace_notice'],
            due + timedelta(days=3): ['renewal_notice', 'membership_due', 'grace_notice', 'grace_reminder'],
            due + timedelta(days=5): ['renewal_notice', 'membership_due', 'grace_notice', 'grace_reminder',
                                      'suspended_notice'],
            due + timedelta(days=6): ['renewal_notice', 'membership_due', 'grace_notice', 'grace_reminder',
                                      'suspended_notice'],
            due + timedelta(days=15): ['renewal_notice', 'membership_due', 'grace_notice', 'grace_reminder',
                                       'suspended_notice', 'last_call'],
        }
        states = {}
        for day, codes in expected.items():
            with self._at(day, 6):
                self.Membership._cron_membership_daily()
                self.Membership._cron_billing_daily()
                self.Membership._cron_billing_daily()  # dos corridas el mismo día: nada se repite
            self.assertEqual(sorted(self._codes(self.partner)), sorted(codes + ['payment_validated']), day)
            states[day] = membership.state
        self.assertEqual(states[due + timedelta(days=3)], 'grace')
        self.assertEqual(states[due + timedelta(days=5)], 'suspended', 'Paso +5: suspensión por falta de pago')
        self.assertEqual(len(membership.dunning_log_ids.filtered(lambda l: l.kind == 'step')), 5)
        notice = self.Message.search([('partner_id', '=', self.partner.id), ('template_id.code', '=', 'grace_notice')])
        self.assertIn((due + timedelta(days=4)).strftime('%d/%m/%Y'), notice.body,
                      'El aviso de gracia indica el último día con acceso según la escalera')
        # Paga la renovación: se reactiva y la escalera vuelve a empezar con el nuevo vencimiento.
        with self._at(due + timedelta(days=16)):
            self._pay(membership._open_period_invoice())
        self.assertEqual(membership.state, 'active')

    def test_dunning_catch_up_and_pending_payment(self):
        late, _invoice = self._member(self.plan_basic, partner=self._partner_new('Atrasado', '70011008'))
        late.write({'date_end': self.today - timedelta(days=4), 'state': 'grace'})
        today_due, _invoice2 = self._member(self.plan_basic, partner=self._partner_new('Vence hoy', '70011009'))
        today_due.date_end = self.today
        self.Membership._cron_billing_daily()
        late_codes = self._codes(late.partner_id)
        self.assertIn('grace_reminder', late_codes)
        self.assertNotIn('membership_due', late_codes, 'Solo el aviso más reciente')
        self.assertEqual(sorted(late.dunning_log_ids.mapped('result')), ['done', 'skipped', 'skipped'])
        self.assertTrue(today_due._open_period_invoice())
        self.assertIn('membership_due', self._codes(today_due.partner_id))
        self.assertNotIn('renewal_notice', self._codes(today_due.partner_id))
        # Comprobante por validar: no se insiste hasta que caja lo revise.
        waiting2, _invoice3 = self._member(self.plan_basic, partner=self._partner_new('Comprobante', '70011010'))
        waiting2.date_end = self.today - timedelta(days=4)
        waiting2.action_create_invoice()
        self.Request.create({'partner_id': waiting2.partner_id.id, 'membership_id': waiting2.id,
                             'invoice_id': waiting2._open_period_invoice().id, 'amount': 450.0, 'method': 'qr'})
        self.Membership._cron_billing_daily()
        self.assertFalse(waiting2.dunning_log_ids)

    # ------------------------------------------------------------------
    # Cuotas vencidas: aviso, suspensión y reactivación
    # ------------------------------------------------------------------
    def test_installment_followup(self):
        offer = self.env['spa.payment.offer'].create({
            'name': 'Anual en 3 cuotas', 'offer_type': 'installments', 'installments': 3, 'months': 12,
            'date_from': self.today, 'date_to': self.today + timedelta(days=30)})
        membership = self._membership(self.plan_premium, months=12, activate=False)
        invoice = membership.action_create_invoice(offer=offer)
        self.assertEqual(invoice.state, 'draft')
        self._pay(invoice, amount=invoice._spa_amount_to_pay())
        self.assertEqual(invoice.state, 'posted', 'Se emite toda la factura al pagar la primera cuota')
        self.assertEqual(membership.state, 'active')
        second = self.today + timedelta(days=30)
        with self._at(second + timedelta(days=2)):
            self.Membership._cron_billing_daily()
        self.assertNotIn('installment_reminder', self._codes(self.partner))
        with self._at(second + timedelta(days=3)):
            self.Membership._cron_billing_daily()
            self.Membership._cron_billing_daily()
        self.assertEqual(self._codes(self.partner).count('installment_reminder'), 1)
        with self._at(second + timedelta(days=10)):
            self.Membership._cron_billing_daily()
        self.assertEqual(membership.state, 'suspended')
        self.assertTrue(membership.spa_installment_suspended)
        self.assertIn('installment_suspended', self._codes(self.partner))
        with self._at(second + timedelta(days=11)):
            amount = invoice._spa_amount_to_pay()
            self.assertAlmostEqual(amount, 3023.33)
            self._pay(invoice, amount=amount)
        self.assertEqual(membership.state, 'active')
        self.assertFalse(membership.spa_installment_suspended)
        self.assertEqual(membership.date_end, self.today + relativedelta(months=12) - timedelta(days=1),
                         'La cuota no extiende el período')

    # ------------------------------------------------------------------
    # C2. Ingreso de membresías por área
    # ------------------------------------------------------------------
    def test_membership_revenue_by_area(self):
        self.assertEqual(self.plan_basic.analytic_distribution,
                         {str(self.area_pool.id): 60, str(self.area_wet.id): 40})
        self.assertEqual(self.plan_vip.analytic_distribution,
                         {str(self.area_pool.id): 35, str(self.area_wet.id): 25, str(self.area_spa.id): 40})
        # El dueño (gerente + contabilidad) edita el reparto en la ficha del plan; recepción no lo ve.
        # (Con spa_all el gerente también es contador del spa y sí lo ve.)
        owner = new_test_user(self.env, login='bill_owner', name='Dueño (cobros)',
                              groups='base.group_user,spa_base.group_spa_manager,account.group_account_manager,'
                                     'account.group_account_user')
        self.assertIn('analytic_distribution', self._web_read(owner, self.plan_basic, 'form')[0])

        def arch(user):
            return self.plan_basic.with_user(user).get_views([(False, 'form')])['views']['form']['arch']

        self.assertIn('widget="analytic_distribution"', arch(owner))
        self.assertNotIn('widget="analytic_distribution"', arch(self.reception))
        _membership, invoice = self._member(self.plan_basic)
        product_line = invoice.invoice_line_ids
        self.assertEqual(product_line.analytic_distribution, self.plan_basic.analytic_distribution)
        column = self.area_pool.plan_id._column_name()
        analytic = self.env['account.analytic.line'].search([('move_line_id', '=', product_line.id)])
        by_area = {line[column]: line.amount for line in analytic}
        untaxed = -product_line.balance
        self.assertAlmostEqual(by_area[self.area_pool], untaxed * 0.6, delta=0.011)
        self.assertAlmostEqual(by_area[self.area_wet], untaxed * 0.4, delta=0.011)
        # Prepagado: la factura va a diferidos sin área; el devengo mensual lleva el área del plan.
        annual, annual_invoice = self._member(self.plan_basic, months=12, partner=self._partner_new('Anual', '70011011'))
        self.assertFalse(annual_invoice.invoice_line_ids.analytic_distribution)
        self.env['spa.deferral.line']._cron_post_deferrals()
        posted = annual.deferral_line_ids.filtered(lambda l: l.state == 'posted')
        income = posted.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(income.analytic_distribution, self.plan_basic.analytic_distribution)
        self.assertEqual(income.account_id.code, '410110')

    # ------------------------------------------------------------------
    # C3. Cambio de plan
    # ------------------------------------------------------------------
    def test_plan_upgrade_prorated(self):
        start = self.today - timedelta(days=10)
        membership = self._membership(self.plan_premium, start=start)
        for _index in range(3):
            membership._spa_consume(self.massage, self._dt(self.today, 9.0), 'checkin')
        renewal = membership.action_create_invoice()  # renovación Premium por cobrar
        self.assertAlmostEqual(renewal.amount_total, 890.0)
        wizard = self.env['spa.plan.change'].with_user(self.reception).create({
            'membership_id': membership.id, 'new_plan_id': self.plan_vip.id})
        period_days = (membership.date_end - start).days + 1
        remaining = (membership.date_end - self.today).days + 1
        self.assertEqual((wizard.change_type, wizard.period_days, wizard.remaining_days),
                         ('upgrade', period_days, remaining))
        self.assertAlmostEqual(wizard.amount, round((1490.0 - 890.0) * remaining / period_days, 2))
        action = wizard.action_confirm()
        self.assertEqual(membership.plan_id, self.plan_vip)
        massage = membership._entitlement_for(self.massage, self.today)
        self.assertEqual(massage.plan_line_id.plan_id, self.plan_vip)
        self.assertEqual((massage.granted, massage.used, massage.remaining), (8, 3, 5),
                         'Lo usado en el mes cuenta contra el saldo del plan nuevo')
        upgrade = self.env['account.move'].browse(action['context']['default_invoice_id'])
        self.assertRecordValues(upgrade, [{'state': 'draft', 'spa_invoice_kind': 'upgrade'}])
        self.assertAlmostEqual(upgrade.amount_total, wizard.amount)
        self.assertEqual(renewal.state, 'cancel', 'La renovación pendiente se rehace con el plan nuevo')
        self.assertAlmostEqual(membership._open_period_invoice().amount_total, 1490.0)
        end = membership.date_end
        request = self.Request.with_user(self.reception).with_context(**action['context']).create({'method': 'cash'})
        request.with_user(self.cashier).action_validate()
        self.assertEqual(upgrade.state, 'posted')
        self.assertEqual(membership.date_end, end, 'La diferencia no extiende el período')

    def test_plan_downgrade_next_period(self):
        membership, _invoice = self._member(self.plan_vip)
        old_end = membership.date_end
        wizard = self.env['spa.plan.change'].with_user(self.reception).create({
            'membership_id': membership.id, 'new_plan_id': self.plan_basic.id})
        self.assertEqual(wizard.change_type, 'downgrade')
        self.assertEqual(wizard.effective_date, old_end + timedelta(days=1))
        wizard.action_confirm()
        self.assertEqual(membership.plan_id, self.plan_vip, 'Mantiene VIP hasta el fin del período pagado')
        self.assertEqual(membership.spa_next_plan_id, self.plan_basic)
        # La renovación se cobra con el plan nuevo; pagada por adelantado, el cambio rige al empezar el período.
        membership.date_end = self.today + timedelta(days=3)
        self.Membership._cron_billing_daily()
        renewal = membership._open_period_invoice()
        self.assertAlmostEqual(renewal.amount_total, 450.0)
        self.assertEqual(renewal.spa_period_id.plan_id, self.plan_basic)
        self._pay(renewal)
        switch = self.today + timedelta(days=4)
        self.assertEqual(membership.spa_plan_switch_date, switch)
        self.assertEqual(membership.date_end, switch + relativedelta(months=1) - timedelta(days=1))
        self.assertEqual(membership.plan_id, self.plan_vip)
        with self._at(switch):
            self.Membership._cron_billing_daily()
        self.assertEqual(membership.plan_id, self.plan_basic)
        self.assertFalse(membership.spa_next_plan_id)
        self.partner.invalidate_recordset()
        self.assertNotEqual(self.partner.property_product_pricelist, self.plan_vip.pricelist_id)

    def test_plan_downgrade_cancel(self):
        membership, _invoice = self._member(self.plan_vip)
        membership._spa_schedule_downgrade(self.plan_basic.period_ids.filtered(lambda p: p.months == 1))
        membership.date_end = self.today + timedelta(days=2)
        self.Membership._cron_billing_daily()
        self.assertAlmostEqual(membership._open_period_invoice().amount_total, 450.0)
        membership.with_user(self.reception).action_cancel_plan_change()
        self.assertFalse(membership.spa_next_plan_id)
        self.assertAlmostEqual(membership._open_period_invoice().amount_total, 1490.0)

    def test_day_pass_is_invoiced_and_paid(self):
        """Pase diario (sin membresía): ocupa aforo, se factura al ingresar y caja valida el pago."""
        sauna = self.env.ref('spa_base.space_sauna')
        visitor = self.env['res.partner'].create({'name': 'Visitante sin plan', 'phone': '+591 71234567'})
        local_now = datetime.combine(self.today, time(15, 0))
        with freeze_time(self.env['spa.tools'].to_utc(local_now)):
            wizard = self.env['spa.checkin.wizard'].with_user(self.reception).create({
                'space_id': sauna.id, 'partner_id': visitor.id, 'guests': 1})
            wizard._onchange_day_pass()
            self.assertTrue(wizard.day_pass)
            action = wizard.action_check_in()
        log = self.env['spa.access.log'].search([('partner_id', '=', visitor.id)])
        self.assertTrue(log.day_pass)
        self.assertEqual(log.people, 2)
        invoice = log.invoice_id
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.invoice_line_ids.quantity, 2)
        product = sauna._free_mode_service().product_id
        self.assertAlmostEqual(invoice.amount_total, 2 * product.lst_price, places=2)
        self.assertEqual(invoice.invoice_line_ids.analytic_distribution,
                         {str(sauna.analytic_account_id.id): 100})
        self.assertIn('pase diario', action['params']['message'])
        payment_action = action['params']['next']
        self.assertEqual(payment_action['res_model'], 'spa.payment.request')
        self.assertEqual(payment_action['context']['default_invoice_id'], invoice.id)
        request = self.Request.with_user(self.reception).create({
            'partner_id': visitor.id, 'invoice_id': invoice.id, 'amount': invoice.amount_residual,
            'method': 'cash'})
        request.with_user(self.cashier).action_validate()
        self.assertEqual(invoice.payment_state, 'paid')
