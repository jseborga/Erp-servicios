# Part of ERP Servicios Spa. License LGPL-3.
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

WEEKDAY_FIELDS = ['open_mon', 'open_tue', 'open_wed', 'open_thu', 'open_fri', 'open_sat', 'open_sun']


class SpaSpace(models.Model):
    _name = 'spa.space'
    _description = 'Espacio del spa'
    _inherit = ['mail.thread']
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char('Espacio', required=True, translate=True, tracking=True)
    code = fields.Char('Código', size=10)
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    capacity = fields.Integer('Aforo', required=True, default=1, tracking=True,
                              help='Personas que pueden estar a la vez en el espacio.')
    access_mode = fields.Selection([
        ('slot', 'Por franja horaria (con reserva)'),
        ('free', 'Libre con control de aforo (check-in)'),
    ], string='Modo de acceso', required=True, default='slot', tracking=True)
    slot_duration = fields.Float('Duración de franja (horas)', default=1.0,
                                 help='Solo para modo por franja.')
    max_stay = fields.Float('Permanencia máxima (horas)', default=2.0,
                            help='Modo libre: tras este tiempo se registra la salida automática.')
    open_hour = fields.Float('Abre', required=True, default=8.0)
    close_hour = fields.Float('Cierra', required=True, default=21.0)
    open_mon = fields.Boolean('Lun', default=True)
    open_tue = fields.Boolean('Mar', default=True)
    open_wed = fields.Boolean('Mié', default=True)
    open_thu = fields.Boolean('Jue', default=True)
    open_fri = fields.Boolean('Vie', default=True)
    open_sat = fields.Boolean('Sáb', default=True)
    open_sun = fields.Boolean('Dom', default=True)
    state = fields.Selection([
        ('active', 'Operativo'),
        ('maintenance', 'En mantenimiento'),
        ('closed', 'Cerrado'),
    ], default='active', required=True, tracking=True, string='Estado')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Área (analítica)',
                                          help='Centro de costo para medir la rentabilidad del espacio.')
    closure_ids = fields.One2many('spa.space.closure', 'space_id', string='Cierres programados')
    service_ids = fields.One2many('spa.service', 'space_id', string='Servicios')
    note = fields.Html('Notas')
    active = fields.Boolean(default=True, string='Activo')

    _capacity_positive = models.Constraint('CHECK (capacity > 0)', 'El aforo debe ser mayor que cero.')

    @api.constrains('open_hour', 'close_hour', 'slot_duration')
    def _check_hours(self):
        for space in self:
            if not (0 <= space.open_hour < space.close_hour <= 24):
                raise ValidationError(self.env._('Horario inválido en %s: la apertura debe ser antes del cierre.', space.name))
            if space.access_mode == 'slot' and space.slot_duration <= 0:
                raise ValidationError(self.env._('La duración de franja de %s debe ser mayor que cero.', space.name))

    def _is_open_on(self, day):
        self.ensure_one()
        if self.state != 'active' or not self[WEEKDAY_FIELDS[day.weekday()]]:
            return False
        return not self.closure_ids.filtered(lambda c: c.date_from <= day <= c.date_to)

    def _slot_starts(self, day, duration):
        """Inicios locales (datetime naïve) de franjas para un día y una duración."""
        self.ensure_one()
        if not self._is_open_on(day):
            return []
        step = self.slot_duration if self.access_mode == 'slot' else duration
        step = step or duration or 1.0
        starts = []
        hour = self.open_hour
        while hour + duration <= self.close_hour + 1e-6:
            h = int(hour)
            m = int(round((hour - h) * 60))
            starts.append(datetime.combine(day, datetime.min.time()) + timedelta(hours=h, minutes=m))
            hour += step
        return starts

    def _within_hours(self, start_utc, stop_utc):
        """True si el intervalo cae dentro del horario y de un día abierto."""
        self.ensure_one()
        tools = self.env['spa.tools']
        start = tools.to_local(start_utc)
        stop = tools.to_local(stop_utc)
        if start.date() != stop.date() and not (stop.hour == 0 and stop.minute == 0):
            return False
        if not self._is_open_on(start.date()):
            return False
        start_h = start.hour + start.minute / 60.0
        stop_h = (stop.hour + stop.minute / 60.0) or 24.0
        return self.open_hour - 1e-6 <= start_h and stop_h <= self.close_hour + 1e-6


class SpaSpaceClosure(models.Model):
    _name = 'spa.space.closure'
    _description = 'Cierre programado de un espacio'
    _order = 'date_from desc'

    space_id = fields.Many2one('spa.space', required=True, ondelete='cascade', index=True, string='Espacio')
    date_from = fields.Date('Desde', required=True)
    date_to = fields.Date('Hasta', required=True)
    reason = fields.Char('Motivo', required=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for closure in self:
            if closure.date_to < closure.date_from:
                raise ValidationError(self.env._('La fecha final del cierre no puede ser anterior a la inicial.'))
