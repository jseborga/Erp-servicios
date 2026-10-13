# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError

PERIOD_NAMES = {1: 'Mensual', 3: 'Trimestral', 6: 'Semestral', 12: 'Anual'}


class SpaPlan(models.Model):
    _name = 'spa.plan'
    _description = 'Plan de membresía'
    _inherit = ['mail.thread']
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char('Plan', required=True, translate=True, tracking=True)
    code = fields.Char('Código')
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True, string='Activo')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    currency_id = fields.Many2one(related='company_id.currency_id')
    description = fields.Html('Descripción para la web', translate=True)
    website_published = fields.Boolean('Visible en la web', default=True)
    period_ids = fields.One2many('spa.plan.period', 'plan_id', string='Duraciones y precios', copy=True)
    line_ids = fields.One2many('spa.plan.line', 'plan_id', string='Servicios incluidos', copy=True)
    guest_quota = fields.Integer('Invitados gratis por mes (free pass)', default=0, tracking=True)
    guest_fee_product_id = fields.Many2one('product.product', string='Tarifa de invitado',
                                           domain=[('type', '=', 'service')],
                                           help='Se cobra cuando se agota el cupo de free pass.')
    cancel_policy_id = fields.Many2one('spa.cancel.policy', string='Política de cancelación', required=True,
                                       check_company=True, tracking=True)
    grace_days = fields.Integer('Días de gracia', default=5, tracking=True,
                                help='Días después del vencimiento en que el socio conserva el acceso.')
    freeze_max_days = fields.Integer('Días de congelamiento por año', default=0, tracking=True,
                                     help='Máximo de días por año calendario que el socio puede congelar su '
                                          'membresía (viaje, salud). El vencimiento se corre esos días. '
                                          '0 = el plan no permite congelar.')
    pricelist_id = fields.Many2one('product.pricelist', string='Lista de precios del socio',
                                   help='Descuentos del plan en restaurante, cafetería y tienda. '
                                        'Se asigna al socio mientras la membresía esté vigente.')
    membership_ids = fields.One2many('spa.membership', 'plan_id', string='Membresías')
    member_count = fields.Integer('Socios vigentes', compute='_compute_member_count')
    min_price = fields.Monetary('Desde', compute='_compute_min_price')

    @api.depends('membership_ids.state')
    def _compute_member_count(self):
        data = dict(self.env['spa.membership']._read_group(
            [('plan_id', 'in', self.ids), ('state', 'in', ('active', 'grace'))], ['plan_id'], ['__count']))
        for plan in self:
            plan.member_count = data.get(plan, 0)

    @api.depends('period_ids.price', 'period_ids.months')
    def _compute_min_price(self):
        for plan in self:
            monthly = [p.price / p.months for p in plan.period_ids if p.months and p.active]
            plan.min_price = min(monthly) if monthly else 0.0

    def _line_for_service(self, service):
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.service_id == service)[:1]

    def action_view_members(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Socios del plan %s', self.name),
            'res_model': 'spa.membership',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
        }


