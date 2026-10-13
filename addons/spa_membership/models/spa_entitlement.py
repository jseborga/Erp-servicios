# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError

CONSUMPTION_REASONS = [
    ('booking', 'Reserva'),
    ('checkin', 'Ingreso (check-in)'),
    ('late_cancel', 'Cancelación tardía'),
    ('no_show', 'No se presentó'),
    ('refund', 'Devolución'),
    ('manual_adjust', 'Ajuste manual'),
]


class SpaEntitlement(models.Model):
    _name = 'spa.entitlement'
    _description = 'Saldo de un servicio por mes'
    _order = 'period_start desc, id'

    membership_id = fields.Many2one('spa.membership', required=True, ondelete='cascade', index=True, string='Membresía')
    partner_id = fields.Many2one(related='membership_id.partner_id', store=True)
    company_id = fields.Many2one(related='membership_id.company_id', store=True, string='Compañía')
    plan_line_id = fields.Many2one('spa.plan.line', required=True, ondelete='restrict', string='Línea del plan')
    service_id = fields.Many2one(related='plan_line_id.service_id', store=True)
    period_start = fields.Date('Mes desde', required=True)
    period_end = fields.Date('Mes hasta', required=True)
    unlimited = fields.Boolean('Ilimitado')
    granted = fields.Integer('Del plan')
    carried_in = fields.Integer('Traslado del mes anterior')
    carry_pending = fields.Boolean('Traslado pendiente')
    consumption_ids = fields.One2many('spa.consumption', 'entitlement_id', string='Consumos')
    used = fields.Integer('Usados', compute='_compute_used', store=True)
    remaining = fields.Integer('Disponibles', compute='_compute_used', store=True)

    _uniq = models.Constraint('UNIQUE (membership_id, plan_line_id, period_start)',
                              'Ya existe el saldo de ese servicio para ese mes.')

    @api.depends('consumption_ids.qty', 'granted', 'carried_in', 'unlimited')
    def _compute_used(self):
        for entitlement in self:
            entitlement.used = sum(entitlement.consumption_ids.mapped('qty'))
            entitlement.remaining = 0 if entitlement.unlimited else \
                entitlement.granted + entitlement.carried_in - entitlement.used

    def _compute_display_name(self):
        for entitlement in self:
            entitlement.display_name = f'{entitlement.service_id.name} {entitlement.period_start:%m/%Y}'


class SpaConsumption(models.Model):
    """Libro de consumos. Inmutable: las correcciones son movimientos nuevos."""
    _name = 'spa.consumption'
    _description = 'Consumo de un servicio del plan'
    _order = 'service_date desc, id desc'

    membership_id = fields.Many2one('spa.membership', required=True, ondelete='cascade', index=True, string='Membresía')
    partner_id = fields.Many2one(related='membership_id.partner_id', store=True)
    plan_id = fields.Many2one(related='membership_id.plan_id', store=True)
    company_id = fields.Many2one(related='membership_id.company_id', store=True, string='Compañía')
    entitlement_id = fields.Many2one('spa.entitlement', ondelete='restrict', index=True, string='Saldo del mes')
    service_id = fields.Many2one('spa.service', required=True, string='Servicio')
    service_date = fields.Datetime('Fecha del servicio', required=True, default=fields.Datetime.now)
    qty = fields.Integer('Cantidad', required=True, default=1, help='Negativo = devolución de sesión.')
    reason = fields.Selection(CONSUMPTION_REASONS, string='Motivo', required=True)
    note = fields.Char('Nota')
    user_id = fields.Many2one('res.users', string='Registrado por', default=lambda self: self.env.user, readonly=True)

    def _booking_ref(self):
        """Reserva asociada (la agrega spa_booking)."""
        return False

    def write(self, vals):
        protected = {'membership_id', 'entitlement_id', 'service_id', 'qty', 'service_date', 'reason'}
        if protected & set(vals) and not self.env.context.get('spa_consumption_internal'):
            raise UserError(self.env._('El libro de consumos no se modifica: registre un ajuste.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('spa_consumption_internal'):
            raise UserError(self.env._('El libro de consumos no se borra: registre un ajuste.'))
        return super().unlink()
