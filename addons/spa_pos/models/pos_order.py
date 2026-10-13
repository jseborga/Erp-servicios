# Part of ERP Servicios Spa. License LGPL-3.
from odoo import models
from odoo.exceptions import UserError

LIVE_STATES = ('active', 'grace')


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ------------------------------------------------------------------
    # Socio de la orden
    # ------------------------------------------------------------------
    def _spa_membership(self):
        """Membresía vigente (o suspendida) del cliente de la orden."""
        self.ensure_one()
        partner = self.partner_id.sudo()
        return partner.spa_membership_id or partner.commercial_partner_id.spa_membership_id

    def _spa_member_account_payments(self):
        return self.payment_ids.filtered(
            lambda p: p.payment_method_id.spa_member_account and not p.pos_order_id.currency_id.is_zero(p.amount))

    def _spa_member_account_amount(self):
        return sum(self._spa_member_account_payments().mapped('amount'))

    def _spa_check_member_account(self):
        """Cargo a la cuenta del socio: socio vigente y dentro del límite de crédito del plan."""
        for order in self:
            amount = order._spa_member_account_amount()
            if order.currency_id.compare_amounts(amount, 0) <= 0:
                continue  # sin cargo o devolución: reduce la deuda
            method = order._spa_member_account_payments()[:1].payment_method_id.name
            if not order.partner_id:
                raise UserError(self.env._(
                    'Para cobrar con "%s" seleccione al socio en la orden.', method))
            membership = order._spa_membership()
            if not membership or membership.state not in LIVE_STATES:
                states = dict(self.env['spa.membership']._fields['state']._description_selection(self.env))
                raise UserError(self.env._(
                    '%(partner)s no tiene una membresía vigente (%(state)s). Solo los socios activos o en '
                    'gracia pueden cargar consumos a su cuenta. Cobre con otro medio de pago.',
                    partner=order.partner_id.name,
                    state=states.get(membership.state) if membership else self.env._('no es socio')))
            plan = membership.plan_id
            limit = plan.pos_credit_limit
            currency = order.currency_id
            if currency.compare_amounts(limit, 0) <= 0:
                raise UserError(self.env._(
                    'El plan %(plan)s no permite cargar consumos a la cuenta del socio. Cobre con otro medio '
                    'de pago o configure el crédito en restaurante y cafetería del plan.', plan=plan.name))
            debt = order.partner_id._spa_pos_open_debt(order.company_id, exclude_orders=order)
            if currency.compare_amounts(debt + amount, limit) > 0:
                raise UserError(self.env._(
                    'El cargo de %(amount)s supera el crédito disponible de %(partner)s '
                    '(límite del plan %(plan)s: %(limit)s; deuda pendiente: %(debt)s; disponible: %(available)s). '
                    'Cobre la diferencia con otro medio de pago o pida al socio que pague su cuenta.',
                    amount=currency.format(amount), partner=order.partner_id.name, plan=plan.name,
                    limit=currency.format(limit), debt=currency.format(debt),
                    available=currency.format(max(limit - debt, 0.0))))

    def _spa_check_member_pricelist(self):
        """Una lista de precios de plan solo se aplica a socios vigentes de ese plan."""
        candidates = self.filtered(lambda o: o.config_id.spa_member_pricing and o.pricelist_id
                                   and not o.is_refund and o.currency_id.compare_amounts(o.amount_total, 0) > 0)
        if not candidates:
            return
        member_pricelists = self.env['spa.plan'].sudo().search([('pricelist_id', '!=', False)]).pricelist_id
        for order in candidates.filtered(lambda o: o.pricelist_id in member_pricelists):
            membership = order._spa_membership() if order.partner_id else self.env['spa.membership']
            if not membership or membership.state not in LIVE_STATES \
                    or membership.plan_id.pricelist_id != order.pricelist_id:
                raise UserError(self.env._(
                    'La lista de precios "%(pricelist)s" es solo para socios vigentes de su plan y %(partner)s '
                    'no la tiene. Seleccione al socio correcto o cambie la lista de precios de la orden.',
                    pricelist=order.pricelist_id.display_name,
                    partner=order.partner_id.name or self.env._('el cliente de la orden')))

    # ------------------------------------------------------------------
    # Cobro y facturación
    # ------------------------------------------------------------------
    def action_pos_order_paid(self):
        self._spa_check_member_pricelist()
        self._spa_check_member_account()
        return super().action_pos_order_paid()

    def _process_saved_order(self, draft):
        # Lo cargado a la cuenta del socio siempre se factura: la deuda queda en una factura que el
        # socio ve y paga desde su web (spa_invoice_kind = 'pos').
        if not draft and self.state != 'cancel' and not self.to_invoice and self._spa_member_account_payments():
            self.to_invoice = True
        return super()._process_saved_order(draft)

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        membership = self.env['spa.membership']
        for order in self:
            membership = membership or order._spa_membership()
        if membership or any(order._spa_member_account_payments() for order in self):
            vals['spa_invoice_kind'] = 'pos'
            if membership:
                vals['spa_membership_id'] = membership.id
        return vals

    # ------------------------------------------------------------------
    # Analítica por área
    # ------------------------------------------------------------------
    def _get_invoice_lines_values(self, line_values, pos_line, move_type):
        vals = super()._get_invoice_lines_values(line_values, pos_line, move_type)
        if not vals.get('display_type') and line_values.get('analytic_distribution') \
                and not vals.get('analytic_distribution'):
            vals['analytic_distribution'] = line_values['analytic_distribution']
        return vals

    def _prepare_product_aml_dict(self, base_line_vals, update_base_line_vals, rate, sign):
        # Asiento que revierte el cierre cuando se factura una orden de una sesión ya cerrada.
        vals = super()._prepare_product_aml_dict(base_line_vals, update_base_line_vals, rate, sign)
        if base_line_vals.get('analytic_distribution'):
            vals['analytic_distribution'] = base_line_vals['analytic_distribution']
        return vals


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    def _spa_analytic_distribution(self):
        self.ensure_one()
        return self.order_id.config_id._spa_analytic_distribution()

    def _prepare_base_line_for_taxes_computation(self):
        base_line = super()._prepare_base_line_for_taxes_computation()
        if not base_line.get('analytic_distribution'):
            distribution = self._spa_analytic_distribution()
            if distribution:
                base_line['analytic_distribution'] = distribution
        return base_line
