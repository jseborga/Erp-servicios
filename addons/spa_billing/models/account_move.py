# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.exceptions import UserError

INVOICE_KINDS = [
    ('membership', 'Membresía (alta)'),
    ('renewal', 'Renovación'),
    ('upgrade', 'Cambio de plan (diferencia prorrateada)'),
    ('single', 'Servicio suelto'),
    ('charges', 'Cargos del mes (invitados, penalidades)'),
]
# Cobros que nacen en borrador («cobro pendiente») y se emiten (publican) al cobrarlos: el hecho
# imponible del IVA en servicios es la prestación o el cobro, lo que ocurra primero (Ley 843 art. 4 b).
PENDING_KINDS = ('membership', 'renewal', 'upgrade', 'single')
PERIOD_KINDS = ('membership', 'renewal')


class AccountMove(models.Model):
    _inherit = 'account.move'

    spa_membership_id = fields.Many2one('spa.membership', string='Membresía', index=True, copy=False)
    spa_invoice_kind = fields.Selection(INVOICE_KINDS, string='Tipo de cobro del spa', copy=False)
    spa_period_applied = fields.Boolean('Período aplicado', copy=False,
                                        help='La membresía ya fue activada o extendida con esta factura.')
    spa_offer_id = fields.Many2one('spa.payment.offer', string='Oferta aplicada', copy=False)
    spa_period_id = fields.Many2one('spa.plan.period', string='Plan y duración cobrados', copy=False,
                                    help='Duración (y plan) que paga esta factura. Puede ser distinta de la actual '
                                         'si el socio cambió de plan para el próximo período.')

    # ------------------------------------------------------------------
    # Cobros pendientes (borrador) → factura emitida al cobrar
    # ------------------------------------------------------------------
    def _spa_is_pending_charge(self):
        self.ensure_one()
        return self.state == 'draft' and self.spa_invoice_kind in PENDING_KINDS

    def _spa_is_due(self):
        """Cuenta como saldo por cobrar: factura publicada con saldo o cobro pendiente en borrador."""
        self.ensure_one()
        if self.move_type != 'out_invoice':
            return False
        return self.state == 'posted' or self._spa_is_pending_charge()

    def _spa_payment_reference(self):
        """Referencia que el socio pone en su transferencia: el número de factura o, si aún es un cobro
        pendiente, el número de la membresía o de la reserva."""
        self.ensure_one()
        if self.name and self.name != '/':
            return self.payment_reference or self.name
        return self.invoice_origin or self.spa_membership_id.name or ''

    def _spa_due_date(self):
        """Fecha límite de pago para el socio: la renovación pendiente vence con la membresía."""
        self.ensure_one()
        if self._spa_is_pending_charge() and self.spa_invoice_kind == 'renewal' and self.spa_membership_id.date_end:
            return self.spa_membership_id.date_end
        return self.invoice_date_due

    def _spa_document_label(self):
        self.ensure_one()
        if self.state == 'draft':
            return self.env._('Cobro pendiente %s', self._spa_payment_reference())
        return self.name

    def _spa_amount_to_pay(self):
        """Monto sugerido: la cuota que corresponde (planes en cuotas) o el saldo."""
        self.ensure_one()
        if self.amount_residual <= 0:
            return 0.0
        values = self._get_invoice_next_payment_values() or {}
        if values.get('installment_state') in ('next', 'overdue') and values.get('next_amount_to_pay'):
            return values['next_amount_to_pay']
        return self.amount_residual

    def _spa_post_pending(self):
        """Emite los cobros pendientes con la fecha de hoy (hora del spa). Devuelve las facturas emitidas."""
        today = self.env['spa.tools'].local_today()
        moves = self.sudo().filtered(lambda m: m._spa_is_pending_charge())
        for move in moves:
            vals = {'invoice_date': today}
            if not move.invoice_payment_term_id:
                vals['invoice_date_due'] = today
            move.write(vals)
        if moves:
            moves.action_post()
        return moves

    def _spa_cancel_pending(self, reason=None):
        """Anula cobros pendientes (borradores): nunca llegan a ser documento fiscal."""
        drafts = self.sudo().filtered(lambda m: m.state == 'draft')
        for move in drafts:
            if reason:
                move.message_post(body=reason)
        if drafts:
            drafts.button_cancel()
        return drafts

    # ------------------------------------------------------------------
    # Pago: activar o extender la membresía
    # ------------------------------------------------------------------
    def _invoice_paid_hook(self):
        res = super()._invoice_paid_hook()
        self._spa_apply_period()
        self._spa_after_payment()
        return res

    def _spa_apply_period(self, partial=False):
        """Activa o extiende la membresía al pagar (o al pagar la primera cuota)."""
        today = self.env['spa.tools'].local_today()
        for move in self.filtered(lambda m: m.spa_membership_id and m.spa_invoice_kind in PERIOD_KINDS + ('upgrade',)
                                  and not m.spa_period_applied and m.state == 'posted'):
            if partial and not (move.spa_offer_id.offer_type == 'installments'
                                and move.amount_residual < move.amount_total):
                continue
            move.spa_period_applied = True
            membership = move.spa_membership_id
            if move.spa_invoice_kind == 'upgrade':
                # El cambio de plan ya rige: solo se programa el devengo de la diferencia.
                membership._spa_create_deferral(move, start=today)
                continue
            membership._spa_activate_period(move)
            membership._spa_create_deferral(move)
            self.env['spa.message'].queue('payment_validated', membership.partner_id, {
                'monto': move.currency_id.format(move.amount_total - move.amount_residual),
                'plan': membership.plan_id.name,
                'vence': membership.date_end.strftime('%d/%m/%Y'),
            }, record=membership)

    def _spa_after_payment(self):
        """Reactiva las membresías suspendidas por una cuota vencida cuando ya no deben cuotas atrasadas."""
        memberships = self.filtered(lambda m: m.state == 'posted').spa_membership_id
        memberships.filtered('spa_installment_suspended')._spa_resume_after_installment()

    # ------------------------------------------------------------------
    # Devengo: notas de crédito y anulaciones
    # ------------------------------------------------------------------
    def _spa_deferral_lines(self):
        return self.env['spa.deferral.line'].sudo().search([('invoice_id', 'in', self.ids)])

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for refund in posted.filtered(lambda m: m.move_type == 'out_refund'
                                      and m.reversed_entry_id.spa_membership_id):
            refund.reversed_entry_id._spa_on_refunded(refund)
        return posted

    def _spa_on_refunded(self, refund):
        """Nota de crédito de una factura con ingreso diferido: 215100 queda igual al devengo pendiente.

        * Devuelve al menos lo que falta devengar: se anula el devengo pendiente y, si también devuelve meses
          ya reconocidos, se revierte ese ingreso (cuota negativa: Debe ingresos / Haber 215100).
        * Devuelve menos: las cuotas pendientes se reducen en proporción.
        """
        self.ensure_one()
        membership = self.spa_membership_id
        deferred = self.env['spa.membership']._spa_deferred_account(self.company_id)
        currency = self.company_currency_id
        refunded = currency.round(sum(refund.line_ids.filtered(lambda l: l.account_id == deferred).mapped('balance')))
        if not deferred or currency.compare_amounts(refunded, 0.0) <= 0:
            return
        Line = self.env['spa.deferral.line'].sudo()
        lines = self._spa_deferral_lines()
        if not lines:
            return
        pending = lines.filtered(lambda l: l.state == 'planned' or (l.state == 'cancelled' and not l.refund_move_id))
        pending_total = currency.round(sum(pending.mapped('amount')))
        reason = self.env._('Nota de crédito %(refund)s de %(invoice)s', refund=refund.name, invoice=self.name)
        if currency.compare_amounts(refunded, pending_total) >= 0:
            pending.write({'state': 'cancelled', 'refund_move_id': refund.id, 'cancel_reason': reason})
            excess = currency.round(refunded - pending_total)
            if not currency.is_zero(excess):
                reversal = Line.create({
                    'membership_id': membership.id, 'invoice_id': self.id, 'date': refund.date,
                    'amount': -excess, 'deferred_account_id': deferred.id, 'refund_move_id': refund.id,
                    'analytic_distribution': lines[:1].analytic_distribution,
                })
                reversal._post_line()
        else:
            remaining = currency.round(pending_total - refunded)
            ordered = pending.sorted(lambda l: (l.date, l.id))
            allocated = 0.0
            for index, line in enumerate(ordered):
                if index < len(ordered) - 1:
                    amount = currency.round(line.amount * remaining / pending_total)
                    allocated += amount
                else:
                    amount = currency.round(remaining - allocated)
                line.amount = amount
        membership.sudo().message_post(body=self.env._('Devengo ajustado por la %s.', reason))

    def button_cancel(self):
        res = super().button_cancel()
        cancelled = self.filtered(lambda m: m.state == 'cancel')
        lines = cancelled._spa_deferral_lines().filtered(lambda line: line.state == 'planned')
        lines._spa_cancel(self.env._('Factura anulada'))
        return res

    # ------------------------------------------------------------------
    # Asientos manuales: solo contabilidad (docs/10: caja no hace asientos manuales)
    # ------------------------------------------------------------------
    def _spa_is_automatic_entry(self):
        """Asiento generado por un proceso (pago, extracto bancario, POS), no escrito a mano."""
        self.ensure_one()
        if self.origin_payment_id or self.statement_line_id:
            return True
        return any(fname in self._fields and self[fname]
                   for fname in ('reversed_pos_order_id', 'pos_session_ids', 'pos_order_ids'))

    def _spa_check_manual_entry_rights(self):
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('account.group_account_user') or user.has_group('spa_base.group_spa_manager'):
            return
        manual = self.filtered(lambda m: m.move_type == 'entry' and not m._spa_is_automatic_entry())
        if manual:
            raise UserError(self.env._(
                'No tiene permiso para validar asientos manuales (%s). Caja registra cobros desde «Pagos por '
                'validar» o el punto de venta; los asientos manuales los hace el contador o el gerente.',
                ', '.join(manual.mapped('display_name'))))

    def action_post(self):
        self._spa_check_manual_entry_rights()
        return super().action_post()
