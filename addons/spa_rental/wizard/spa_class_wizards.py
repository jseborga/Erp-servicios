# Part of ERP Servicios Spa. License LGPL-3.
from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class SpaClassSessionCancelWizard(models.TransientModel):
    _name = 'spa.class.session.cancel.wizard'
    _description = 'Cancelar sesión de clase'

    session_ids = fields.Many2many('spa.class.session', string='Sesiones', required=True)
    reason = fields.Char('Motivo', required=True, help='Se envía a los alumnos por WhatsApp.')

    def action_confirm(self):
        self.ensure_one()
        self.session_ids.action_cancel_session(self.reason.strip())
        return True


class SpaClassPackageWizard(models.TransientModel):
    """Inscribe a una persona en las próximas N sesiones de un horario (paquete o curso completo)."""
    _name = 'spa.class.package.wizard'
    _description = 'Inscribir en paquete de clases'

    template_id = fields.Many2one('spa.class.template', string='Horario', required=True)
    partner_id = fields.Many2one('res.partner', string='Alumno', required=True)
    membership_id = fields.Many2one('spa.membership', string='Membresía',
                                    domain="[('partner_id', '=', partner_id), ('state', 'in', ('active', 'grace'))]")
    payment_mode = fields.Selection([
        ('membership', 'Con su membresía (descuenta una sesión del plan por clase)'),
        ('invoice', 'Pago del paquete'),
    ], string='Forma de pago', required=True, default='invoice')
    sessions = fields.Integer('Sesiones', compute='_compute_sessions', store=True, readonly=False,
                              help='Número de sesiones desde la próxima. En un curso con fecha final, todas las restantes.')
    currency_id = fields.Many2one(related='template_id.currency_id')
    price = fields.Monetary('Precio total', compute='_compute_price', store=True, readonly=False,
                            help='IVA incluido. Precio del paquete o precio por sesión × sesiones.')
    channel = fields.Selection([('reception', 'Recepción'), ('phone', 'Teléfono'), ('whatsapp', 'WhatsApp')],
                               default='reception', required=True, string='Canal')

    @api.depends('template_id')
    def _compute_sessions(self):
        for wizard in self:
            template = wizard.template_id
            if not template:
                wizard.sessions = 0
            elif template.package_sessions:
                wizard.sessions = template.package_sessions
            elif template.date_to:
                wizard.sessions = template._spa_count_remaining()
            else:
                wizard.sessions = len(template._spa_upcoming_sessions())

    can_edit_price = fields.Boolean(compute='_compute_can_edit_price', string='Puede cambiar el precio')

    def _compute_can_edit_price(self):
        allowed = self.env.user.has_group('spa_base.group_spa_manager')
        for wizard in self:
            wizard.can_edit_price = allowed

    def _spa_list_price(self):
        """Precio de lista: el del paquete si corresponde, si no el precio por sesión × sesiones."""
        self.ensure_one()
        template = self.template_id
        if self.payment_mode == 'membership' or not template:
            return 0.0
        if template.package_product_id and (self.sessions == template.package_sessions or not template.package_sessions):
            return template.package_price
        return template.session_price * self.sessions

    @api.depends('template_id', 'sessions', 'payment_mode')
    def _compute_price(self):
        for wizard in self:
            wizard.price = wizard._spa_list_price()

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        membership = self.partner_id.spa_membership_id
        if membership.state in ('active', 'grace') and \
                membership.plan_id._line_for_service(self.template_id.service_id):
            self.membership_id = membership
            self.payment_mode = 'membership'
        else:
            self.membership_id = False
            self.payment_mode = 'invoice'

    def action_confirm(self):
        self.ensure_one()
        template = self.template_id
        if self.sessions <= 0:
            raise UserError(self.env._('Indique cuántas sesiones incluye la inscripción.'))
        if not template.package_sessions and template.date_to:
            # Curso completo: todas las sesiones programadas que quedan hasta la fecha final.
            template._generate_sessions(until=template.date_to)
            sessions = template._spa_upcoming_sessions()
        else:
            sessions = template._spa_upcoming_sessions(count=self.sessions)
        if not sessions or (template.package_sessions and len(sessions) < self.sessions):
            raise UserError(self.env._('Solo hay %(n)s sesiones programadas de %(name)s.', n=len(sessions),
                                       name=template.name))
        if self.payment_mode == 'membership' and not self.membership_id:
            raise UserError(self.env._('Seleccione la membresía o cambie a pago del paquete.'))
        if not self.env.user.has_group('spa_base.group_spa_manager') and \
                template.currency_id.compare_amounts(self.price, self._spa_list_price()):
            raise UserError(self.env._('Solo el gerente cambia el precio del paquete.'))
        currency = template.currency_id
        share = currency.round(self.price / len(sessions)) if self.payment_mode == 'invoice' else 0.0
        vals_list = []
        for index, session in enumerate(sessions):
            price = share
            if self.payment_mode == 'invoice' and index == len(sessions) - 1:
                price = currency.round(self.price - share * (len(sessions) - 1))
            vals_list.append({
                'session_id': session.id,
                'partner_id': self.partner_id.id,
                'membership_id': self.membership_id.id if self.payment_mode == 'membership' else False,
                'payment_mode': self.payment_mode,
                'package': True,
                'price': price,
                'channel': self.channel,
            })
        enrollments = self.env['spa.class.enrollment'].create(vals_list)
        for enrollment in enrollments.sorted('start'):
            enrollment._spa_enroll_one()
        if self.payment_mode == 'invoice' and self.price > 0:
            product = template.package_product_id or template.session_product_id
            name = self.env._('%(name)s – paquete de %(n)s sesiones del %(first)s al %(last)s (%(student)s)',
                              name=template.name, n=len(sessions),
                              first=self.env['spa.tools'].to_local(sessions[0].start).strftime('%d/%m/%Y'),
                              last=self.env['spa.tools'].to_local(sessions[-1].start).strftime('%d/%m/%Y'),
                              student=self.partner_id.name)
            line = enrollments[:1]._spa_invoice_line(product, self.price, name)
            enrollments.invoice_id = enrollments._spa_new_invoice([Command.create(line)])
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Inscripciones'),
            'res_model': 'spa.class.enrollment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', enrollments.ids)],
        }
