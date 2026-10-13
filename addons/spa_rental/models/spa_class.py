# Part of ERP Servicios Spa. License LGPL-3.
"""Clases recurrentes: horarios (plantillas), sesiones e inscripciones.

* El horario (``spa.class.template``) define servicio, instructor, días, hora, cupo y precio.
* Un proceso diario crea las sesiones de las próximas N semanas (idempotente: una sesión por
  horario y hora de inicio). Si una fecha no se puede dictar (evento exclusivo, espacio cerrado,
  instructor ocupado) la sesión se crea **cancelada con el motivo**, para que se vea y no se
  vuelva a intentar cada día.
* Cada sesión programada reserva su cupo completo en el espacio (``spa.space._seats_taken``) y
  ocupa al instructor (``spa.service._free_employee``).
* Inscripción con membresía (descuenta el saldo del plan con ``_spa_check_access`` /
  ``_spa_consume``) o con factura en borrador (por sesión o paquete) que se valida al cobrar o al
  terminar la clase.
"""
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

WEEKDAY_FIELDS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
SCHEDULE_FIELDS = set(WEEKDAY_FIELDS) | {'start_hour', 'duration', 'date_from', 'date_to', 'service_id', 'active'}
ACTIVE_ENROLLMENT_STATES = ('enrolled', 'attended', 'absent')
BLOCKING_BOOKING_STATES = ('confirmed', 'checked_in')


