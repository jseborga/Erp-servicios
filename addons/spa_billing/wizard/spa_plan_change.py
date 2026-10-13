# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaPlanChange(models.TransientModel):
    """Cambio de plan de una membresía vigente.

    * Subir (el plan nuevo cuesta más por mes): rige desde hoy y se cobra la diferencia prorrateada
      = (precio mensual nuevo − precio mensual actual) × meses del período × días que faltan / días del período.
      Para un plan mensual: (nuevo − actual) × días que faltan / días del mes. El cobro nace pendiente y se
      factura al pagarlo.
    * Bajar: rige desde el próximo período; la renovación se cobra con el plan nuevo.
    """
    _name = 'spa.plan.change'
    _description = 'Cambio de plan de una membresía'

    membership_id = fields.Many2one('spa.membership', string='Membresía', required=True, readonly=True)
    partner_id = fields.Many2one(related='membership_id.partner_id')
    company_id = fields.Many2one(related='membership_id.company_id')
    currency_id = fields.Many2one(related='membership_id.currency_id')
    current_period_id = fields.Many2one(related='membership_id.period_id', string='Plan actual')
    current_plan_id = fields.Many2one(related='membership_id.plan_id', string='Plan')
    date_end = fields.Date(related='membership_id.date_end', string='Vence')
    new_plan_id = fields.Many2one('spa.plan', string='Nuevo plan', required=True,
                                  domain="[('id', '!=', current_plan_id), ('company_id', '=', company_id)]")
    new_period_id = fields.Many2one('spa.plan.period', string='Duración', required=True,
                                    compute='_compute_new_period_id', store=True, readonly=False, precompute=True,
                                    domain="[('plan_id', '=', new_plan_id), ('active', '=', True)]")
    change_type = fields.Selection([('upgrade', 'Subir de plan (desde hoy)'), ('downgrade', 'Bajar de plan (desde '
                                                                                            'el próximo período)')],
                                   string='Tipo de cambio', compute='_compute_amounts')
    remaining_days = fields.Integer('Días que faltan', compute='_compute_amounts')
    period_days = fields.Integer('Días del período', compute='_compute_amounts')
    amount = fields.Monetary('Diferencia a cobrar', compute='_compute_amounts',
                             help='Precio mensual nuevo − actual, por los días que faltan del período (sin descuentos).')
    effective_date = fields.Date('Rige desde', compute='_compute_amounts')
    summary = fields.Text('Resumen', compute='_compute_amounts')

    @api.depends('new_plan_id', 'membership_id')
    def _compute_new_period_id(self):
        for wizard in self:
            months = wizard.membership_id.period_id.months
            periods = wizard.new_plan_id.period_ids.filtered('active')
            wizard.new_period_id = periods.filtered(lambda p: p.months == months)[:1] or periods[:1]

    def _period_bounds(self):
        self.ensure_one()
        membership = self.membership_id
        months = membership.period_id.months or 1
        end = membership.date_end
        start = end + timedelta(days=1) - relativedelta(months=months)
        return start, end

    @api.depends('new_period_id', 'membership_id')
    def _compute_amounts(self):
        today = self.env['spa.tools'].local_today()
        for wizard in self:
            membership = wizard.membership_id
            old, new = membership.period_id, wizard.new_period_id
            if not (membership.date_end and new):
                wizard.update({'change_type': False, 'remaining_days': 0, 'period_days': 0, 'amount': 0.0,
                               'effective_date': False, 'summary': False})
                continue
            start, end = wizard._period_bounds()
            period_days = (end - start).days + 1
            remaining = max(min((end - today).days + 1, period_days), 0)
            diff_month = new.monthly_price - old.monthly_price
            upgrade = membership.currency_id.compare_amounts(diff_month, 0.0) > 0
            amount = membership.currency_id.round(
                diff_month * (old.months or 1) * remaining / period_days) if upgrade and period_days else 0.0
            currency = membership.currency_id
            if upgrade:
                summary = self.env._(
                    '%(new)s rige desde hoy. Diferencia: (%(new_month)s − %(old_month)s por mes) × %(days)s de '
                    '%(total)s días = %(amount)s. La renovación se cobra con el plan nuevo.',
                    new=new.display_name, new_month=currency.format(new.monthly_price),
                    old_month=currency.format(old.monthly_price), days=remaining, total=period_days,
                    amount=currency.format(amount))
            else:
                summary = self.env._(
                    'Mantiene %(old)s hasta el %(end)s. Desde el %(next)s pasa a %(new)s: la renovación se cobra '
                    '%(price)s.', old=old.plan_id.name, end=end.strftime('%d/%m/%Y'),
                    next=(end + timedelta(days=1)).strftime('%d/%m/%Y'), new=new.display_name,
                    price=currency.format(new.price))
            wizard.update({
                'change_type': 'upgrade' if upgrade else 'downgrade',
                'remaining_days': remaining,
                'period_days': period_days,
                'amount': amount,
                'effective_date': today if upgrade else end + timedelta(days=1),
                'summary': summary,
            })

    def action_confirm(self):
        self.ensure_one()
        membership = self.membership_id
        if membership.state not in ('active', 'grace'):
            raise UserError(self.env._('Solo se cambia de plan una membresía activa o en gracia.'))
        if membership.spa_plan_switch_date:
            raise UserError(self.env._('El próximo período ya está pagado con otro plan (cambia el %s).',
                                       membership.spa_plan_switch_date.strftime('%d/%m/%Y')))
        new = self.new_period_id
        if new.plan_id != self.new_plan_id or new.plan_id == membership.plan_id:
            raise UserError(self.env._('Elija un plan distinto del actual y una de sus duraciones.'))
        if self.change_type == 'upgrade':
            if new.months != membership.period_id.months:
                raise UserError(self.env._(
                    'Para subir de plan a mitad de período elija la misma duración (%(months)s mes/es). El cambio de '
                    'duración se hace en la renovación.', months=membership.period_id.months))
            invoice = membership._spa_apply_upgrade(new, self.amount)
            if invoice:
                return self._open_payment(invoice)
            return {'type': 'ir.actions.act_window_close'}
        membership._spa_schedule_downgrade(new)
        return {'type': 'ir.actions.act_window_close'}

    def _open_payment(self, invoice):
        membership = self.membership_id
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar pago del cambio de plan'),
            'res_model': 'spa.payment.request',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': membership.partner_id.id,
                'default_membership_id': membership.id,
                'default_invoice_id': invoice.id,
                'default_amount': invoice._spa_amount_to_pay(),
                'default_channel': 'reception',
            },
        }