class SpaPlanPeriod(models.Model):
    _name = 'spa.plan.period'
    _description = 'Duración y precio de un plan'
    _order = 'months'

    plan_id = fields.Many2one('spa.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True, string='Compañía')
    currency_id = fields.Many2one(related='plan_id.currency_id')
    months = fields.Integer('Meses', required=True, default=1)
    name = fields.Char('Duración', compute='_compute_name', store=True)
    price = fields.Monetary('Precio', required=True)
    monthly_price = fields.Monetary('Equivale por mes', compute='_compute_monthly_price')
    product_id = fields.Many2one('product.product', string='Producto de venta', readonly=True, copy=False,
                                 help='Se crea automáticamente; lleva impuestos y cuenta de ingreso.')
    active = fields.Boolean(default=True, string='Activo')

    _months_positive = models.Constraint('CHECK (months > 0)', 'La duración debe ser de al menos un mes.')
    _plan_months_uniq = models.Constraint('UNIQUE (plan_id, months)', 'El plan ya tiene esa duración.')

    @api.depends('months')
    def _compute_name(self):
        for period in self:
            period.name = PERIOD_NAMES.get(period.months) or self.env._('%s meses', period.months)

    @api.depends('price', 'months')
    def _compute_monthly_price(self):
        for period in self:
            period.monthly_price = period.price / period.months if period.months else 0.0

    def _product_category(self):
        self.ensure_one()
        xmlid = 'l10n_bo_spa.categ_membership_monthly' if self.months == 1 else 'l10n_bo_spa.categ_membership_prepaid'
        return self.env.ref(xmlid, raise_if_not_found=False) or self.env.ref('product.product_category_all')

    def _sync_product(self):
        for period in self:
            vals = {
                'name': f'{period.plan_id.name} – {period.name}',
                'list_price': period.price,
                'type': 'service',
                'categ_id': period._product_category().id,
                'sale_ok': True,
                'purchase_ok': False,
            }
            if period.product_id:
                period.product_id.sudo().write(vals)
            else:
                period.product_id = self.env['product.product'].sudo().create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        periods = super().create(vals_list)
        periods._sync_product()
        return periods

    def write(self, vals):
        res = super().write(vals)
        if {'price', 'months', 'plan_id'} & set(vals):
            self._sync_product()
        return res


class SpaPlanLine(models.Model):
    _name = 'spa.plan.line'
    _description = 'Servicio incluido en un plan'
    _order = 'sequence, id'

    plan_id = fields.Many2one('spa.plan', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    service_id = fields.Many2one('spa.service', string='Servicio', required=True)
    unlimited = fields.Boolean('Ilimitado')
    quantity = fields.Integer('Sesiones por mes', default=1)
    freq_limit_qty = fields.Integer('Tope de uso', default=0, help='0 = sin tope.')
    freq_limit_period = fields.Selection([('day', 'por día'), ('week', 'por semana')], string='Período del tope',
                                         default='week')
    hour_from = fields.Float('Desde (hora)', default=0.0)
    hour_to = fields.Float('Hasta (hora)', default=24.0)
    carryover = fields.Selection([
        ('lose', 'Se pierde al cerrar el mes'),
        ('accumulate', 'Se acumula'),
        ('carry_limited', 'Se traslada con tope'),
    ], string='Saldo no usado', default='lose', required=True)
    carryover_max = fields.Integer('Tope de traslado', default=0)
    guests_per_booking = fields.Integer('Invitados por reserva', default=0,
                                        help='0 = este servicio no admite invitados en este plan.')

    _plan_service_uniq = models.Constraint('UNIQUE (plan_id, service_id)',
                                           'El servicio ya está incluido en el plan.')

    @api.constrains('unlimited', 'quantity', 'hour_from', 'hour_to', 'freq_limit_qty')
    def _check_line(self):
        for line in self:
            if not line.unlimited and line.quantity <= 0:
                raise ValidationError(self.env._('Indique sesiones por mes para %s, o márquelo ilimitado.',
                                                 line.service_id.name))
            if not (0 <= line.hour_from < line.hour_to <= 24):
                raise ValidationError(self.env._('Horario permitido inválido para %s.', line.service_id.name))
            if line.freq_limit_qty < 0:
                raise ValidationError(self.env._('El tope de uso no puede ser negativo.'))

    def _summary(self):
        self.ensure_one()
        parts = [self.env._('ilimitado') if self.unlimited else self.env._('%s al mes', self.quantity)]
        if self.freq_limit_qty:
            parts.append(self.env._('máx. %(qty)s %(period)s', qty=self.freq_limit_qty,
                                    period=dict(self._fields['freq_limit_period'].selection)[self.freq_limit_period]))
        if self.hour_from > 0 or self.hour_to < 24:
            parts.append('%02d:%02d–%02d:%02d' % (int(self.hour_from), round(self.hour_from % 1 * 60),
                                                 int(self.hour_to), round(self.hour_to % 1 * 60)))
        return ', '.join(parts)