class SpaClassTemplate(models.Model):
    _name = 'spa.class.template'
    _description = 'Horario de clase recurrente'
    _inherit = ['mail.thread']
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char('Clase', required=True, tracking=True, help='Ej. «Natación niños L-M-V 18:00».')
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    service_id = fields.Many2one('spa.service', string='Servicio', required=True, check_company=True, tracking=True,
                                 domain=[('spa_is_class', '=', True)])
    space_id = fields.Many2one(related='service_id.space_id', store=True, string='Espacio')
    space_capacity = fields.Integer(related='space_id.capacity', string='Aforo del espacio')
    requires_instructor = fields.Boolean(related='service_id.requires_staff')
    instructor_id = fields.Many2one('hr.employee', string='Instructor', check_company=True, tracking=True)
    mon = fields.Boolean('Lun')
    tue = fields.Boolean('Mar')
    wed = fields.Boolean('Mié')
    thu = fields.Boolean('Jue')
    fri = fields.Boolean('Vie')
    sat = fields.Boolean('Sáb')
    sun = fields.Boolean('Dom')
    start_hour = fields.Float('Hora de inicio', required=True, default=18.0, tracking=True)
    duration = fields.Float('Duración (horas)', required=True, default=1.0, tracking=True)
    capacity = fields.Integer('Cupo', required=True, default=8, tracking=True,
                              help='Alumnos por sesión. Se reservan en el espacio mientras dura la clase.')
    date_from = fields.Date('Desde', required=True, default=lambda self: self.env['spa.tools'].local_today())
    date_to = fields.Date('Hasta', help='Vacío = horario permanente.')
    session_product_id = fields.Many2one('product.product', string='Producto por sesión', check_company=True,
                                         compute='_compute_session_product_id', store=True, readonly=False,
                                         precompute=True, domain=[('type', '=', 'service')],
                                         help='Precio de una sesión suelta (factura). Ingreso: categoría del producto.')
    session_price = fields.Float(related='session_product_id.lst_price', string='Precio por sesión')
    package_product_id = fields.Many2one('product.product', string='Producto del paquete', check_company=True,
                                         domain=[('type', '=', 'service')],
                                         help='Opcional: precio del paquete o curso completo.')
    package_price = fields.Float(related='package_product_id.lst_price', string='Precio del paquete')
    package_sessions = fields.Integer('Sesiones del paquete', default=0,
                                      help='Cuántas sesiones incluye el paquete. 0 = todas las sesiones restantes '
                                           'hasta la fecha final del horario (curso completo).')
    description = fields.Text('Descripción para el alumno')
    session_ids = fields.One2many('spa.class.session', 'template_id', string='Sesiones')
    session_count = fields.Integer('Nº de sesiones', compute='_compute_session_count')

    @api.depends('service_id')
    def _compute_session_product_id(self):
        for template in self:
            template.session_product_id = template.session_product_id or template.service_id.product_id

    def _compute_session_count(self):
        data = dict(self.env['spa.class.session']._read_group(
            [('template_id', 'in', self.ids), ('state', '=', 'planned')], ['template_id'], ['__count']))
        for template in self:
            template.session_count = data.get(template, 0)

    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.duration = self.service_id.duration
            if not self.name:
                self.name = self.service_id.name

    @api.constrains('capacity', 'service_id', 'start_hour', 'duration', 'date_from', 'date_to', 'instructor_id',
                    *WEEKDAY_FIELDS)
    def _check_template(self):
        for template in self:
            if template.capacity <= 0:
                raise ValidationError(self.env._('El cupo de %s debe ser mayor que cero.', template.name))
            if template.capacity > template.space_id.capacity:
                raise ValidationError(self.env._(
                    'El cupo de %(name)s (%(cap)s) supera el aforo de %(space)s (%(space_cap)s).', name=template.name,
                    cap=template.capacity, space=template.space_id.name, space_cap=template.space_id.capacity))
            if not any(template[day] for day in WEEKDAY_FIELDS):
                raise ValidationError(self.env._('Elija al menos un día de la semana para %s.', template.name))
            if template.duration <= 0 or not (0 <= template.start_hour < 24) or \
                    template.start_hour + template.duration > 24:
                raise ValidationError(self.env._('Horario inválido en %s.', template.name))
            if template.date_to and template.date_to < template.date_from:
                raise ValidationError(self.env._('La fecha final de %s es anterior a la inicial.', template.name))
            if template.service_id.requires_staff and not template.instructor_id:
                raise ValidationError(self.env._('Indique el instructor de %s.', template.name))
            skill = template.service_id.skill_id
            if template.instructor_id and skill and skill not in template.instructor_id.sudo().spa_skill_ids:
                raise ValidationError(self.env._('%(emp)s no tiene la especialidad «%(skill)s».',
                                                 emp=template.instructor_id.name, skill=skill.name))

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates._generate_sessions()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if SCHEDULE_FIELDS & set(vals):
            self._spa_reschedule()
        elif {'capacity', 'instructor_id'} & set(vals):
            update = {key: vals[key] for key in ('capacity', 'instructor_id') if key in vals}
            for session in self._spa_future_sessions():
                if session.enrollment_ids.filtered(lambda e: e.state in ACTIVE_ENROLLMENT_STATES):
                    if session.state == 'planned':
                        session.write(update)  # valida cupo e instructor; si no se puede, avisa
                elif session.state == 'planned' or not session.enrollment_ids:
                    session._spa_apply_template()
        return res

    # ------------------------------------------------------------------
    # Generación de sesiones
    # ------------------------------------------------------------------
    @api.model
    def _spa_weeks_ahead(self):
        try:
            weeks = int(self.env['ir.config_parameter'].sudo().get_param('spa_rental.class_weeks_ahead', 5))
        except (TypeError, ValueError):
            weeks = 5
        return min(max(weeks, 1), 52)

    def _spa_future_sessions(self):
        now = fields.Datetime.now()
        return self.env['spa.class.session'].sudo().search([('template_id', 'in', self.ids), ('start', '>', now)])

    def _spa_desired_starts(self, last_day=None):
        """Inicios (UTC) que el horario debe tener desde ahora hasta el horizonte o ``last_day``."""
        self.ensure_one()
        tools = self.env['spa.tools']
        now = fields.Datetime.now()
        today = tools.local_today()
        last = max(today + timedelta(weeks=self._spa_weeks_ahead()), last_day or today)
        if self.date_to:
            last = min(last, self.date_to)
        day = max(today, self.date_from)
        starts = set()
        while day <= last:
            if self[WEEKDAY_FIELDS[day.weekday()]]:
                start = tools.local_combine(day, self.start_hour)
                if start > now:
                    starts.add(start)
            day += timedelta(days=1)
        return starts

    def _spa_reschedule(self):
        """Tras cambiar días, horas o vigencia: ajusta las sesiones futuras.

        * Con alumnos inscritos: se mantienen y se avisa en el horario (el gerente decide).
        * Sin alumnos y en un horario que sigue vigente: se actualizan (duración, cupo, instructor).
        * Sin alumnos y fuera del nuevo horario: se borran (o se cancelan si tienen historial).
        """
        tools = self.env['spa.tools']
        for template in self:
            future = template._spa_future_sessions()
            last_day = max((tools.to_local(s.start).date() for s in future), default=None)
            desired = template._spa_desired_starts(last_day) if template.active else set()
            with_students = self.env['spa.class.session']
            for session in future:
                if session.enrollment_ids.filtered(lambda e: e.state in ACTIVE_ENROLLMENT_STATES):
                    with_students |= session
                elif session.start in desired:
                    if session.state == 'planned' or not session.enrollment_ids:
                        session._spa_apply_template()
                elif session.enrollment_ids:
                    session.enrollment_ids.filtered(lambda e: e.state == 'draft').write({'state': 'cancelled'})
                    session.with_context(spa_session_checked=True).write({
                        'state': 'cancelled', 'cancel_reason': self.env._('Horario modificado')})
                else:
                    session.with_context(spa_session_unlink=True).unlink()
            if with_students:
                template.message_post(body=self.env._(
                    'Se cambió el horario. Estas sesiones tienen alumnos inscritos y se mantienen; cancélelas o '
                    'muévalas si corresponde: %s', ', '.join(with_students.mapped('display_name'))))
        self.filtered('active')._generate_sessions()

    def _generate_sessions(self, until=None):
        """Crea las sesiones hasta ``until`` (fecha local) o las próximas N semanas. Idempotente."""
        tools = self.env['spa.tools']
        Session = self.env['spa.class.session'].sudo()
        now = fields.Datetime.now()
        today = tools.local_today()
        horizon = today + timedelta(weeks=self._spa_weeks_ahead())
        created = Session.browse()
        for template in self.filtered('active'):
            last = max(until or horizon, horizon) if until else horizon
            if template.date_to:
                last = min(last, template.date_to)
            day = max(today, template.date_from)
            if day > last:
                continue
            existing = set(Session.search([
                ('template_id', '=', template.id), ('start', '>=', tools.local_combine(day, 0.0))]).mapped('start'))
            template.space_id._lock_for_booking()
            skipped = []
            while day <= last:
                if template[WEEKDAY_FIELDS[day.weekday()]]:
                    start = tools.local_combine(day, template.start_hour)
                    if start > now and start not in existing:
                        stop = start + timedelta(hours=template.duration)
                        vals = template._spa_session_vals(start, stop)
                        errors = Session._spa_slot_errors(template.space_id, start, stop, template.capacity,
                                                          template.instructor_id, template.service_id)
                        if errors:
                            vals.update(state='cancelled', cancel_reason=errors[0])
                            skipped.append('%s: %s' % (tools.to_local(start).strftime('%d/%m %H:%M'), errors[0]))
                        created |= Session.with_context(spa_session_checked=True).create(vals)
                        existing.add(start)
                day += timedelta(days=1)
            if skipped:
                template.message_post(body=self.env._('Sesiones que no se pueden dictar (quedan canceladas):\n%s',
                                                      '\n'.join(skipped)))
        return created

    def _spa_session_vals(self, start, stop):
        self.ensure_one()
        return {
            'template_id': self.id,
            'company_id': self.company_id.id,
            'service_id': self.service_id.id,
            'instructor_id': self.instructor_id.id,
            'start': start,
            'stop': stop,
            'capacity': self.capacity,
        }

    def _spa_upcoming_sessions(self, count=None):
        """Próximas sesiones programadas (genera más si hacen falta para un paquete)."""
        self.ensure_one()
        Session = self.env['spa.class.session']
        domain = [('template_id', '=', self.id), ('state', '=', 'planned'), ('start', '>', fields.Datetime.now())]
        sessions = Session.search(domain, order='start')
        if count and len(sessions) < count and (not self.date_to or self.date_to > self.env['spa.tools'].local_today()):
            # Paquete más largo que el horizonte: crea las sesiones que faltan.
            weekly = max(sum(1 for day in WEEKDAY_FIELDS if self[day]), 1)
            weeks = (count // weekly) + 2
            self._generate_sessions(until=self.env['spa.tools'].local_today() + timedelta(weeks=weeks))
            sessions = Session.search(domain, order='start')
        if count:
            return sessions[:count]
        return sessions

    def _spa_count_remaining(self):
        """Sesiones que faltan hasta la fecha final (sin crearlas)."""
        self.ensure_one()
        if not self.date_to:
            return 0
        tools = self.env['spa.tools']
        now = fields.Datetime.now()
        day = max(tools.local_today(), self.date_from)
        count = 0
        while day <= self.date_to:
            if self[WEEKDAY_FIELDS[day.weekday()]] and tools.local_combine(day, self.start_hour) > now:
                count += 1
            day += timedelta(days=1)
        return count

    def action_generate_sessions(self):
        created = self._generate_sessions()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._('Sesiones'),
                'message': self.env._('%s sesión(es) nueva(s).', len(created)),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Sesiones de %s', self.name),
            'res_model': 'spa.class.session',
            'view_mode': 'list,calendar,form',
            'domain': [('template_id', '=', self.id)],
            'context': {'default_template_id': self.id, 'search_default_upcoming': 1},
        }

    def action_open_package_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Inscribir al paquete'),
            'res_model': 'spa.class.package.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_template_id': self.id},
        }

    @api.model
    def _cron_generate_sessions(self):
        self.search([('active', '=', True)])._generate_sessions()
        return True


