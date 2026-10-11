# Part of ERP Servicios Spa. License LGPL-3.
"""Utilidades de fecha y hora del spa.

Las fechas se guardan en UTC (como todo Odoo); los horarios del negocio
(apertura, franjas, horario permitido de un plan) se expresan en hora local.
La zona horaria se configura con el parámetro del sistema ``spa.timezone``
(por defecto America/La_Paz).
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, models

DEFAULT_TZ = 'America/La_Paz'


def float_to_time(value):
    """8.5 -> time(8, 30). 24.0 -> time(23, 59, 59)."""
    if value >= 24:
        return time(23, 59, 59)
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return time(hours, minutes)


class SpaTools(models.AbstractModel):
    _name = 'spa.tools'
    _description = 'Utilidades del spa'

    @api.model
    def spa_tz(self):
        name = self.env['ir.config_parameter'].sudo().get_param('spa.timezone') or DEFAULT_TZ
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone(DEFAULT_TZ)

    @api.model
    def to_local(self, dt_utc):
        """Datetime UTC naïve -> datetime local naïve."""
        if not dt_utc:
            return dt_utc
        return pytz.utc.localize(dt_utc).astimezone(self.spa_tz()).replace(tzinfo=None)

    @api.model
    def to_utc(self, dt_local):
        """Datetime local naïve -> datetime UTC naïve."""
        if not dt_local:
            return dt_local
        return self.spa_tz().localize(dt_local).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def local_combine(self, day, hour_float):
        """Fecha local + hora decimal -> datetime UTC naïve."""
        return self.to_utc(datetime.combine(day, float_to_time(hour_float)))

    @api.model
    def local_today(self):
        return self.to_local(datetime.utcnow()).date()

    @api.model
    def local_hour(self, dt_utc):
        local = self.to_local(dt_utc)
        return local.hour + local.minute / 60.0

    @api.model
    def week_bounds(self, day):
        """Lunes y domingo (inclusive) de la semana de ``day``."""
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)

    @api.model
    def month_bounds(self, day):
        start = day.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return start, next_month - timedelta(days=1)
