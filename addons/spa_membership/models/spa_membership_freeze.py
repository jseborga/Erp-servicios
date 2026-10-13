# Part of ERP Servicios Spa. License LGPL-3.
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

MANAGER_GROUP = 'spa_base.group_spa_manager'


def days_by_year(date_from, date_to):
    """{año: días} de un intervalo de fechas (ambos extremos incluidos)."""
    result = defaultdict(int)
    day = date_from
    while day <= date_to:
        year_end = day.replace(month=12, day=31)
        chunk_end = min(year_end, date_to)
        result[day.year] += (chunk_end - day).days + 1
        day = chunk_end + timedelta(days=1)
    return result


class SpaMembershipFreeze(models.Model):
    """Congelamiento (viaje, salud): el socio no usa el spa y el vencimiento se corre esos días."""
    _name = 'spa.membership.freeze'
    _description = 'Congelamiento de membresía'
    _order = 'date_from desc, id desc'

    membership_id = fields.Many2one('spa.membership', string='Membresía', required=True, ondelete='cascade',
                                    index=True)
    partner_id = fields.Many2one(related='membership_id.partner_id', store=True, string='Socio')
    company_id = fields.Many2one(related='membership_id.company_id', store=True, string='Compañía')
    date_from = fields.Date('Desde', required=True)
    date_to = fields.Date('Hasta', required=True)
    days = fields.Integer('Días', compute='_compute_days', store=True)
    reason = fields.Char('Motivo', required=True)
    state = fields.Selection([('active', 'Vigente'), ('cancelled', 'Anulado')], string='Estado',
                             default='active', required=True)
    date_end_before = fields.Date('Vencía', readonly=True, help='Vencimiento de la membresía antes del congelamiento.')
    user_id = fields.Many2one('res.users', string='Registrado por', default=lambda self: self.env.user, readonly=True)

    @api.depends('date_from', 'date_to')
    def _compute_days(self):
        for freeze in self:
            freeze.days = (freeze.date_to - freeze.date_from).days + 1 \
                if freeze.date_from and freeze.date_to and freeze.date_to >= freeze.date_from else 0

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for freeze in self:
            if freeze.date_to < freeze.date_from:
                raise ValidationError(self.env._('La fecha final del congelamiento no puede ser anterior a la inicial.'))

    def _compute_display_name(self):
        for freeze in self:
            freeze.display_name = '%s – %s' % (freeze.date_from and freeze.date_from.strftime('%d/%m/%Y'),
                                               freeze.date_to and freeze.date_to.strftime('%d/%m/%Y'))

    def action_cancel(self):
        """Anula un congelamiento que aún no empezó: el vencimiento vuelve a la fecha anterior."""
        if not self.env.su and not self.env.user.has_group(MANAGER_GROUP):
            raise UserError(self.env._('Solo el gerente puede anular un congelamiento.'))
        today = self.env['spa.tools'].local_today()
        for freeze in self.filtered(lambda f: f.state == 'active'):
            if freeze.date_from <= today:
                raise UserError(self.env._(
                    'El congelamiento del %s ya empezó: no se puede anular. Registre un ajuste si corresponde.',
                    freeze.date_from.strftime('%d/%m/%Y')))
            membership = freeze.membership_id
            membership.write({'date_end': membership.date_end - timedelta(days=freeze.days)})
            freeze.state = 'cancelled'
            membership.message_post(body=self.env._(
                'Congelamiento anulado (%(from)s – %(to)s). Vence el %(end)s.',
                **{'from': freeze.date_from.strftime('%d/%m/%Y'), 'to': freeze.date_to.strftime('%d/%m/%Y'),
                   'end': membership.date_end.strftime('%d/%m/%Y')}))
        return True