class SpaClassSession(models.Model):
    _name = 'spa.class.session'
    _description = 'Sesión de clase'
    _inherit = ['mail.thread']
    _order = 'start, id'
    _check_company_auto = True

    name = fields.Char('Sesión', compute='_compute_name', store=True)
    template_id = fields.Many2one('spa.class.template', string='Horario', index=True, ondelete='restrict',
                                  check_company=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    service_id = fields.Many2one('spa.service', string='Servicio', required=True, check_company=True,
                                 domain=[('spa_is_class', '=', True)])
    space_id = fields.Many2one(related='service_id.space_id', store=True, string='Espacio', index=True)
    instructor_id = fields.Many2one('hr.employee', string='Instructor', check_company=True, tracking=True, index=True)
    start = fields.Datetime('Inicio', required=True, index=True, tracking=True)
    stop = fields.Datetime('Fin', required=True, index=True, tracking=True)
    capacity = fields.Integer('Cupo', required=True, default=8, tracking=True)
    enrollment_ids = fields.One2many('spa.class.enrollment', 'session_id', string='Alumnos')
    enrolled_count = fields.Integer('Inscritos', compute='_compute_counts', store=True)
    attended_count = fields.Integer('Asistieron', compute='_compute_counts', store=True)
    seats_left = fields.Integer('Cupos libres', compute='_compute_counts', store=True)
    state = fields.Selection([
        ('planned', 'Programada'),
        ('done', 'Realizada'),
        ('cancelled', 'Cancelada'),
    ], default='planned', required=True, tracking=True, index=True)
    cancel_reason = fields.Char('Motivo de cancelación', tracking=True)
    color = fields.Integer(related='template_id.color')
    note = fields.Text('Notas')

    _template_start_uniq = models.UniqueIndex('(template_id, start) WHERE template_id IS NOT NULL',
                                              'Ya existe una sesión de ese horario a esa hora.')

    @api.depends('template_id.name', 'service_id.name', 'start')
    def _compute_name(self):
        tools = self.env['spa.tools']
        for session in self:
            local = tools.to_local(session.start)
            session.name = '%s · %s' % (session.template_id.name or session.service_id.name or '',
                                        local.strftime('%d/%m/%Y %H:%M') if local else '')

    @api.depends('enrollment_ids.state', 'capacity')
    def _compute_counts(self):
        for session in self:
            active = session.enrollment_ids.filtered(lambda e: e.state in ACTIVE_ENROLLMENT_STATES)
            session.enrolled_count = len(active)
            session.attended_count = len(active.filtered(lambda e: e.state == 'attended'))
            session.seats_left = max(session.capacity - len(active), 0)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        template = self.template_id
        if template:
            self.service_id = template.service_id
            self.instructor_id = template.instructor_id
            self.capacity = template.capacity

    @api.onchange('start', 'service_id')
    def _onchange_start(self):
        if self.start and self.service_id:
            duration = self.template_id.duration or self.service_id.duration
            self.stop = self.start + timedelta(hours=duration)

    @api.constrains('start', 'stop', 'capacity')
    def _check_session(self):
        for session in self:
            if session.stop <= session.start:
                raise ValidationError(self.env._('La clase debe terminar después de empezar.'))
            if session.capacity <= 0:
                raise ValidationError(self.env._('El cupo de la clase debe ser mayor que cero.'))
            if session.state == 'planned' and session.capacity < session.enrolled_count:
                raise ValidationError(self.env._('%(name)s ya tiene %(n)s inscritos: el cupo no puede ser menor.',
                                                 name=session.name, n=session.enrolled_count))

    # ------------------------------------------------------------------
    # Disponibilidad del espacio y del instructor
    # ------------------------------------------------------------------
    @api.model
    def _spa_instructor_errors(self, instructor, service, start, stop, exclude_session=None):
        _ = self.env._
        if not instructor:
            return [_('Indique el instructor de %s.', service.name)] if service.requires_staff else []
        # sudo: especialidades y turno son datos privados del empleado (recepción y gerente no son RR. HH.).
        instructor = instructor.sudo()
        errors = []
        if service.skill_id and service.skill_id not in instructor.spa_skill_ids:
            errors.append(_('%(emp)s no tiene la especialidad «%(skill)s».', emp=instructor.name,
                            skill=service.skill_id.name))
        if not instructor._spa_is_working(start, stop):
            errors.append(_('%s no tiene turno en ese horario.', instructor.name))
        bookings = self.env['spa.booking'].sudo().search([
            ('employee_id', '=', instructor.id), ('state', 'in', BLOCKING_BOOKING_STATES),
            ('start', '<', stop), ('stop', '>', start)], limit=1)
        if bookings:
            errors.append(_('%(emp)s tiene una reserva a esa hora (%(booking)s).', emp=instructor.name,
                            booking=bookings.display_name))
        others = self.sudo().search([
            ('instructor_id', '=', instructor.id), ('state', '=', 'planned'), ('start', '<', stop),
            ('stop', '>', start), ('id', '!=', exclude_session.id if exclude_session else 0)], limit=1)
        if others:
            errors.append(_('%(emp)s ya dicta %(session)s a esa hora.', emp=instructor.name,
                            session=others.display_name))
        return errors

    @api.model
    def _spa_slot_errors(self, space, start, stop, capacity, instructor, service, exclude_session=None):
        """Motivos por los que la clase no se puede dictar (lista vacía = se puede)."""
        _ = self.env._
        tools = self.env['spa.tools']
        errors = []
        if space.state != 'active':
            errors.append(_('%s no está operativo.', space.name))
        local_day = tools.to_local(start).date()
        closure = space.closure_ids.filtered(lambda c: c.date_from <= local_day <= c.date_to)[:1]
        if closure:
            errors.append(_('%(space)s cerrado: %(reason)s.', space=space.name, reason=closure.reason))
        elif not space._within_hours(start, stop):
            errors.append(_('Fuera del horario de atención de %s.', space.name))
        rentals = space._spa_rentals(start, stop)
        exclusive = rentals.filtered(lambda r: r.mode == 'exclusive')
        if exclusive:
            errors.append(_('Reservado para evento: %s.', exclusive[0].event_name))
        elif capacity > space.capacity:
            errors.append(_('El cupo (%(cap)s) supera el aforo de %(space)s (%(space_cap)s).', cap=capacity,
                            space=space.name, space_cap=space.capacity))
        else:
            excluded = [exclude_session.id] if exclude_session else []
            taken = space.with_context(spa_exclude_session_ids=excluded)._seats_taken(start, stop)
            if taken + capacity > space.capacity:
                errors.append(_('Quedan %(free)s de %(cap)s cupos en %(space)s (reservas, eventos y otras clases); '
                                'la clase necesita %(need)s.', free=max(space.capacity - taken, 0),
                                cap=space.capacity, space=space.name, need=capacity))
        errors += self._spa_instructor_errors(instructor, service, start, stop, exclude_session=exclude_session)
        return errors

    def _spa_check_slot(self):
        for session in self.filtered(lambda s: s.state == 'planned'):
            session.space_id._lock_for_booking()
            errors = self._spa_slot_errors(session.space_id, session.start, session.stop, session.capacity,
                                           session.instructor_id, session.service_id, exclude_session=session)
            if errors:
                raise UserError(self.env._('No se puede programar %(name)s:\n%(errors)s', name=session.name,
                                           errors='\n'.join('• ' + error for error in errors)))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            template = self.env['spa.class.template'].browse(vals.get('template_id'))
            if template:
                vals.setdefault('service_id', template.service_id.id)
                vals.setdefault('company_id', template.company_id.id)
                vals.setdefault('capacity', template.capacity)
                vals.setdefault('instructor_id', template.instructor_id.id)
                if vals.get('start') and not vals.get('stop'):
                    vals['stop'] = fields.Datetime.to_datetime(vals['start']) + timedelta(hours=template.duration)
            elif vals.get('start') and not vals.get('stop') and vals.get('service_id'):
                service = self.env['spa.service'].browse(vals['service_id'])
                vals['stop'] = fields.Datetime.to_datetime(vals['start']) + timedelta(hours=service.duration)
        sessions = super().create(vals_list)
        if not self.env.context.get('spa_session_checked'):
            sessions._spa_check_slot()
        return sessions

    def write(self, vals):
        res = super().write(vals)
        if {'start', 'stop', 'capacity', 'instructor_id', 'service_id'} & set(vals) and \
                not self.env.context.get('spa_session_checked'):
            self._spa_check_slot()
        return res

    def unlink(self):
        if not self.env.context.get('spa_session_unlink'):
            if self.enrollment_ids.filtered(lambda e: e.state != 'cancelled' and e.state != 'draft'):
                raise UserError(self.env._('La sesión tiene alumnos inscritos: cancélela en lugar de borrarla.'))
        return super().unlink()

    def _spa_session_product(self):
        """Producto de la sesión suelta: el del horario o, si no tiene, el del servicio."""
        return self[:1].template_id.session_product_id or self[:1].service_id.product_id

    def _spa_apply_template(self):
        """Sesión sin alumnos: toma la duración, el cupo y el instructor actuales de su horario.

        Si con los nuevos datos no se puede dictar, queda cancelada con el motivo; si antes estaba
        cancelada por un conflicto que ya no existe, vuelve a programarse.
        """
        for session in self:
            template = session.template_id
            stop = session.start + timedelta(hours=template.duration)
            session.space_id._lock_for_booking()
            errors = self._spa_slot_errors(template.space_id, session.start, stop, template.capacity,
                                           template.instructor_id, template.service_id, exclude_session=session)
            session.with_context(spa_session_checked=True).write({
                'stop': stop,
                'capacity': template.capacity,
                'instructor_id': template.instructor_id.id,
                'service_id': template.service_id.id,
                'state': 'cancelled' if errors else 'planned',
                'cancel_reason': errors[0] if errors else False,
            })

    # ------------------------------------------------------------------
    # Flujo
    # ------------------------------------------------------------------
    def _spa_lock(self):
        """Bloquea las filas de las sesiones para serializar inscripciones concurrentes."""
        if self.ids:
            self.env.cr.execute('SELECT id FROM spa_class_session WHERE id IN %s FOR UPDATE', [tuple(self.ids)])

    def _spa_taken(self, exclude=None):
        """Inscritos activos según la base de datos (después del bloqueo)."""
        self.ensure_one()
        self.env['spa.class.enrollment'].flush_model(['session_id', 'state'])
        self.env.cr.execute("""
            SELECT COUNT(*) FROM spa_class_enrollment
             WHERE session_id = %s AND state IN %s AND id != %s
        """, [self.id, ACTIVE_ENROLLMENT_STATES, exclude.id if exclude else 0])
        return self.env.cr.fetchone()[0]

    def action_cancel_session(self, reason=None):
        """Cancela la sesión: avisa a los inscritos y devuelve la sesión (saldo o nota de crédito)."""
        reason = reason or self.env._('Cancelada por el spa')
        for session in self:
            if session.state != 'planned':
                raise UserError(self.env._('Solo se cancelan sesiones programadas (%s).', session.name))
            session.enrollment_ids.filtered(lambda e: e.state == 'draft').write({'state': 'cancelled'})
            enrollments = session.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
            enrollments._spa_cancel_by_session(reason)
            session.write({'state': 'cancelled', 'cancel_reason': reason})
            session.message_post(body=self.env._('Sesión cancelada (%(reason)s). Avisados: %(n)s alumno(s).',
                                                 reason=reason, n=len(enrollments)))
        return True

    def action_open_cancel_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cancelar sesión'),
            'res_model': 'spa.class.session.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_ids': self.ids},
        }

    def action_replan(self):
        """Vuelve a programar una sesión cancelada (p. ej. al resolverse el conflicto)."""
        for session in self:
            if session.state != 'cancelled':
                raise UserError(self.env._('Solo se reprograman sesiones canceladas.'))
            if session.start <= fields.Datetime.now():
                raise UserError(self.env._('La sesión %s ya pasó.', session.name))
            session.with_context(spa_session_checked=True).write({'state': 'planned', 'cancel_reason': False})
            session._spa_check_slot()
        return True

    def action_done(self):
        """Clase dictada: ausentes y validación de las facturas cuyo servicio quedó prestado."""
        for session in self:
            if session.state != 'planned':
                raise UserError(self.env._('Solo se cierran sesiones programadas.'))
            session.state = 'done'
            session.enrollment_ids.filtered(lambda e: e.state == 'enrolled').write({'state': 'absent'})
            session.enrollment_ids.filtered(lambda e: e.state == 'draft').write({'state': 'cancelled'})
        self.enrollment_ids._spa_post_completed_invoices()
        return True

    def action_new_enrollment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Inscribir en %s', self.name),
            'res_model': 'spa.class.enrollment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    @api.model
    def _cron_sessions(self):
        now = fields.Datetime.now()
        self.search([('state', '=', 'planned'), ('stop', '<=', now)]).action_done()
        return True


