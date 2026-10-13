# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, freeze_time, tagged

from .common import MON, NOW, TUE, SpaRentalCommon, utc_at


@tagged('post_install', '-at_install', 'spa')
@freeze_time(NOW)
class TestSpaRental(SpaRentalCommon):

    # ------------------------------------------------------------------
    # Disponibilidad y bloqueo del espacio
    # ------------------------------------------------------------------
    def test_exclusive_rental_blocks_member_slots_and_bookings(self):
        rental = self._rental(TUE, 14, 17)
        self.assertEqual(rental.state, 'quotation')
        self.assertEqual(rental.line_ids.product_id, self.pool_hour, 'Se agrega el alquiler por hora del espacio')
        self.assertEqual(rental.line_ids.quantity, 3.0)
        self.assertEqual(rental.amount_total, 1800.0)
        with self._raises(UserError, 'gerente'):
            rental.with_user(self.reception).action_confirm()
        rental.with_user(self.manager).action_confirm()
        self.assertEqual(rental.state, 'confirmed')
        self.assertEqual(rental.reserved_seats, self.space_pool.capacity)

        slots = self.pool._get_slots(TUE)
        blocked = [s for s in slots if s['start'] < rental.stop and s['stop'] > rental.start]
        self.assertEqual(len(blocked), 2)  # 13-15 y 15-17
        for slot in blocked:
            self.assertEqual(slot['free'], 0)
            self.assertFalse(slot['available'])
            self.assertIn('Reservado para evento: Cumpleaños de Sofía', slot['reason'])
        others = [s for s in slots if s not in blocked]
        self.assertTrue(all(s['free'] == self.space_pool.capacity for s in others))

        member = self._membership(self.plan_premium)
        booking = self._booking(member, self.pool, TUE, 15, confirm=False)
        with self._raises(UserError, 'Reservado para evento: Cumpleaños de Sofía'):
            booking.action_confirm()
        self.assertEqual(booking.state, 'draft')
        # Evento privado: los socios no ven el nombre.
        rental.with_user(self.reception).private_event = True
        with self._raises(UserError, 'Reservado para evento: evento privado'):
            booking.action_confirm()
        reasons = {s['reason'] for s in self.pool._get_slots(TUE) if s['start'] < rental.stop and s['stop'] > rental.start}
        self.assertEqual(reasons, {'Reservado para evento: evento privado'})
        # Fuera del evento se reserva normal.
        self.assertEqual(self._booking(member, self.pool, TUE, 9).state, 'confirmed')

    def test_exclusive_rental_blocks_check_in_and_courtesy(self):
        self.space_sauna.write({'open_hour': 0.0, 'close_hour': 24.0})
        member = self._membership(self.plan_premium)
        rental = self._rental(MON, 10, 13, space=self.space_sauna, event='Sesión de fotos')
        rental.action_confirm()
        Log = self.env['spa.access.log']
        with freeze_time(utc_at(MON, 9, 30)):
            # Antes del evento, pero la permanencia máxima (1 h) se cruza con él.
            with self._raises(UserError, 'Reservado para evento: Sesión de fotos'):
                Log.do_check_in(self.space_sauna, token=member.qr_token)
        with freeze_time(utc_at(MON, 11)):
            with self._raises(UserError, 'Reservado para evento: Sesión de fotos'):
                Log.do_check_in(self.space_sauna, token=member.qr_token)
            courtesy = self.env['spa.courtesy.pass'].create({
                'guest_name': 'Invitada Cortesía', 'phone': '+591 73333333',
                'service_ids': [Command.set(self.sauna.ids)]})
            with self._raises(UserError, 'Reservado para evento'):
                courtesy._redeem(self.space_sauna)
            self.assertFalse(Log.search([('space_id', '=', self.space_sauna.id), ('state', '=', 'open')]))
            self.assertEqual(self.space_sauna.spa_reserved_now, self.space_sauna.capacity)
        with freeze_time(utc_at(MON, 13, 5)):
            self.assertTrue(Log.do_check_in(self.space_sauna, token=member.qr_token))

    def test_exclusive_rental_refused_when_space_in_use(self):
        member = self._membership(self.plan_premium)
        self._booking(member, self.pool, TUE, 9)  # 09:00-11:00
        rental = self._rental(TUE, 10, 12)
        self.assertIn('reserva(s) de socios', rental.availability_warning)
        with self._raises(UserError, r'Hay 1 reserva\(s\) de socios'):
            rental.action_confirm()
        self.assertEqual(rental.state, 'quotation')
        # Otro evento confirmado en el mismo horario.
        first = self._rental(TUE, 13, 15, mode='partial', seats=4, event='Club A')
        first.action_confirm()
        second = self._rental(TUE, 14, 16, mode='partial', seats=4, event='Club B')
        with self._raises(UserError, 'otro evento confirmado'):
            second.action_confirm()
        # Fuera del horario de atención: solo con autorización del gerente.
        late = self._rental(TUE, 20, 23, event='Fiesta nocturna')
        with self._raises(UserError, 'fuera de la atención'):
            late.action_confirm()
        with self._raises(UserError, 'gerente'):
            late.with_user(self.reception).write({'outside_hours_ok': True})
        late.with_user(self.manager).write({'outside_hours_ok': True})
        late.with_user(self.manager).action_confirm()
        self.assertEqual(late.state, 'confirmed')
        # Un cierre programado no se puede saltar.
        self.space_pool.closure_ids = [Command.create({'date_from': MON, 'date_to': MON, 'reason': 'Mantenimiento'})]
        closed = self._rental(MON, 14, 16, event='Evento en cierre')
        with self._raises(UserError, 'Mantenimiento'):
            closed.action_confirm()

    def test_partial_rental_reduces_seats(self):
        self.space_pool.capacity = 6
        rental = self._rental(TUE, 9, 12, mode='partial', seats=5, event='Club de natación')
        rental.action_confirm()
        slot = [s for s in self.pool._get_slots(TUE) if s['start'] == self._dt(TUE, 9)][0]
        self.assertEqual(slot['free'], 1)
        ana = self._membership(self.plan_premium)
        bruno = self._membership(self.plan_premium, partner=self.env['res.partner'].create({'name': 'Bruno'}))
        self.assertEqual(self._booking(ana, self.pool, TUE, 9).state, 'confirmed')
        with self._raises(UserError, 'cupos reservados para evento «Club de natación»'):
            self._booking(bruno, self.pool, TUE, 9)
        slot = [s for s in self.pool._get_slots(TUE) if s['start'] == self._dt(TUE, 9)][0]
        self.assertIn('Club de natación', slot['reason'])
        # Espacio libre (sauna, aforo 5): evento parcial de 3 cupos en curso.
        self.space_sauna.write({'open_hour': 0.0, 'close_hour': 24.0})
        sauna_event = self._rental(MON, 10, 12, space=self.space_sauna, mode='partial', seats=3, event='Taller')
        sauna_event.action_confirm()
        Log = self.env['spa.access.log']
        with freeze_time(utc_at(MON, 10, 30)):
            Log.do_check_in(self.space_sauna, token=ana.qr_token)
            Log.do_check_in(self.space_sauna, token=bruno.qr_token)
            third = self._membership(self.plan_premium, partner=self.env['res.partner'].create({'name': 'Carla'}))
            with self._raises(UserError, 'reservados para evento «Taller»'):
                Log.do_check_in(self.space_sauna, token=third.qr_token)

    def test_confirmed_rental_is_locked(self):
        rental = self._rental(TUE, 14, 16)
        rental.action_confirm()
        with self._raises(UserError, 'volverlo a cotización'):
            rental.with_user(self.reception).write({'stop': self._dt(TUE, 18)})
        rental.with_user(self.reception).write({'attendees': 30, 'note': 'Torta a las 15:00'})
        with self._raises(UserError, 'solo se modifica en cotización'):
            rental.line_ids.with_user(self.manager).write({'quantity': 5.0})
        rental.with_user(self.manager).action_reset_quotation()
        self.assertEqual(rental.state, 'quotation')
        self.assertEqual(rental.invoice_id, self.env['account.move'])
        rental.write({'stop': self._dt(TUE, 18)})
        self.assertEqual(rental.duration_hours, 4.0)

    def test_only_manager_changes_prices(self):
        rental = self._rental(TUE, 14, 16)
        line = rental.line_ids
        with self._raises(UserError, 'Solo el gerente'):
            line.with_user(self.reception).write({'price_unit': 100.0})
        with self._raises(UserError, 'Solo el gerente'):
            line.with_user(self.reception).write({'discount': 10.0})
        self.env.invalidate_all()
        extra = self.env['product.product'].create({'name': 'Decoración temática', 'type': 'service', 'list_price': 250.0,
                                                    'categ_id': self.env.ref('l10n_bo_spa.categ_rental').id})
        self.env['spa.rental.line'].with_user(self.reception).create({'rental_id': rental.id, 'product_id': extra.id})
        line.with_user(self.manager).write({'discount': 10.0})
        self.assertEqual(rental.amount_total, 600.0 * 2 * 0.9 + 250.0)

    # ------------------------------------------------------------------
    # Facturación (Ley 843 art. 4 inc. b) y garantía
    # ------------------------------------------------------------------
    def test_invoice_draft_until_paid(self):
        rental = self._rental(TUE, 14, 17)
        rental.action_confirm()
        invoice = rental.invoice_id
        self.assertEqual(invoice.state, 'draft', 'No se factura antes del cobro o de terminar el evento')
        self.assertEqual(invoice.spa_invoice_kind, 'rental')
        self.assertEqual(invoice.amount_total, rental.amount_total)
        product_lines = invoice.invoice_line_ids
        self.assertEqual(product_lines.account_id, self.acc_rental)
        self.assertEqual(product_lines.analytic_distribution, {str(self.area_events.id): 100.0})
        self.assertEqual(product_lines.tax_ids, self.company._spa_sale_taxes())
        self.assertEqual(rental.invoice_status, 'draft')
        # Recepción no cobra.
        with self._raises(AccessError):
            self._pay(rental, 1000.0, user=self.reception)
        self.assertEqual(invoice.state, 'draft')
        # Anticipo: la factura se valida con la fecha del cobro.
        self._pay(rental, 1000.0)
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.invoice_date, MON)
        self.assertEqual(invoice.payment_state, 'partial')
        self.assertEqual(rental.invoice_status, 'partial')
        self.assertEqual(rental.amount_paid, 1000.0)
        self.assertEqual(rental.amount_due, 800.0)
        income = invoice.line_ids.filtered(lambda l: l.account_id == self.acc_rental)
        self.assertAlmostEqual(-sum(income.mapped('balance')), 1800.0 * 0.87, places=2)  # IVA 13 % incluido
        self._pay(rental, 800.0, method='qr')
        self.assertEqual(rental.invoice_status, 'paid')
        # Con cobros no se cancela sin nota de crédito.
        with self._raises(UserError, 'ya tiene cobros'):
            rental.with_user(self.manager).action_cancel()

    def test_done_posts_invoice_and_cron(self):
        rental = self._rental(MON, 10, 12)
        rental.action_confirm()
        with freeze_time(utc_at(MON, 10, 30)):
            self.env['spa.rental']._cron_rentals()
            self.assertEqual(rental.state, 'in_progress')
            self.assertEqual(rental.invoice_id.state, 'draft')
        with freeze_time(utc_at(MON, 12, 5)):
            self.env['spa.rental']._cron_rentals()
        self.assertEqual(rental.state, 'done')
        self.assertEqual(rental.invoice_id.state, 'posted', 'Servicio prestado: nace el hecho imponible')
        self.assertEqual(rental.invoice_id.invoice_date, MON)

    def test_cancel_quotation_and_confirmed(self):
        rental = self._rental(TUE, 14, 16)
        rental.action_confirm()
        invoice = rental.invoice_id
        with self._raises(UserError, 'gerente'):
            rental.with_user(self.reception).action_cancel()
        rental.with_user(self.manager).action_cancel()
        self.assertEqual(rental.state, 'cancelled')
        self.assertEqual(invoice.state, 'cancel')
        slot = [s for s in self.pool._get_slots(TUE) if s['start'] == self._dt(TUE, 15)][0]
        self.assertEqual(slot['free'], self.space_pool.capacity, 'Al cancelar se libera el espacio')

    def test_deposit_received_applied_and_refunded(self):
        rental = self._rental(MON, 10, 12, deposit=500.0)
        rental.action_confirm()
        self.assertEqual(rental.deposit_state, 'pending')
        self._pay(rental, 500.0, kind='deposit')
        self.assertEqual(rental.deposit_state, 'held')
        self.assertEqual(rental.deposit_balance, 500.0)
        payment = rental.deposit_payment_ids
        self.assertEqual(payment.destination_account_id, self.acc_deposit)
        self.assertEqual(self._partner_balance(self.acc_deposit, self.customer), -500.0)
        self.assertEqual(rental.invoice_id.state, 'draft', 'La garantía no es cobro del servicio')
        with self._raises(UserError, 'garantía'):
            rental.with_user(self.manager).action_cancel()
        rental.action_done()
        # Daños por Bs 200 con la garantía.
        wizard = self.env['spa.rental.deposit.wizard'].with_user(self.cashier).create({
            'rental_id': rental.id, 'operation': 'apply', 'amount': 200.0,
            'product_id': self.env.ref('spa_rental.product_rental_damage').id, 'description': 'Reposera rota'})
        wizard.action_confirm()
        damage = rental.move_ids.filtered(lambda m: m.spa_rental_move_kind == 'damage')
        self.assertEqual(damage.state, 'posted')
        self.assertEqual(damage.amount_total, 200.0)
        self.assertEqual(damage.payment_state, 'paid')
        self.assertEqual(damage.invoice_line_ids.account_id, self.acc_rental)
        self.assertEqual(rental.deposit_applied, 200.0)
        self.assertEqual(rental.deposit_balance, 300.0)
        with self._raises(UserError, 'supera la garantía'):
            self.env['spa.rental.deposit.wizard'].with_user(self.cashier).create({
                'rental_id': rental.id, 'operation': 'refund', 'amount': 400.0, 'method': 'cash'}).action_confirm()
        self.env['spa.rental.deposit.wizard'].with_user(self.cashier).create({
            'rental_id': rental.id, 'operation': 'refund', 'amount': 300.0, 'method': 'cash'}).action_confirm()
        self.assertEqual(rental.deposit_refunded, 300.0)
        self.assertEqual(rental.deposit_balance, 0.0)
        self.assertEqual(rental.deposit_state, 'settled')
        self.assertEqual(self._partner_balance(self.acc_deposit, self.customer), 0.0, '216200 queda en cero')

    def test_quotation_form_onchange(self):
        """Recepción cotiza desde el formulario: el alquiler por hora sigue al espacio y a las horas."""
        with Form(self.env['spa.rental'].with_user(self.reception)) as form:
            form.event_name = 'Sesión de fotos'
            form.partner_id = self.customer
            form.space_id = self.space_pool
            form.start = self._dt(TUE, 9)
            form.stop = self._dt(TUE, 11)
            self.assertEqual(len(form.line_ids), 1)
            self.assertEqual(form.line_ids._records[0]['quantity'], 2.0)
            form.stop = self._dt(TUE, 12)
            self.assertEqual(form.line_ids._records[0]['quantity'], 3.0)
            form.space_id = self.space_sauna
            self.assertEqual(len(form.line_ids), 1)
            self.assertEqual(form.line_ids._records[0]['product_id'], self.space_sauna.spa_rental_product_id.id)
            form.mode = 'partial'
            form.attendees = 3
            self.assertEqual(form.seats, 3)
        rental = form.record
        self.assertEqual(rental.amount_total, 900.0)
        self.assertEqual(rental.phone, self.customer.phone)
        self.assertTrue(rental.lead_id)

    def test_views_readable_by_roles(self):
        rental = self._rental(TUE, 14, 16, deposit=300.0)
        rental.action_confirm()
        self._pay(rental, 300.0, kind='deposit')
        for user in (self.reception, self.cashier, self.manager):
            for view_type in ('list', 'form', 'calendar'):
                self._web_read_view(user, rental, view_type)
        self.space_pool.with_user(self.reception).read(['spa_reserved_now', 'spa_reserved_label', 'occupancy'])

    # ------------------------------------------------------------------
    # CRM y mensajes
    # ------------------------------------------------------------------
    def test_lead_created_and_won(self):
        rental = self._rental(TUE, 14, 16)
        lead = rental.lead_id
        self.assertTrue(lead)
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_event'))
        self.assertEqual(lead.team_id, self.env.ref('spa_rental.crm_team_events'))
        self.assertEqual(lead.partner_id, self.customer)
        self.assertEqual(lead.expected_revenue, 1200.0)
        # Segundo espacio del mismo evento: misma oportunidad.
        jacuzzi = self._rental(TUE, 14, 16, space=self.env.ref('spa_base.space_jacuzzi'), lead_id=lead.id)
        self.assertEqual(jacuzzi.lead_id, lead)
        self.assertEqual(lead.stage_id, self.env.ref('spa_rental.crm_stage_event_quote'))
        rental.action_confirm()
        self.assertEqual(lead.won_status, 'won')
        self.assertEqual(lead.stage_id, self.env.ref('spa_rental.crm_stage_event_won'))
        self.assertTrue(self._messages(self.customer, 'rental_confirmed'))
        # Una cotización cancelada sin otros eventos pierde su oportunidad.
        other = self._rental(TUE, 18, 19, partner=self.walk_in, event='Consulta')
        other.action_cancel()
        self.assertEqual(other.lead_id.with_context(active_test=False).won_status, 'lost')

    def test_reminder(self):
        rental = self._rental(TUE, 7, 9)
        rental.action_confirm()
        self.env['spa.rental']._cron_rentals()
        self.assertEqual(len(self._messages(self.customer, 'rental_reminder')), 1)
        self.env['spa.rental']._cron_rentals()
        self.assertEqual(len(self._messages(self.customer, 'rental_reminder')), 1, 'Una sola vez')
