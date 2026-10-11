# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaMembership(models.Model):
    _inherit = 'spa.membership'

    invoice_ids = fields.One2many('account.move', 'spa_membership_id', string='Facturas')
    invoice_count = fields.Integer(compute='_compute_billing')
    amount_due = fields.Monetary('Saldo por cobrar', compute='_compute_billing')
    payment_request_ids = fields.One2many('spa.payment.request', 'membership_id', string='Pagos informados')
    deferral_line_ids = fields.One2many('spa.deferral.line', 'membership_id', string='Devengo')
    offer_id = fields.Many2one('spa.payment.offer', string='Oferta de pago',
                               help='Descuento o cuotas para la próxima factura de este socio.')
    auto_renew = fields.Boolean('Renovación con aviso', default=True,
                                help='Genera la factura de renovación y el aviso antes del vencimiento.')

    @api.depends('invoice_ids.amount_residual', 'invoice_ids.state')
    def _compute_billing(self):
        for membership in self:
            invoices = membership.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
            membership.invoice_count = len(invoices)
            membership.amount_due = sum(invoices.filtered(lambda m: m.state == 'posted').mapped('amount_residual'))

    # ------------------------------------------------------------------
    # Facturación
    # ------------------------------------------------------------------
    @api.model
    def _spa_line_vals(self, product, quantity=1.0, price=None, name=None, discount=0.0, analytic=None):
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
        return vals

    def _open_period_invoice(self):
        self.ensure_one()
        return self.invoice_ids.filtered(
            lambda m: m.spa_invoice_kind in ('membership', 'renewal') and not m.spa_period_applied
            and m.state in ('draft', 'posted') and m.payment_state not in ('paid', 'reversed'))

    def action_create_invoice(self, offer=None, post=True):
        """Factura del período (alta o renovación). Devuelve la factura."""
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(self.env._('La membresía está cancelada.'))
        existing = self._open_period_invoice()
        if existing:
            return existing[:1]
        kind = 'membership' if self.state in ('draft', 'expired') else 'renewal'
        offer = offer or self.offer_id
        if offer and not offer._is_applicable(self.period_id, self.partner_id, self.env['spa.tools'].local_today()):
            offer = self.env['spa.payment.offer']
        period = self.period_id
        line = self._spa_line_vals(
            period.product_id, price=period.price,
            name=self.env._('Membresía %(plan)s – %(period)s (%(name)s)', plan=self.plan_id.name,
                            period=period.name, name=self.name),
            discount=offer.discount_percent if offer and offer.offer_type == 'discount' else 0.0)
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'spa_membership_id': self.id,
            'spa_invoice_kind': kind,
            'spa_offer_id': offer.id if offer else False,
            'invoice_line_ids': [(0, 0, line)],
            'company_id': self.company_id.id,
        }
        if offer and offer.offer_type == 'installments':
            vals['invoice_payment_term_id'] = offer._get_payment_term().id
        invoice = self.env['account.move'].sudo().create(vals)
        if post:
            invoice.action_post()
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
        invoice = self._open_period_invoice()[:1] or self.action_create_invoice()
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
                'default_amount': invoice.amount_residual,
                'default_channel': 'reception',
            },
        }

    def _spa_add_charge(self, product, name=None, analytic=None, quantity=1.0):
        """Agrega un cargo (invitado, penalidad) a la factura de cargos del mes (borrador).

        Devuelve la línea de factura creada.
        """
        self.ensure_one()
        if not product:
            return self.env['account.move.line']
        tools = self.env['spa.tools']
        month_start, _month_end = tools.month_bounds(tools.local_today())
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
                'invoice_date': fields.Date.context_today(self),
                'invoice_origin': self.env._('Cargos %s', self.name),
                'spa_membership_id': self.id,
                'spa_invoice_kind': 'charges',
                'invoice_line_ids': [(0, 0, line)],
                'company_id': self.company_id.id,
            })
        invoice.message_post(body=self.env._('Cargo agregado: %s', line['name']))
        return (invoice.invoice_line_ids - before)[-1:]

    # ------------------------------------------------------------------
    # Devengo de planes prepagados
    # ------------------------------------------------------------------
    def _spa_create_deferral(self, invoice):
        """Programa el paso mensual de ingresos diferidos a ingresos (planes de más de un mes)."""
        self.ensure_one()
        months = self.period_id.months
        if months <= 1 or self.deferral_line_ids.filtered(lambda d: d.invoice_id == invoice):
            return
        prepaid_categ = self.env.ref('l10n_bo_spa.categ_membership_prepaid', raise_if_not_found=False)
        deferred_account = prepaid_categ.with_company(self.company_id).property_account_income_categ_id \
            if prepaid_categ else self.env['account.account']
        lines = invoice.invoice_line_ids.filtered(lambda l: l.account_id == deferred_account)
        total = -sum(lines.mapped('balance'))
        if not lines or invoice.currency_id.is_zero(total):
            return
        period_start = self.date_end - relativedelta(months=months) + timedelta(days=1)
        share = invoice.currency_id.round(total / months)
        vals = []
        for index in range(months):
            amount = share if index < months - 1 else invoice.currency_id.round(total - share * (months - 1))
            vals.append({
                'membership_id': self.id,
                'invoice_id': invoice.id,
                'date': period_start + relativedelta(months=index),
                'amount': amount,
                'deferred_account_id': deferred_account.id,
            })
        self.env['spa.deferral.line'].sudo().create(vals)

    # ------------------------------------------------------------------
    # Procesos diarios: renovación, mora y cargos
    # ------------------------------------------------------------------
    def _spa_notice_values(self):
        self.ensure_one()
        invoice = self._open_period_invoice()[:1]
        amount = invoice.amount_residual if invoice else self.period_id.price
        return {
            'plan': self.plan_id.name,
            'vence': self.date_end.strftime('%d/%m/%Y') if self.date_end else '',
            'gracia': self.grace_until.strftime('%d/%m/%Y') if self.grace_until else '',
            'monto': self.currency_id.format(amount),
        }

    @api.model
    def _cron_membership_daily(self):
        before = {m.id: m.state for m in self.search([('state', 'in', ('active', 'grace'))])}
        res = super()._cron_membership_daily()
        changed = self.browse(list(before)).filtered(lambda m: m.state != before[m.id])
        for membership in changed:
            if membership.state == 'grace':
                self.env['spa.message'].queue('grace_notice', membership.partner_id,
                                              membership._spa_notice_values(), record=membership)
            elif membership.state == 'suspended':
                self.env['spa.message'].queue('suspended_notice', membership.partner_id,
                                              membership._spa_notice_values(), record=membership)
        return res

    @api.model
    def _cron_billing_daily(self):
        today = self.env['spa.tools'].local_today()
        # 1. Facturas y avisos de renovación
        for membership in self.search([('state', 'in', ('active', 'grace', 'suspended')), ('auto_renew', '=', True)]):
            days = membership.company_id.spa_renewal_days
            if membership.date_end and membership.date_end - timedelta(days=days) <= today \
                    and not membership._open_period_invoice():
                membership.action_create_invoice()
                self.env['spa.message'].queue('renewal_notice', membership.partner_id,
                                              membership._spa_notice_values(), record=membership)
        # 2. Facturas de cargos de meses anteriores
        month_start, _end = self.env['spa.tools'].month_bounds(today)
        old_charges = self.env['account.move'].sudo().search([
            ('spa_invoice_kind', '=', 'charges'), ('state', '=', 'draft'), ('invoice_date', '<', month_start)])
        for invoice in old_charges:
            invoice.invoice_date = today
            invoice.action_post()
        # 3. Devengo mensual
        self.env['spa.deferral.line']._cron_post_deferrals()
        return True
