# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models
from odoo.tools import SQL

BOOKED_STATES = ('confirmed', 'checked_in', 'done')

WEEKDAYS = [
    ('1', 'Lunes'),
    ('2', 'Martes'),
    ('3', 'Miércoles'),
    ('4', 'Jueves'),
    ('5', 'Viernes'),
    ('6', 'Sábado'),
    ('7', 'Domingo'),
]
HOURS = [('%02d' % hour, '%02d:00' % hour) for hour in range(24)]


class SpaReportOccupancy(models.Model):
    """Ocupación de cada espacio por fecha local y hora.

    Una fila por espacio, día y hora del horario de atención (aunque esté vacía, para que los
    promedios de ocupación sean reales), más las horas fuera de horario que tengan movimiento.

    * Cupos reservados: reservas confirmadas, en curso o atendidas que se superponen con la hora.
    * Ingresos registrados: personas que hicieron check-in en esa hora (llegadas).
    * Personas dentro: personas con check-in vigente durante la hora (hasta su salida o, si no
      registraron salida, hasta la permanencia máxima del espacio).
    * Ocupado: el mayor entre cupos reservados y personas dentro (no suma dos veces a quien reservó
      e ingresó).

    La consulta se arma en cada lectura con la zona horaria del spa (``spa.timezone``).
    """
    _name = 'spa.report.occupancy'
    _description = 'Ocupación por espacio y hora'
    _auto = False
    _order = 'date desc, hour, space_id'
    _rec_name = 'space_id'
    _depends = {
        'spa.booking': ['space_id', 'start', 'stop', 'state', 'seats'],
        'spa.access.log': ['space_id', 'check_in', 'check_out', 'people', 'state'],
        'spa.space': ['capacity', 'open_hour', 'close_hour', 'active', 'company_id', 'access_mode', 'max_stay',
                      'open_mon', 'open_tue', 'open_wed', 'open_thu', 'open_fri', 'open_sat', 'open_sun'],
        'spa.space.closure': ['space_id', 'date_from', 'date_to'],
    }

    space_id = fields.Many2one('spa.space', string='Espacio', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    access_mode = fields.Selection([
        ('slot', 'Por franja horaria (con reserva)'),
        ('free', 'Libre con control de aforo (check-in)'),
    ], string='Modo de acceso', readonly=True)
    date = fields.Date('Fecha', readonly=True)
    weekday = fields.Selection(WEEKDAYS, string='Día de la semana', readonly=True)
    hour = fields.Selection(HOURS, string='Hora', readonly=True)
    is_open = fields.Boolean('En horario de atención', readonly=True)
    capacity = fields.Integer('Aforo (cupos-hora)', readonly=True, aggregator='sum')
    booked_seats = fields.Integer('Cupos reservados', readonly=True, aggregator='sum')
    checkin_people = fields.Integer('Ingresos registrados (personas)', readonly=True, aggregator='sum')
    present_people = fields.Integer('Personas dentro', readonly=True, aggregator='sum')
    occupied = fields.Integer('Ocupado', readonly=True, aggregator='sum')
    free_seats = fields.Integer('Cupos libres', readonly=True, aggregator='sum')
    occupancy_pct = fields.Float('Ocupación (%)', readonly=True, aggregator='avg', digits=(16, 1))

    @property
    def _table_query(self):
        tz = self.env['spa.tools'].spa_tz().zone
        # PostgreSQL estima 1000 filas por cada generate_series por fila: el costo estimado supera
        # jit_above_cost y compilar con JIT tarda más que la consulta (~1 s con 2 años de datos frente a
        # ~0,3 s sin JIT). Se desactiva JIT solo en la transacción actual.
        self.env.cr.execute(SQL("SET LOCAL jit = off"))
        return SQL("""
            WITH params AS (
                SELECT (NOW() AT TIME ZONE %(tz)s)::date AS today,
                       (NOW() AT TIME ZONE 'UTC') AS now_utc
            ),
            bounds AS (
                SELECT LEAST(COALESCE(b.first_day, p.today), COALESCE(l.first_day, p.today), p.today) AS day_from,
                       GREATEST(COALESCE(b.last_day, p.today), p.today) AS day_to
                  FROM params p
                 CROSS JOIN (SELECT MIN((start AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date) AS first_day,
                                    MAX((stop AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date) AS last_day
                               FROM spa_booking
                              WHERE state IN %(booked)s) b
                 CROSS JOIN (SELECT MIN((check_in AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date) AS first_day
                               FROM spa_access_log) l
            ),
            calendar AS (
                SELECT s.id AS space_id, d::date AS day, h AS hour
                  FROM spa_space s
                 CROSS JOIN bounds
                 CROSS JOIN LATERAL generate_series(bounds.day_from, bounds.day_to, interval '1 day') AS d
                 CROSS JOIN generate_series(0, 23) AS h
                 WHERE s.active
                   AND h >= floor(s.open_hour) AND h < ceil(s.close_hour)
                   AND CASE extract(isodow FROM d)::int
                           WHEN 1 THEN s.open_mon WHEN 2 THEN s.open_tue WHEN 3 THEN s.open_wed
                           WHEN 4 THEN s.open_thu WHEN 5 THEN s.open_fri WHEN 6 THEN s.open_sat
                           ELSE s.open_sun END
                   AND NOT EXISTS (SELECT 1 FROM spa_space_closure c
                                    WHERE c.space_id = s.id AND d::date BETWEEN c.date_from AND c.date_to)
            ),
            booked AS (
                SELECT b.space_id, slot::date AS day, extract(hour FROM slot)::int AS hour, SUM(b.seats) AS qty
                  FROM spa_booking b
                 CROSS JOIN LATERAL generate_series(
                           date_trunc('hour', b.start AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s),
                           (b.stop AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s) - interval '1 microsecond',
                           interval '1 hour') AS slot
                 WHERE b.state IN %(booked)s AND b.space_id IS NOT NULL
                 GROUP BY 1, 2, 3
            ),
            visits AS (
                SELECT l.space_id, l.people,
                       l.check_in AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s AS local_in,
                       COALESCE(l.check_out,
                                LEAST(p.now_utc, l.check_in + COALESCE(NULLIF(s.max_stay, 0), 2.0) * interval '1 hour')
                       ) AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s AS local_out
                  FROM spa_access_log l
                  JOIN spa_space s ON s.id = l.space_id
                 CROSS JOIN params p
            ),
            arrivals AS (
                SELECT space_id, local_in::date AS day, extract(hour FROM local_in)::int AS hour, SUM(people) AS qty
                  FROM visits
                 GROUP BY 1, 2, 3
            ),
            present AS (
                SELECT v.space_id, slot::date AS day, extract(hour FROM slot)::int AS hour, SUM(v.people) AS qty
                  FROM visits v
                 CROSS JOIN LATERAL generate_series(
                           date_trunc('hour', v.local_in),
                           GREATEST(v.local_out - interval '1 microsecond', v.local_in),
                           interval '1 hour') AS slot
                 GROUP BY 1, 2, 3
            ),
            usage AS (
                SELECT space_id, day, hour,
                       SUM(booked) AS booked, SUM(arrived) AS arrived, SUM(present) AS present
                  FROM (SELECT space_id, day, hour, qty AS booked, 0 AS arrived, 0 AS present FROM booked
                        UNION ALL
                        SELECT space_id, day, hour, 0, qty, 0 FROM arrivals
                        UNION ALL
                        SELECT space_id, day, hour, 0, 0, qty FROM present) AS movements
                 GROUP BY 1, 2, 3
            ),
            grid AS (
                SELECT COALESCE(c.space_id, u.space_id) AS space_id,
                       COALESCE(c.day, u.day) AS day,
                       COALESCE(c.hour, u.hour) AS hour,
                       c.space_id IS NOT NULL AS is_open,
                       COALESCE(u.booked, 0)::int AS booked,
                       COALESCE(u.arrived, 0)::int AS arrived,
                       COALESCE(u.present, 0)::int AS present
                  FROM calendar c
                  FULL OUTER JOIN usage u
                    ON u.space_id = c.space_id AND u.day = c.day AND u.hour = c.hour
            )
            SELECT (g.space_id::bigint * 100000 + (g.day - DATE '2000-01-01')) * 24 + g.hour AS id,
                   g.space_id,
                   s.company_id,
                   s.access_mode,
                   g.day AS date,
                   extract(isodow FROM g.day)::int::varchar AS weekday,
                   lpad(g.hour::text, 2, '0') AS hour,
                   g.is_open,
                   s.capacity,
                   g.booked AS booked_seats,
                   g.arrived AS checkin_people,
                   g.present AS present_people,
                   GREATEST(g.booked, g.present) AS occupied,
                   GREATEST(s.capacity - GREATEST(g.booked, g.present), 0) AS free_seats,
                   CASE WHEN s.capacity > 0
                        THEN 100.0 * GREATEST(g.booked, g.present) / s.capacity ELSE 0 END AS occupancy_pct
              FROM grid g
              JOIN spa_space s ON s.id = g.space_id
        """, tz=tz, booked=BOOKED_STATES)
