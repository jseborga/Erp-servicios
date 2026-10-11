# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaPaymentOffer(models.Model):
    _name = 'spa.payment.offer'
    _description = 'Oferta de pago (descuento o cuotas)'
    _order = 'date_to desc, id desc'
    _check_company_auto = True

    name = fields.Char('Oferta', required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date('Vigente desde', required=True, default=fields.Date.context_today)
    date_to = fields.Date('Vigente hasta', required=True)
    plan_ids = fields.Many2many('spa.plan', string='Planes', help='Vacío = todos los planes.')
    months = fields.Integer('Solo para duración (meses)', default=0, help='0 = cualquier duración.')
    offer_type = fields.Selection([
        ('discount', 'Descuento'),
        ('installments', 'Pago en cuotas'),
    ], string='Tipo', required=True, default='discount')
    discount_percent = fields.Float('Descuento (%)')
    installments = fields.Integer('Número de cuotas', default=1)
    new_members_only = fields.Boolean('Solo socios nuevos')
    payment_term_id = fields.Many2one('account.payment.term', string='Plazos de pago', readonly=True, copy=False)
    description = fields.Text('Condiciones', translate=True)

    @api.constrains('date_from', 'date_to', 'discount_percent', 'installments', 'offer_type')
    def _check_offer(self):
        for offer in self:
            if offer.date_to < offer.date_from:
                raise ValidationError(self.env._('La vigencia de la oferta termina antes de empezar.'))
            if offer.offer_type == 'discount' and not (0 < offer.discount_percent < 100):
                raise ValidationError(self.env._('El descuento debe estar entre 0 y 100 %.'))
            if offer.offer_type == 'installments' and offer.installments < 2:
                raise ValidationError(self.env._('Una oferta en cuotas necesita al menos 2 cuotas.'))

    def _is_applicable(self, period, partner, day):
        self.ensure_one()
        if not (self.active and self.date_from <= day <= self.date_to):
            return False
        if self.plan_ids and period.plan_id not in self.plan_ids:
            return False
        if self.months and period.months != self.months:
            return False
        if self.new_members_only and partner.spa_membership_ids.filtered(lambda m: m.date_start):
            return False
        return True

    @api.model
    def _applicable_offers(self, period, partner, day=None):
        day = day or self.env['spa.tools'].local_today()
        offers = self.search([('company_id', '=', period.company_id.id)])
        return offers.filtered(lambda o: o._is_applicable(period, partner, day))

    def _get_payment_term(self):
        """Plazos de pago en cuotas mensuales iguales (se crean una vez por oferta)."""
        self.ensure_one()
        if self.offer_type != 'installments':
            return self.env['account.payment.term']
        if not self.payment_term_id:
            share = round(100.0 / self.installments, 2)
            lines = []
            for index in range(self.installments):
                value = share if index < self.installments - 1 else round(100.0 - share * (self.installments - 1), 2)
                lines.append((0, 0, {'value': 'percent', 'value_amount': value, 'nb_days': 30 * index}))
            self.payment_term_id = self.env['account.payment.term'].sudo().create({
                'name': self.env._('%s cuotas mensuales', self.installments),
                'company_id': self.company_id.id,
                'line_ids': lines,
            })
        return self.payment_term_id
