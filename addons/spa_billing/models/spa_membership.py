# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .account_move import PENDING_KINDS, PERIOD_KINDS

ACCESS_STATES = ('active', 'grace')
LIVE_STATES = ('active', 'grace', 'suspended')
DEFERRAL_GROUPS = 'spa_base.group_spa_manager,account.group_account_user'


class SpaMembership(models.Model):
    _inherit = 'spa.membership'

    invoice_ids = fields.One2many('account.move', 'spa_membership_id', string='Facturas')
    # compute_sudo: recepción y marketing ven el saldo sin permisos sobre las facturas.
    invoice_count = fields.Integer(compute='_compute_billing', compute_sudo=True, string='Nº de facturas')
    amount_due = fields.Monetary('Saldo por cobrar', compute='_compute_billing', compute_sudo=True,
                                 help='Facturas emitidas con saldo y cobros pendientes (aún sin factura).')
    payment_request_ids = fields.One2many('spa.payment.request', 'membership_id', string='Pagos informados')
    deferral_line_ids = fields.One2many('spa.deferral.line', 'membership_id', string='Devengo',
                                        groups=DEFERRAL_GROUPS)
    offer_id = fields.Many2one('spa.payment.offer', string='Oferta de pago',
                               help='Descuento o cuotas para la próxima factura de este socio.')
    auto_renew = fields.Boolean('Renovación con aviso', default=True,
                                help='Genera el cobro de renovación y los avisos de la escalera de cobranza.')
    # Cambio de plan a la baja: rige desde el próximo período (se cobra en la renovación).
    spa_next_plan_id = fields.Many2one('spa.plan', string='Plan desde la renovación', readonly=True, copy=False,
                                       tracking=True)
    spa_next_period_id = fields.Many2one('spa.plan.period', string='Duración desde la renovación', readonly=True,
                                         copy=False)
    spa_plan_switch_date = fields.Date('Cambia de plan el', readonly=True, copy=False,
                                       help='Inicio del período ya pagado con el nuevo plan.')
    spa_installment_suspended = fields.Boolean('Suspendida por cuota vencida', readonly=True, copy=False,
                                               tracking=True)
    dunning_log_ids = fields.One2many('spa.dunning.log', 'membership_id', string='Avisos de cobranza')

    @api.depends('invoice_ids.amount_residual', 'invoice_ids.state', 'invoice_ids.payment_state')
    def _compute_billing(self):
        for membership in self:
            invoices = membership.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
            membership.invoice_count = len(invoices.filtered(lambda m: m.state != 'cancel'))
            membership.amount_due = sum(invoices.filtered(lambda m: m._spa_is_due()).mapped('amount_residual'))

    # ------------------------------------------------------------------
    # Facturación
    # ------------------------------------------------------------------
    @api.model
    def _spa_line_vals(self, product, quantity=1.0, price=None, name=None, discount=0.0, analytic=None,
                       distribution=None):
        company = self.env.company
        vals = {
            'product_id': product.id,
            'name': name or product.display_name,
            'quantity': quantity,
            'price_unit': product.lst_price if price is None else price,
            'discount': discount,
            'tax_ids': [(6, 0, company._spa_sale_taxes().ids or product.taxes_id.ids)],
        }
        if analytic:
            vals['analytic_distribution'] = {str(analytic.id): 100}
        elif distribution:
            vals['analytic_distribution'] = dict(distribution)
        return vals

    @api.model
    def _spa_deferred_account(self, company):
        categ = self.env.ref('l10n_bo_spa.categ_membership_prepaid', raise_if_not_found=False)
        return categ.with_company(company).property_account_income_categ_id if categ else self.env['account.account']

    @api.model
    def _spa_is_deferred_product(self, product):
        categ = self.env.ref('l10n_bo_spa.categ_membership_prepaid', raise_if_not_found=False)
        return bool(categ) and product.categ_id == categ

    def _spa_plan_distribution(self, period):
        """Áreas del plan para la línea de la factura: solo si va directo a ingresos (plan mensual). Los planes
        prepagados van a 215100 y el área se aplica al devengar cada mes (spa.deferral.line)."""
        self.ensure_one()
        if self._spa_is_deferred_product(period.product_id):
            return None
        return period.plan_id.sudo().analytic_distribution or None

    def _open_period_invoice(self):
        """Factura (sudo) del período por cobrar: cobro pendiente en borrador o factura publicada sin pagar."""
        self.ensure_one()
        return self.sudo().invoice_ids.filtered(
            lambda m: m.spa_invoice_kind in PERIOD_KINDS and not m.spa_period_applied
            and m.state in ('draft', 'posted') and m.payment_state not in ('paid', 'reversed'))

    def _spa_open_invoices(self):
        """Facturas (sudo) con saldo o cobros pendientes de la membresía, la del período primero."""
        self.ensure_one()
        invoices = self.sudo().invoice_ids.filtered(
            lambda m: m._spa_is_due() and m.amount_residual > 0 and m.payment_state not in ('paid', 'reversed'))
        return invoices.sorted(lambda m: (m.spa_invoice_kind not in PERIOD_KINDS, m.invoice_date_due or m.date, m.id))

    def _spa_create_invoice(self, kind, lines, period=None, offer=None):
        """Crea la factura del spa como cobro pendiente (borrador) con fecha y vencimiento de hoy (hora local)."""
        self.ensure_one()
        today = self.env['spa.tools'].local_today()
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': today,
            'invoice_origin': self.name,
            'spa_membership_id': self.id,
            'spa_invoice_kind': kind,
            'spa_offer_id': offer.id if offer else False,
            'spa_period_id': period.id if period else False,
            'invoice_line_ids': [(0, 0, line) for line in lines],
            'company_id': self.company_id.id,
        }
        if offer and offer.offer_type == 'installments':
            vals['invoice_payment_term_id'] = offer._get_payment_term().id
        else:
            vals['invoice_date_due'] = today
        return self.env['account.move'].sudo().create(vals)

    def action_create_invoice(self, offer=None, post=False):
        """Cobro del período (alta o renovación). Devuelve la factura (sudo).

        Nace en borrador («cobro pendiente», sin documento fiscal): se emite al validar el pago en caja
        (Ley 843 art. 4 inc. b: en servicios, el hecho imponible es la prestación o el cobro, lo primero).
        ``post=True`` la emite de inmediato (uso contable excepcional).
        """
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(self.env._('La membresía %s está cancelada: no se puede cobrar.', self.name))
        existing = self._open_period_invoice()
        if existing:
            return existing[:1]
        kind = 'membership' if self.state in ('draft', 'expired') else 'renewal'
        period = self.spa_next_period_id if kind == 'renewal' and self.spa_next_period_id else self.period_id
        offer = offer or self.offer_id
        if offer and not offer._is_applicable(period, self.partner_id, self.env['spa.tools'].local_today()):
            offer = self.env['spa.payment.offer']
        line = self._spa_line_vals(
            period.product_id, price=period.price,
            name=self.env._('Membresía %(plan)s – %(period)s (%(name)s)', plan=period.plan_id.name,
                            period=period.name, name=self.name),
            discount=offer.discount_percent if offer and offer.offer_type == 'discount' else 0.0,
            distribution=self._spa_plan_distribution(period))
        invoice = self._spa_create_invoice(kind, [line], period=period, offer=offer)
        if post:
            invoice._spa_post_pending()
        if self.offer_id:
            self.offer_id = False
        return invoice

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Facturas'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('spa_membership_id', '=', self.id)],
            'context': {'default_move_type': 'out_invoice'},
        }

    def action_register_payment_request(self):
        """Recepción registra un pago informado (QR, transferencia o efectivo) para validar en caja."""
        self.ensure_one()
        invoice = self._spa_open_invoices()[:1] or self.action_create_invoice()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar pago'),
            'res_model': 'spa.payment.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_membership_id': self.id,
                'default_invoice_id': invoice.id,
                'default_amount': invoice._spa_amount_to_pay(),
                'default_reference': False,
                'default_channel': 'reception',
            },
        }

    def _spa_add_charge(self, product, name=None, analytic=None, quantity=1.0):
        """Agrega un cargo (invitado, penalidad) a la factura de cargos del mes (borrador).

        El servicio ya se prestó: la factura de cargos se emite al cerrar el mes. Devuelve la línea creada.
        """
        self.ensure_one()
        if not product:
            return self.env['account.move.line']
        tools = self.env['spa.tools']
        today = tools.local_today()
        month_start, _month_end = tools.month_bounds(today)
        Move = self.env['account.move'].sudo()
        invoice = Move.search([
            ('partner_id', '=', self.partner_id.id), ('spa_invoice_kind', '=', 'charges'),
            ('state', '=', 'draft'), ('invoice_date', '>=', month_start), ('company_id', '=', self.company_id.id),
        ], limit=1)
        line = self._spa_line_vals(product, quantity=quantity, name=name, analytic=analytic)
        before = invoice.invoice_line_ids
        if invoice:
            invoice.write({'invoice_line_ids': [(0, 0, line)]})
        else:
            invoice = Move.create({
                'move_type': 'out_invoice',
                'partner_id': self.partner_id.id,
                'invoice_date': today,
                'invoice_date_due': today,
                'invoice_origin': self.env._('Cargos %s', self.name),
                'spa_membership_id': self.id,
                'spa_invoice_kind': 'charges',
                'invoice_line_ids': [(0, 0, line)],
                'company_id': self.company_id.id,
            })
        invoice.message_post(body=self.env._('Cargo agregado: %s', line['name']))
        return (invoice.invoice_line_ids - before)[-1:]

    # ------------------------------------------------------------------
    # Activación con el período pagado (y cambio de plan a la baja)
    # ------------------------------------------------------------------
    def _period_end(self, start):
        months = self.env.context.get('spa_period_months')
        if months:
            return start + relativedelta(months=months) - timedelta(days=1)
        return super()._period_end(start)

    def _spa_activate_period(self, invoice):
        """Activa o extiende con la duración que pagó la factura. Si es otro plan (cambio a la baja), el plan
        nuevo rige desde el inicio del período pagado."""
        self.ensure_one()
        period = invoice.spa_period_id or self.period_id
        if period == self.period_id:
            return self.action_activate()
        res = self.with_context(spa_period_months=period.months).action_activate()
        today = self.env['spa.tools'].local_today()
        new_start = self.date_end + timedelta(days=1) - relativedelta(months=period.months)
        if new_start <= today:
            self._spa_switch_plan(period)
        else:
            self.write({'spa_next_plan_id': period.plan_id.id, 'spa_next_period_id': period.id,
                        'spa_plan_switch_date': new_start})
        return res

    def _spa_switch_plan(self, period, transfer_usage=False):
        """Pasa la membresía al plan/duración ``period`` desde hoy: lista de precios y saldos del mes."""
        self.ensure_one()
        today = self.env['spa.tools'].local_today()
        old_plan = self.plan_id
        month_start, _end = self.env['spa.tools'].month_bounds(today)
        old_entitlements = self.sudo().entitlement_ids.filtered(lambda e: e.period_start >= month_start)
        old_pricelist = old_plan.pricelist_id
        self.write({'plan_id': period.plan_id.id, 'period_id': period.id, 'spa_next_plan_id': False,
                    'spa_next_period_id': False, 'spa_plan_switch_date': False})
        partner = self.partner_id.with_company(self.company_id)
        new_pricelist = period.plan_id.pricelist_id
        if old_pricelist and old_pricelist != new_pricelist \
                and partner.specific_property_product_pricelist == old_pricelist:
            partner.sudo().specific_property_product_pricelist = new_pricelist
        self._apply_partner_pricelist()
        if self.state in ACCESS_STATES:
            self._ensure_entitlements(today)
            if transfer_usage:
                self._spa_transfer_usage(old_entitlements)
        self.message_post(body=self.env._('Cambio de plan: %(old)s → %(new)s (%(period)s).', old=old_plan.name,
                                          new=period.plan_id.name, period=period.name))
        return True

    def _spa_transfer_usage(self, old_entitlements):
        """Al subir de plan a mitad de mes, lo ya usado del mes cuenta contra el saldo del plan nuevo
        (mismo servicio): se mueven los consumos al saldo nuevo y se conserva el traslado del mes anterior."""
        self.ensure_one()
        Consumption = self.env['spa.consumption'].sudo().with_context(spa_consumption_internal=True)
        for old in old_entitlements.filtered(lambda e: e.plan_line_id.plan_id != self.plan_id):
            line = self.plan_id._line_for_service(old.service_id)
            if not line:
                continue
            self._ensure_entitlements(old.period_start)
            new = self.sudo().entitlement_ids.filtered(
                lambda e: e.plan_line_id == line and e.period_start == old.period_start)[:1]
            if not new or new == old:
                continue
            if old.consumption_ids:
                Consumption.browse(old.consumption_ids.ids).write({'entitlement_id': new.id})
            if old.carried_in and not line.unlimited and not new.carried_in:
                new.sudo().carried_in = old.carried_in

    # ------------------------------------------------------------------
    # Devengo de planes prepagados
    # ------------------------------------------------------------------
    def _spa_create_deferral(self, invoice, start=None):
        """Programa el paso mensual de ingresos diferidos a ingresos (planes de más de un mes).

        ``start``: primer mes (diferencia por cambio de plan: desde hoy hasta el vencimiento).
        """
        self.ensure_one()
        membership = self.sudo()  # caja valida pagos sin permisos sobre el devengo (spa.deferral.line)
        if membership.deferral_line_ids.filtered(lambda d: d.invoice_id == invoice) or not self.date_end:
            return
        deferred_account = self._spa_deferred_account(self.company_id)
        lines = invoice.invoice_line_ids.filtered(lambda l: deferred_account and l.account_id == deferred_account)
        total = -sum(lines.mapped('balance'))
        if not lines or invoice.currency_id.is_zero(total):
            return
        period = invoice.spa_period_id or self.period_id
        if start:
            dates = []
            day = start
            while day <= self.date_end:
                dates.append(day)
                day = start + relativedelta(months=len(dates))
            dates = dates or [start]
        else:
            months = max(period.months, 1)
            period_start = self.date_end - relativedelta(months=months) + timedelta(days=1)
            dates = [period_start + relativedelta(months=index) for index in range(months)]
        count = len(dates)
        share = invoice.currency_id.round(total / count)
        distribution = period.plan_id.sudo().analytic_distribution or False
        vals = []
        for index, day in enumerate(dates):
            amount = share if index < count - 1 else invoice.currency_id.round(total - share * (count - 1))
            vals.append({
                'membership_id': self.id,
                'invoice_id': invoice.id,
                'date': day,
                'amount': amount,
                'deferred_account_id': deferred_account.id,
                'analytic_distribution': distribution,
            })
        self.env['spa.deferral.line'].sudo().create(vals)

    # ------------------------------------------------------------------
    # Cancelación: sin cobros pendientes ni devengo
    # ------------------------------------------------------------------
    def action_cancel(self):
        res = super().action_cancel()
        self._spa_after_cancel()
        return res

    def _spa_after_cancel(self):
        for membership in self.sudo().filtered(lambda m: m.state == 'cancelled'):
            reason = self.env._('Membresía %s cancelada: se anula el cobro pendiente.', membership.name)
            membership.invoice_ids.filtered(lambda m: m._spa_is_pending_charge())._spa_cancel_pending(reason)
            planned = membership.deferral_line_ids.filtered(lambda line: line.state == 'planned')
            if not planned:
                continue
            amount = sum(planned.mapped('amount'))
            planned._spa_cancel(self.env._('Membresía cancelada'))
            membership.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=self.env._('Ingreso diferido de una membresía cancelada'),
                note=self.env._(
                    'Se detuvo el devengo pendiente de %(amount)s. Si se devuelve el dinero, emita la nota de crédito '
                    'de la factura. Si NO hay devolución, reconozca el saldo como ingreso con «Reconocer ahora» en '
                    'Devengo de membresías (líneas anuladas).', amount=membership.currency_id.format(amount)),
                user_id=self.env.user.id)

    @api.model
    def _spa_cleanup_pending(self):
        """Ningún documento fiscal para renovaciones impagas: se anulan los cobros pendientes de membresías
        vencidas (renovación, cambio de plan) o canceladas (todos)."""
        drafts = self.env['account.move'].sudo().search([
            ('state', '=', 'draft'), ('spa_invoice_kind', 'in', list(PENDING_KINDS)),
            ('spa_membership_id.state', 'in', ('expired', 'cancelled'))])
        stale = drafts.filtered(lambda m: m.spa_membership_id.state == 'cancelled'
                                or m.spa_invoice_kind in ('renewal', 'upgrade'))
        for move in stale:
            move._spa_cancel_pending(self.env._('La membresía %(name)s está %(state)s: se anula el cobro pendiente.',
                                                name=move.spa_membership_id.name,
                                                state=dict(self._fields['state']._description_selection(self.env))[
                                                    move.spa_membership_id.state].lower()))
        return stale

    # ------------------------------------------------------------------
    # Avisos
    # ------------------------------------------------------------------
    def _spa_suspend_offset(self):
        """Días desde el vencimiento con que la escalera de cobranza suspende (o None)."""
        self.ensure_one()
        steps = self.env['spa.dunning.step'].sudo().search([
            ('company_id', '=', self.company_id.id), ('action', '=', 'suspend')], order='offset_days', limit=1)
        return steps.offset_days if steps else None

    def _spa_access_until(self):
        """Último día con acceso sin pagar: fin de la gracia del plan o el día anterior a la suspensión de la
        escalera de cobranza, lo que ocurra antes."""
        self.ensure_one()
        if not self.date_end:
            return False
        until = self.grace_until or self.date_end
        offset = self._spa_suspend_offset()
        if offset is not None:
            until = min(until, self.date_end + timedelta(days=offset - 1))
        return max(until, self.date_end)

    def _spa_notice_values(self):
        self.ensure_one()
        invoice = self._open_period_invoice()[:1]
        amount = invoice.amount_residual if invoice else (self.spa_next_period_id or self.period_id).price
        until = self._spa_access_until()
        return {
            'plan': self.plan_id.name,
            'vence': self.date_end.strftime('%d/%m/%Y') if self.date_end else '',
            'gracia': until.strftime('%d/%m/%Y') if until else '',
            'monto': self.currency_id.format(amount),
        }

    def _spa_messaged_today(self, today=None):
        self.ensure_one()
        today = today or self.env['spa.tools'].local_today()
        return bool(self.env['spa.dunning.log'].sudo().search_count([
            ('membership_id', '=', self.id), ('date', '=', today), ('message_id', '!=', False)], limit=1))

    def _spa_notify(self, template_code, values=None, log_vals=None, today=None):
        """Genera el WhatsApp y lo registra en la bitácora de cobranza."""
        self.ensure_one()
        message = self.env['spa.message'].queue(template_code, self.partner_id,
                                                values or self._spa_notice_values(), record=self)
        vals = {
            'membership_id': self.id,
            'date': today or self.env['spa.tools'].local_today(),
            'period_end': self.date_end,
            'kind': 'transition',
            'action': 'notify',
            'result': 'done',
            'message_id': message.id,
            'note': False if message else self.env._('Sin celular válido o plantilla inactiva: no se generó el mensaje.'),
        }
        vals.update(log_vals or {})
        self.env['spa.dunning.log'].sudo().create(vals)
        return message

    def _spa_has_pending_payment(self):
        self.ensure_one()
        return bool(self.env['spa.payment.request'].sudo().search_count([
            ('membership_id', '=', self.id), ('state', '=', 'pending')], limit=1))

    # ------------------------------------------------------------------
    # Procesos diarios: renovación, mora, cuotas, cargos y devengo
    # ------------------------------------------------------------------
    @api.model
    def _cron_membership_daily(self):
        before = {m.id: m.state for m in self.search([('state', 'in', ('active', 'grace'))])}
        res = super()._cron_membership_daily()
        changed = self.browse(list(before)).filtered(lambda m: m.state != before[m.id])
        for membership in changed:
            if membership.state == 'grace':
                membership._spa_notify('grace_notice')
            elif membership.state == 'suspended':
                membership._spa_notify('suspended_notice')
        self._spa_cleanup_pending()
        return res

    @api.model
    def _cron_billing_daily(self):
        today = self.env['spa.tools'].local_today()
        # 0. Cambios de plan a la baja que empiezan hoy (período ya pagado)
        for membership in self.search([('spa_plan_switch_date', '!=', False), ('spa_plan_switch_date', '<=', today),
                                       ('spa_next_period_id', '!=', False)]):
            membership._spa_switch_plan(membership.spa_next_period_id)
        # 1. Cobros de renovación (borrador; el aviso lo envía la escalera de cobranza)
        for membership in self.search([('state', 'in', LIVE_STATES), ('auto_renew', '=', True)]):
            days = membership.company_id.spa_renewal_days
            if membership.date_end and membership.date_end - timedelta(days=days) <= today \
                    and not membership._open_period_invoice():
                membership.action_create_invoice()
        # 2. Facturas de cargos de meses anteriores: el servicio ya se prestó, se emiten al cerrar el mes
        month_start, _end = self.env['spa.tools'].month_bounds(today)
        old_charges = self.env['account.move'].sudo().search([
            ('spa_invoice_kind', '=', 'charges'), ('state', '=', 'draft'), ('invoice_date', '<', month_start)])
        for invoice in old_charges:
            invoice.write({'invoice_date': today, 'invoice_date_due': today})
            invoice.action_post()
        # 3. Devengo mensual
        self.env['spa.deferral.line']._cron_post_deferrals()
        # 4. Cobros pendientes de membresías vencidas o canceladas
        self._spa_cleanup_pending()
        # 5. Escalera de cobranza y cuotas vencidas
        self._spa_run_dunning(today)
        self._spa_run_installments(today)
        return True

    # ------------------------------------------------------------------
    # Escalera de cobranza (spa.dunning.step)
    # ------------------------------------------------------------------
    @api.model
    def _spa_run_dunning(self, today=None):
        today = today or self.env['spa.tools'].local_today()
        steps = self.env['spa.dunning.step'].sudo().search([])
        by_company = {}
        for step in steps:
            by_company.setdefault(step.company_id.id, self.env['spa.dunning.step'].sudo())
            by_company[step.company_id.id] |= step
        if not by_company:
            return True
        memberships = self.sudo().search([
            ('state', 'in', LIVE_STATES), ('auto_renew', '=', True), ('date_end', '!=', False),
            ('company_id', 'in', list(by_company))])
        for membership in memberships:
            company_steps = by_company[membership.company_id.id]
            due = company_steps.filtered(lambda s: membership.date_end + timedelta(days=s.offset_days) <= today)
            if not due:
                continue
            done = self.env['spa.dunning.log'].sudo().search([
                ('membership_id', '=', membership.id), ('period_end', '=', membership.date_end),
                ('step_id', 'in', due.ids)]).step_id
            todo = due - done
            if not todo or membership._spa_has_pending_payment():
                continue  # con un comprobante por validar no se insiste: se revisa al día siguiente
            membership._spa_apply_dunning_steps(todo, today)
        return True

    def _spa_apply_dunning_steps(self, steps, today):
        """Aplica los pasos vencidos una sola vez por período. De los avisos atrasados solo se envía el más
        reciente, y nunca más de un mensaje de cobranza por día al mismo socio."""
        self.ensure_one()
        Log = self.env['spa.dunning.log'].sudo()
        base = {'membership_id': self.id, 'date': today, 'period_end': self.date_end, 'kind': 'step'}
        for step in steps.filtered(lambda s: s.action == 'suspend').sorted('offset_days'):
            vals = dict(base, step_id=step.id, action='suspend')
            if self.state in ACCESS_STATES:
                self.action_suspend()
                self.message_post(body=self.env._('Suspendida por falta de pago (escalera de cobranza: %s).',
                                                  step.name))
                message = self.env['spa.message']
                if step.template_id and not self._spa_messaged_today(today):
                    message = self.env['spa.message'].queue(step.template_id.code, self.partner_id,
                                                            self._spa_notice_values(), record=self)
                Log.create(dict(vals, result='done', message_id=message.id))
            else:
                Log.create(dict(vals, result='skipped', note=self.env._('La membresía ya estaba suspendida.')))
        notify = steps.filtered(lambda s: s.action == 'notify').sorted('offset_days')
        latest = notify[-1:]
        for step in notify - latest:
            Log.create(dict(base, step_id=step.id, action='notify', result='skipped',
                            note=self.env._('Aviso atrasado: se envía solo el más reciente.')))
        if latest:
            vals = dict(base, step_id=latest.id, action='notify')
            if self._spa_messaged_today(today):
                Log.create(dict(vals, result='skipped', note=self.env._('El socio ya recibió un aviso hoy.')))
            elif not latest.template_id:
                Log.create(dict(vals, result='skipped', note=self.env._('El paso no tiene plantilla de mensaje.')))
            else:
                values = dict(self._spa_notice_values(), dias=abs(latest.offset_days))
                message = self.env['spa.message'].queue(latest.template_id.code, self.partner_id, values, record=self)
                Log.create(dict(vals, result='done', message_id=message.id, note=False if message else self.env._(
                    'Sin celular válido o plantilla inactiva: no se generó el mensaje.')))
        return True

    # ------------------------------------------------------------------
    # Cuotas vencidas (planes en cuotas)
    # ------------------------------------------------------------------
    @api.model
    def _spa_overdue_installments(self, today=None, min_days=0):
        """Cuotas (apuntes por cobrar) impagas de facturas de membresía vencidas hace ``min_days`` días o más."""
        today = today or self.env['spa.tools'].local_today()
        domain = [
            ('move_id.state', '=', 'posted'), ('move_id.spa_membership_id', '!=', False),
            ('move_id.spa_offer_id.offer_type', '=', 'installments'), ('display_type', '=', 'payment_term'),
            ('reconciled', '=', False), ('amount_residual', '>', 0),
            ('date_maturity', '<=', today - timedelta(days=max(min_days, 0)))]
        if self:
            domain.append(('move_id.spa_membership_id', 'in', self.ids))
        return self.env['account.move.line'].sudo().search(domain, order='date_maturity, id')

    @api.model
    def _spa_run_installments(self, today=None):
        """Aviso por WhatsApp a los N días de vencida una cuota y suspensión a los M días (Ajustes)."""
        today = today or self.env['spa.tools'].local_today()
        Log = self.env['spa.dunning.log'].sudo()
        for line in self._spa_overdue_installments(today, min_days=1):
            membership = line.move_id.spa_membership_id
            company = membership.company_id
            remind, suspend = company.spa_installment_reminder_days, company.spa_installment_suspend_days
            days = (today - line.date_maturity).days
            if membership.state not in LIVE_STATES or membership._spa_has_pending_payment():
                continue
            values = dict(membership._spa_notice_values(), monto=line.currency_id.format(line.amount_residual),
                          fecha=line.date_maturity.strftime('%d/%m/%Y'))
            logged = Log.search([('move_line_id', '=', line.id)]).mapped('action')
            base = {'membership_id': membership.id, 'date': today, 'period_end': membership.date_end,
                    'kind': 'installment', 'move_line_id': line.id}
            if suspend and days >= suspend and 'suspend' not in logged:
                if membership.state in ACCESS_STATES:
                    membership.action_suspend()
                    membership.spa_installment_suspended = True
                    membership.message_post(body=self.env._(
                        'Suspendida por la cuota vencida el %(date)s (%(amount)s).',
                        date=values['fecha'], amount=values['monto']))
                    message = self.env['spa.message']
                    if not membership._spa_messaged_today(today):
                        message = self.env['spa.message'].queue('installment_suspended', membership.partner_id,
                                                                values, record=membership)
                    Log.create(dict(base, action='suspend', result='done', message_id=message.id))
                else:
                    Log.create(dict(base, action='suspend', result='skipped',
                                    note=self.env._('La membresía ya estaba suspendida.')))
            elif remind and days >= remind and not {'notify', 'suspend'} & set(logged):
                if membership._spa_messaged_today(today):
                    continue  # se reintenta mañana
                message = self.env['spa.message'].queue('installment_reminder', membership.partner_id, values,
                                                        record=membership)
                Log.create(dict(base, action='notify', result='done', message_id=message.id,
                                note=False if message else self.env._('Sin celular válido: no se generó el mensaje.')))
        return True

    def _spa_resume_after_installment(self):
        """Reactiva la membresía suspendida por una cuota cuando ya no hay cuotas atrasadas fuera de plazo."""
        today = self.env['spa.tools'].local_today()
        for membership in self.filtered(lambda m: m.spa_installment_suspended):
            suspend_days = membership.company_id.spa_installment_suspend_days
            if membership._spa_overdue_installments(today, min_days=suspend_days or 0):
                continue
            membership.spa_installment_suspended = False
            if membership.state != 'suspended':
                continue
            membership.state = 'active'
            membership._apply_partner_pricelist()
            membership._ensure_entitlements(today)
            membership.message_post(body=self.env._('Reactivada: la cuota atrasada fue pagada.'))
            self.env['spa.dunning.log'].sudo().create({
                'membership_id': membership.id, 'date': today, 'period_end': membership.date_end,
                'kind': 'installment', 'action': 'reactivate', 'result': 'done'})
        return True

    # ------------------------------------------------------------------
    # Cambio de plan
    # ------------------------------------------------------------------
    def action_open_plan_change(self):
        self.ensure_one()
        if self.state not in ACCESS_STATES:
            raise UserError(self.env._('Solo se cambia de plan una membresía activa o en gracia.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cambiar de plan'),
            'res_model': 'spa.plan.change',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_membership_id': self.id},
        }

    def _spa_refresh_renewal(self):
        """Rehace el cobro de renovación pendiente (borrador) con el plan que corresponda."""
        self.ensure_one()
        renewal = self._open_period_invoice().filtered(lambda m: m.spa_invoice_kind == 'renewal')
        if not renewal:
            return self.env['account.move']
        if renewal.filtered(lambda m: m.state == 'posted'):
            raise UserError(self.env._(
                'La renovación %s ya fue emitida: cóbrela (o anúlela con una nota de crédito) antes de cambiar el plan '
                'del próximo período.', renewal.filtered(lambda m: m.state == 'posted')[:1].name))
        renewal._spa_cancel_pending(self.env._('Cambio de plan: se rehace el cobro de renovación.'))
        return self.action_create_invoice()

    def _spa_apply_upgrade(self, period, amount):
        """Sube de plan desde hoy. Devuelve el cobro pendiente de la diferencia prorrateada (o vacío)."""
        self.ensure_one()
        old = self.period_id
        self._spa_switch_plan(period, transfer_usage=True)
        invoice = self.env['account.move']
        if self.currency_id.compare_amounts(amount, 0.0) > 0:
            line = self._spa_line_vals(
                period.product_id, price=amount,
                name=self.env._('Cambio de plan %(old)s → %(new)s, del %(start)s al %(end)s (%(name)s)',
                                old=old.plan_id.name, new=period.plan_id.name,
                                start=self.env['spa.tools'].local_today().strftime('%d/%m/%Y'),
                                end=self.date_end.strftime('%d/%m/%Y'), name=self.name),
                distribution=self._spa_plan_distribution(period))
            invoice = self._spa_create_invoice('upgrade', [line], period=period)
        self._spa_refresh_renewal()
        return invoice

    def _spa_schedule_downgrade(self, period):
        """Baja de plan desde el próximo período: se cobra en la renovación y rige al empezar ese período."""
        self.ensure_one()
        self.write({'spa_next_plan_id': period.plan_id.id, 'spa_next_period_id': period.id,
                    'spa_plan_switch_date': False})
        self.message_post(body=self.env._('Cambio de plan programado: %(plan)s (%(period)s) desde el próximo período.',
                                          plan=period.plan_id.name, period=period.name))
        self._spa_refresh_renewal()
        return True

    def action_cancel_plan_change(self):
        for membership in self:
            if membership.spa_plan_switch_date:
                raise UserError(self.env._('El próximo período ya se pagó con el nuevo plan: no se puede anular.'))
            membership.write({'spa_next_plan_id': False, 'spa_next_period_id': False})
            membership.message_post(body=self.env._('Se anuló el cambio de plan programado.'))
            membership._spa_refresh_renewal()
        return True