class SpaMembership(models.Model):
    _inherit = 'spa.membership'

    freeze_ids = fields.One2many('spa.membership.freeze', 'membership_id', string='Congelamientos')
    freeze_max_days = fields.Integer(related='plan_id.freeze_max_days', string='Días de congelamiento por año')
    frozen_until = fields.Date('Congelada hasta', compute='_compute_frozen',
                               help='Si hoy está congelada: último día del congelamiento.')

    def _compute_frozen(self):
        today = self.env['spa.tools'].local_today()
        for membership in self:
            membership.frozen_until = membership._spa_frozen_on(today).date_to

    def _spa_frozen_on(self, day):
        """Congelamiento vigente que cubre ``day`` (fecha local) o vacío."""
        self.ensure_one()
        return self.sudo().freeze_ids.filtered(
            lambda f: f.state == 'active' and f.date_from <= day <= f.date_to)[:1]

    def _spa_frozen_days(self, year, exclude=None):
        """Días congelados de la membresía en un año calendario."""
        self.ensure_one()
        total = 0
        for freeze in self.sudo().freeze_ids.filtered(lambda f: f.state == 'active' and f != exclude):
            total += days_by_year(freeze.date_from, freeze.date_to).get(year, 0)
        return total

    def _spa_freeze_check(self, date_from, date_to):
        """Gancho: otros módulos bloquean el congelamiento (spa_booking: reservas en esas fechas)."""
        return True

    def _spa_freeze(self, date_from, date_to, reason):
        """Congela la membresía entre dos fechas locales y corre el vencimiento esos días.

        Reglas: solo membresías activas; el plan debe permitirlo (``freeze_max_days`` > 0) y no
        se supera ese máximo por año calendario; no empieza en el pasado; termina antes del
        vencimiento; no se superpone con otro congelamiento; sin reservas en esas fechas.
        Devuelve el ``spa.membership.freeze`` creado.
        """
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group(MANAGER_GROUP):
            raise UserError(self.env._('Solo el gerente puede congelar una membresía.'))
        today = self.env['spa.tools'].local_today()
        fmt = '%d/%m/%Y'
        if not (date_from and date_to and reason):
            raise UserError(self.env._('Indique las fechas y el motivo del congelamiento.'))
        if date_to < date_from:
            raise UserError(self.env._('La fecha final del congelamiento no puede ser anterior a la inicial.'))
        if self.state != 'active':
            raise UserError(self.env._('Solo se congela una membresía activa (%(name)s está «%(state)s»).',
                                       name=self.name, state=dict(self._fields['state'].selection)[self.state]))
        max_days = self.plan_id.freeze_max_days
        if max_days <= 0:
            raise UserError(self.env._('El plan %s no permite congelar la membresía.', self.plan_id.name))
        if date_from < today:
            raise UserError(self.env._('El congelamiento no puede empezar en el pasado (hoy es %s).',
                                       today.strftime(fmt)))
        if date_to > self.date_end:
            raise UserError(self.env._(
                'El congelamiento debe terminar a más tardar el día del vencimiento (%s). '
                'Renueve primero la membresía o elija otras fechas.', self.date_end.strftime(fmt)))
        overlap = self.sudo().freeze_ids.filtered(
            lambda f: f.state == 'active' and f.date_from <= date_to and f.date_to >= date_from)
        if overlap:
            raise UserError(self.env._('Ya hay un congelamiento del %(from)s al %(to)s.',
                                       **{'from': overlap[0].date_from.strftime(fmt),
                                          'to': overlap[0].date_to.strftime(fmt)}))
        for year, days in days_by_year(date_from, date_to).items():
            used = self._spa_frozen_days(year)
            if used + days > max_days:
                raise UserError(self.env._(
                    'El plan %(plan)s permite congelar hasta %(max)s días por año: en %(year)s ya usó %(used)s '
                    'y pide %(days)s. Quedan %(left)s días.',
                    plan=self.plan_id.name, max=max_days, year=year, used=used, days=days,
                    left=max(max_days - used, 0)))
        self._spa_freeze_check(date_from, date_to)
        days = (date_to - date_from).days + 1
        freeze = self.env['spa.membership.freeze'].sudo().create({
            'membership_id': self.id,
            'date_from': date_from,
            'date_to': date_to,
            'reason': reason,
            'date_end_before': self.date_end,
            'user_id': self.env.user.id,
        })
        self.write({'date_end': self.date_end + timedelta(days=days)})
        self.message_post(body=self.env._(
            'Membresía congelada del %(from)s al %(to)s (%(days)s días): %(reason)s. Nuevo vencimiento: %(end)s.',
            **{'from': date_from.strftime(fmt), 'to': date_to.strftime(fmt), 'days': days, 'reason': reason,
               'end': self.date_end.strftime(fmt)}))
        return freeze

    def action_open_freeze_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Congelar membresía'),
            'res_model': 'spa.membership.freeze.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_membership_id': self.id},
        }
