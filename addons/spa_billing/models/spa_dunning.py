# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SpaDunningStep(models.Model):
    """Paso de la escalera de cobranza: aviso o suspensión N días antes/después del vencimiento.

    Complementa la mora del núcleo (spa_membership): los días de gracia del plan siguen suspendiendo
    automáticamente; la escalera agrega los avisos y, si se configura, una suspensión antes o después.
    """
    _name = 'spa.dunning.step'
    _description = 'Paso de la escalera de cobranza'
    _order = 'offset_days, sequence, id'
    _check_company_auto = True

    name = fields.Char('Paso', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, string='Activo')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    offset_days = fields.Integer('Día respecto al vencimiento', required=True, default=0,
                                 help='Negativo: días antes del vencimiento de la membresía. 0: el día del vencimiento. '
                                      'Positivo: días después (renovación aún impaga).')
    action = fields.Selection([
        ('notify', 'Enviar aviso'),
        ('suspend', 'Suspender el acceso'),
    ], string='Acción', required=True, default='notify')
    template_id = fields.Many2one('spa.message.template', string='Mensaje (WhatsApp)',
                                  help='Plantilla del aviso. En una suspensión es opcional (aviso de suspensión).')
    template_code = fields.Char(related='template_id.code', string='Código de plantilla')
    note = fields.Text('Notas')

    @api.constrains('action', 'offset_days', 'template_id')
    def _check_step(self):
        for step in self:
            if step.action == 'suspend' and step.offset_days <= 0:
                raise ValidationError(self.env._(
                    'La suspensión debe ser después del vencimiento (día 1 o más): antes el período está pagado.'))
            if step.action == 'notify' and not step.template_id:
                raise ValidationError(self.env._('Elija la plantilla del mensaje del aviso «%s».', step.name))

    def _compute_display_name(self):
        for step in self:
            sign = '+' if step.offset_days > 0 else ''
            step.display_name = f'{step.name} (día {sign}{step.offset_days})'


class SpaDunningLog(models.Model):
    """Bitácora de cobranza: qué se aplicó a cada membresía y período (para no repetirlo)."""
    _name = 'spa.dunning.log'
    _description = 'Bitácora de cobranza'
    _order = 'date desc, id desc'

    membership_id = fields.Many2one('spa.membership', string='Membresía', required=True, ondelete='cascade',
                                    index=True)
    partner_id = fields.Many2one(related='membership_id.partner_id', store=True, string='Socio')
    company_id = fields.Many2one(related='membership_id.company_id', store=True, string='Compañía')
    date = fields.Date('Fecha', required=True, index=True)
    period_end = fields.Date('Vencimiento del período', help='Vencimiento de la membresía cuando se aplicó.')
    kind = fields.Selection([
        ('step', 'Escalera de cobranza'),
        ('transition', 'Cambio de estado'),
        ('installment', 'Cuota vencida'),
    ], string='Origen', required=True, default='step')
    step_id = fields.Many2one('spa.dunning.step', string='Paso', ondelete='set null', index=True)
    move_line_id = fields.Many2one('account.move.line', string='Cuota', ondelete='set null', index=True)
    action = fields.Selection([
        ('notify', 'Aviso'),
        ('suspend', 'Suspensión'),
        ('reactivate', 'Reactivación'),
    ], string='Acción', required=True)
    result = fields.Selection([('done', 'Aplicado'), ('skipped', 'Omitido')], string='Resultado', required=True,
                              default='done')
    message_id = fields.Many2one('spa.message', string='Mensaje', ondelete='set null')
    note = fields.Char('Detalle')

    _step_period_uniq = models.UniqueIndex('(membership_id, step_id, period_end) WHERE step_id IS NOT NULL',
                                           'Ese paso de cobranza ya se aplicó en este período.')
    _installment_uniq = models.UniqueIndex('(move_line_id, action) WHERE move_line_id IS NOT NULL',
                                           'Esa acción ya se aplicó a la cuota.')