class SpaClassEnrollment(models.Model):
    _name = 'spa.class.enrollment'
    _description = 'Inscripción a clase'
    _inherit = ['mail.thread']
    _order = 'start desc, id desc'
    _check_company_auto = True

    session_id = fields.Many2one('spa.class.session', string='Sesión', required=True, index=True,
                                 ondelete='restrict', check_company=True,
                                 domain="[('state', '=', 'planned')]")
    template_id = fields.Many2one(related='session_id.template_id', store=True, string='Horario')
    service_id = fields.Many2one(related='session_id.service_id', store=True, string='Servicio')
    space_id = fields.Many2one(related='session_id.space_id', store=True, string='Espacio')
    instructor_id = fields.Many2one(related='session_id.instructor_id', string='Instructor')
    start = fields.Datetime(related='session_id.start', store=True, string='Inicio', index=True)
    stop = fields.Datetime(related='session_id.stop', store=True, string='Fin')
    company_id = fields.Many2one(related='session_id.company_id', store=True)
    currency_id = fields.Many2one(related='session_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Alumno', required=True, index=True, tracking=True)
    phone = fields.Char(related='partner_id.phone')
    membership_id = fields.Many2one('spa.membership', string='Membresía', check_company=True, tracking=True,
                                    domain="[('partner_id', '=', partner_id), ('state', 'in', ('active', 'grace'))]")
    payment_mode = fields.Selection([
        ('membership', 'Con su membresía'),
        ('invoice', 'Pago por clase / paquete'),
    ], string='Forma de pago', required=True, default='invoice', tracking=True)
    package = fields.Boolean('Paquete', readonly=True, help='Inscripción como parte de un paquete o curso completo.')
    price = fields.Monetary('Precio', compute='_compute_price', store=True, readonly=False, precompute=True,
                            help='Importe (IVA incluido) de esta sesión. En un paquete, su parte del precio.')
    invoice_id = fields.Many2one('account.move', string='Factura', readonly=True, copy=False)
    refund_move_id = fields.Many2one('account.move', string='Nota de crédito', readonly=True, copy=False)
    invoice_status = fields.Selection([
        ('none', 'Sin factura'),
        ('draft', 'Por cobrar (borrador)'),
        ('posted', 'Validada, por cobrar'),
        ('partial', 'Pago parcial'),
        ('paid', 'Pagada'),
        ('cancel', 'Anulada'),
    ], string='Cobro', compute='_compute_invoice_status', compute_sudo=True)
    consumption_ids = fields.One2many('spa.consumption', 'class_enrollment_id', string='Consumos')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('enrolled', 'Inscrito'),
        ('attended', 'Asistió'),
        ('absent', 'No asistió'),
        ('cancelled', 'Cancelada'),
    ], default='draft', required=True, tracking=True, index=True, copy=False)
    attended_at = fields.Datetime('Ingreso', readonly=True, copy=False)
    cancel_reason = fields.Char('Motivo de cancelación', copy=False)
    channel = fields.Selection([
        ('reception', 'Recepción'),
        ('phone', 'Teléfono'),
        ('whatsapp', 'WhatsApp'),
        ('portal', 'Web del socio'),
    ], string='Canal', default='reception', required=True)
    note = fields.Text('Notas')

    can_edit_price = fields.Boolean('Puede cambiar el precio', compute='_compute_can_edit_price')

    _partner_session_uniq = models.UniqueIndex(
        "(session_id, partner_id) WHERE state IN ('enrolled', 'attended', 'absent')",
        'La persona ya está inscrita en esa sesión.')

    @api.depends('session_id', 'payment_mode')
    def _compute_price(self):
        for enrollment in self:
            if enrollment.package:
                enrollment.price = enrollment.price
            elif enrollment.payment_mode == 'membership':
                enrollment.price = 0.0
            else:
                enrollment.price = enrollment.session_id._spa_session_product().lst_price

    @api.depends('invoice_id.state', 'invoice_id.payment_state')
    def _compute_invoice_status(self):
        for enrollment in self:
            invoice = enrollment.invoice_id
            if not invoice:
                status = 'none'
            elif invoice.state in ('draft', 'cancel'):
                status = invoice.state
            elif invoice.payment_state in ('paid', 'in_payment', 'reversed'):
                status = 'paid'
            elif invoice.payment_state == 'partial':
                status = 'partial'
            else:
                status = 'posted'
            enrollment.invoice_status = status

    def _compute_can_edit_price(self):
        allowed = self.env.su or self.env.user.has_group('spa_base.group_spa_manager')
        for enrollment in self:
            enrollment.can_edit_price = allowed

    def _compute_display_name(self):
        for enrollment in self:
            enrollment.display_name = '%s · %s' % (enrollment.partner_id.name or '', enrollment.session_id.name or '')

    def _spa_check_price_rights(self):
        """Solo el gerente cambia el precio de una clase suelta (los paquetes los reparte el asistente)."""
        if self.env.su or self.env.user.has_group('spa_base.group_spa_manager'):
            return
        for enrollment in self.filtered(lambda e: e.payment_mode == 'invoice' and not e.package):
            expected = enrollment.session_id._spa_session_product().lst_price
            if enrollment.currency_id.compare_amounts(enrollment.price, expected):
                raise UserError(self.env._('Solo el gerente cambia el precio de la clase (%s).',
                                           enrollment.session_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        enrollments = super().create(vals_list)
        enrollments._spa_check_price_rights()
        return enrollments

    def write(self, vals):
        res = super().write(vals)
        if {'price', 'payment_mode', 'session_id'} & set(vals):
            self._spa_check_price_rights()
        return res

    @api.onchange('partner_id', 'session_id')
    def _onchange_partner_membership(self):
        membership = self.partner_id.spa_membership_id
        if membership.state in ('active', 'grace') and self.session_id and \
                membership.plan_id._line_for_service(self.session_id.service_id):
            self.membership_id = membership
            self.payment_mode = 'membership'
        elif self.partner_id:
            self.membership_id = False
            self.payment_mode = 'invoice'

    # ------------------------------------------------------------------
    # Inscripción
    # ------------------------------------------------------------------
    def action_enroll(self):
        for enrollment in self.sorted('start'):
            enrollment._spa_enroll_one()
            if enrollment.payment_mode == 'invoice' and enrollment.price > 0 and not enrollment.invoice_id:
                enrollment._spa_create_invoice()
        return True

    def _spa_enroll_one(self):
        self.ensure_one()
        _ = self.env._
        if self.state != 'draft':
            raise UserError(_('La inscripción de %s ya fue procesada.', self.partner_id.name))
        session = self.session_id
        if session.state != 'planned':
            raise UserError(_('La sesión %s no está programada.', session.name))
        if session.stop <= fields.Datetime.now():
            raise UserError(_('La clase %s ya terminó.', session.name))
        # Serializa inscripciones concurrentes a la misma sesión.
        session._spa_lock()
        taken = session._spa_taken(exclude=self)
        if taken + 1 > session.capacity:
            raise UserError(_('La clase %(name)s está llena (%(n)s de %(cap)s).', name=session.name, n=taken,
                              cap=session.capacity))
        if self.sudo().search_count([('session_id', '=', session.id), ('partner_id', '=', self.partner_id.id),
                                     ('state', 'in', ACTIVE_ENROLLMENT_STATES), ('id', '!=', self.id)]):
            raise UserError(_('%(name)s ya está inscrito en %(session)s.', name=self.partner_id.name,
                              session=session.name))
        if self.payment_mode == 'membership':
            membership = self.membership_id
            if not membership:
                raise UserError(_('Seleccione la membresía o cambie a pago por clase.'))
            if membership.partner_id != self.partner_id:
                raise UserError(_('La membresía no pertenece a %s.', self.partner_id.name))
            membership._spa_check_access(session.service_id, session.start, session.stop)
            membership._spa_consume(session.service_id, session.start, 'booking',
                                    note=_('Clase %s', session.name), extra_vals={'class_enrollment_id': self.id})
        self.state = 'enrolled'

    def _spa_invoice_line(self, product, price, name):
        self.ensure_one()
        company = self.company_id
        return self.env['account.move']._spa_rental_line_vals(
            product, price=price, name=name, analytic=company._spa_rental_analytic(), company=company)

    def _spa_create_invoice(self):
        """Factura en BORRADOR de una sesión suelta (se valida al cobrar o al terminar la clase)."""
        self.ensure_one()
        session = self.session_id
        product = session._spa_session_product()
        name = self.env._('%(service)s – %(session)s (%(student)s)', service=session.service_id.name,
                          session=session.name, student=self.partner_id.name)
        invoice = self._spa_new_invoice([Command.create(self._spa_invoice_line(product, self.price, name))])
        self.invoice_id = invoice
        return invoice

    def _spa_new_invoice(self, lines):
        company = self[:1].company_id
        return self.env['account.move'].sudo().with_company(company).create({
            'move_type': 'out_invoice',
            'partner_id': self[:1].partner_id.id,
            'company_id': company.id,
            'invoice_origin': ', '.join(self.session_id.mapped('name'))[:200],
            'spa_invoice_kind': 'class',
            'invoice_line_ids': lines,
        })

    def _spa_post_completed_invoices(self):
        """Valida las facturas en borrador cuyas sesiones ya se dictaron o cancelaron (servicio prestado)."""
        invoices = self.sudo().invoice_id.filtered(lambda m: m.state == 'draft')
        for invoice in invoices:
            enrollments = self.sudo().search([('invoice_id', '=', invoice.id)])
            if all(e.session_id.state in ('done', 'cancelled') or e.state == 'cancelled' for e in enrollments) \
                    and enrollments.filtered(lambda e: e.state in ('attended', 'absent')):
                invoice._spa_post_on_taxable_event()

    # ------------------------------------------------------------------
    # Asistencia
    # ------------------------------------------------------------------
    @api.model
    def _spa_checkin_minutes(self):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param('spa_rental.class_checkin_minutes', 30))
        except (TypeError, ValueError):
            return 30

    @api.model
    def _spa_find_for_check_in(self, partner, space, now=None):
        now = now or fields.Datetime.now()
        return self.sudo().search([
            ('partner_id', '=', partner.id), ('space_id', '=', space.id), ('state', '=', 'enrolled'),
            ('session_id.state', '=', 'planned'),
            ('start', '<=', now + timedelta(minutes=self._spa_checkin_minutes())), ('stop', '>', now),
        ], order='start', limit=1)

    def action_attend(self):
        now = fields.Datetime.now()
        for enrollment in self:
            if enrollment.state != 'enrolled':
                raise UserError(self.env._('Solo se marca la asistencia de alumnos inscritos.'))
            if now < enrollment.start - timedelta(minutes=self._spa_checkin_minutes()):
                raise UserError(self.env._('La clase %s aún no empieza.', enrollment.session_id.name))
            if enrollment.payment_mode == 'membership' and enrollment.membership_id.state not in ('active', 'grace'):
                raise UserError(self.env._('La membresía %(name)s no da acceso (estado: %(state)s).',
                                           name=enrollment.membership_id.name,
                                           state=dict(enrollment.membership_id._fields['state'].selection)[
                                               enrollment.membership_id.state]))
            enrollment.write({'state': 'attended', 'attended_at': now})
        return True

    def action_absent(self):
        self.filtered(lambda e: e.state == 'enrolled').write({'state': 'absent'})
        return True

    def _spa_check_in(self, method='manual'):
        """Ingreso del alumno con su QR: marca asistencia y registra el ingreso.

        El ingreso se registra con 0 personas para el aforo general porque la clase ya reservó sus
        cupos en el espacio (no se cuenta dos veces).
        """
        self.ensure_one()
        Log = self.env['spa.access.log']
        if Log.search_count([('partner_id', '=', self.partner_id.id), ('space_id', '=', self.space_id.id),
                             ('state', '=', 'open')]):
            raise UserError(self.env._('%(name)s ya está dentro de %(space)s.', name=self.partner_id.name,
                                       space=self.space_id.name))
        self.action_attend()
        return Log.create({
            'partner_id': self.partner_id.id,
            'membership_id': self.membership_id.id,
            'space_id': self.space_id.id,
            'people': 0,
            'method': method,
            'courtesy_ref': self.session_id.name,
            'class_session_id': self.session_id.id,
            'class_enrollment_id': self.id,
        })

    # ------------------------------------------------------------------
    # Cancelación y devoluciones
    # ------------------------------------------------------------------
    @api.model
    def _spa_cancel_hours(self):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param('spa_rental.class_cancel_hours', 2))
        except (TypeError, ValueError):
            return 2.0

    def action_cancel(self):
        """Cancelación pedida por el alumno: devuelve la sesión si es con anticipación."""
        now = fields.Datetime.now()
        for enrollment in self:
            if enrollment.state not in ('draft', 'enrolled'):
                raise UserError(self.env._('La inscripción de %s ya no se puede cancelar.', enrollment.partner_id.name))
            if enrollment.state == 'draft':
                enrollment.state = 'cancelled'
                continue
            in_time = now <= enrollment.start - timedelta(hours=self._spa_cancel_hours())
            if in_time:
                enrollment._spa_refund(self.env._('Cancelación con anticipación'))
                enrollment.write({'state': 'cancelled', 'cancel_reason': self.env._('Cancelada por el alumno')})
            else:
                enrollment.write({'state': 'cancelled', 'cancel_reason': self.env._(
                    'Cancelación tardía: la sesión se considera usada')})
                enrollment.message_post(body=self.env._('Cancelación tardía (menos de %s h): no se devuelve la sesión.',
                                                        self._spa_cancel_hours()))
        return True

    def _spa_refund(self, note):
        """Devuelve la sesión: saldo del plan, línea de la factura en borrador o nota de crédito."""
        self.ensure_one()
        if self.payment_mode == 'membership':
            net = sum(self.consumption_ids.mapped('qty'))
            if net > 0 and self.membership_id:
                self.membership_id._spa_consume(self.service_id, self.start, 'refund', qty=-net, note=note,
                                                extra_vals={'class_enrollment_id': self.id})
            return 'membership'
        invoice = self.invoice_id.sudo()
        if not invoice or invoice.state == 'cancel' or not self.price:
            return 'free'
        if invoice.state == 'draft':
            others = self.sudo().search([('invoice_id', '=', invoice.id), ('id', '!=', self.id),
                                         ('state', 'in', ACTIVE_ENROLLMENT_STATES)])
            if not others:
                invoice.button_cancel()
            else:
                line = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')[:1]
                new_total = line.price_unit * line.quantity - self.price
                line.write({'price_unit': new_total / (line.quantity or 1.0),
                            'name': '%s (%s)' % (line.name, self.env._('menos %s', self.session_id.name))})
            return 'draft'
        credit = invoice._spa_credit_note(self.price, self.env._('Devolución: %s', self.session_id.name))
        self.refund_move_id = credit
        self.message_post(body=self.env._('Nota de crédito %s en borrador para la devolución (caja la valida).',
                                          credit.display_name))
        return 'credit'

    def _spa_cancel_by_session(self, reason):
        tools = self.env['spa.tools']
        for enrollment in self:
            refund = enrollment._spa_refund(self.env._('Sesión cancelada por el spa: %s', reason))
            enrollment.write({'state': 'cancelled', 'cancel_reason': reason})
            local = tools.to_local(enrollment.start)
            refund_text = {
                'membership': self.env._('Te devolvimos la sesión a tu plan.'),
                'draft': self.env._('No se te cobrará esta clase.'),
                'credit': self.env._('Te devolveremos el importe de la clase o quedará como saldo a favor.'),
                'free': '',
            }[refund]
            self.env['spa.message'].queue('class_cancelled', enrollment.partner_id, {
                'clase': enrollment.template_id.name or enrollment.service_id.name,
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': local.strftime('%H:%M'),
                'motivo': reason,
                'devolucion': refund_text,
            }, record=enrollment)

    def action_open_payment(self):
        self.ensure_one()
        if not self.invoice_id or self.invoice_id.sudo().state == 'cancel':
            raise UserError(self.env._('La inscripción no tiene una factura por cobrar.'))
        return self.env['spa.rental.payment.wizard']._spa_open(invoice=self.invoice_id, enrollment=self)
