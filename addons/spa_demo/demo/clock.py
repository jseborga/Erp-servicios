# Part of ERP Servicios Spa. License LGPL-3.
"""Reloj simulado para cargar «semanas de operación» con los métodos reales del negocio.

Las reglas del spa dependen de la hora: no se reserva en el pasado, el check-in exige que la
reserva empiece en 30 minutos, la gracia vence por fecha, la factura toma la fecha del día...
Para que la historia de la demo sea consistente, cada operación se ejecuta *en su momento*:

* ``freezegun`` (dependencia de Odoo 19: ``setup.py`` / ``debian/control``) congela
  ``datetime.now()``, ``date.today()`` y ``time.time()`` de Python, que es lo que usan
  ``fields.Datetime.now()``, ``fields.Date.context_today()`` y ``spa.tools.local_today()``.
* El cursor guarda su propia hora de transacción (``cr.now()``: ``create_date``/``write_date``).
  Se fija en el mismo instante (``cr._now``) para que las fechas de creación cuadren con la
  historia (p. ej. «días hasta convertir» de un prospecto). Odoo la reinicia sola en el
  siguiente ``commit``/``rollback``.

El reloj solo avanza (nunca retrocede) y nunca pasa la hora real: así los asientos se numeran
en orden cronológico y nada queda «en el futuro».

Limitación conocida: ``freezegun`` actúa sobre todo el proceso. Instale el módulo desde la línea
de comandos o en una base de demostración sin otros usuarios conectados (en modo multi-hilo, las
otras peticiones verían la hora simulada mientras dura la carga, uno o dos minutos).
"""
import heapq
import logging
from datetime import datetime, timezone

from freezegun import api as freezegun_api
from freezegun.api import freeze_time

_logger = logging.getLogger(__name__)


class DemoClock:
    """Reloj congelado que avanza por una agenda de eventos ordenados por fecha y hora (UTC)."""

    def __init__(self, env):
        self.env = env
        self.real_now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        self.current = None
        self._freezer = None
        self._factory = None
        self._agenda = []
        self._seq = 0

    # ------------------------------------------------------------------
    # Congelar / liberar
    # ------------------------------------------------------------------
    def start(self, when):
        if self._freezer:
            raise RuntimeError('El reloj de la demo ya está corriendo.')
        when = min(when, self.real_now)
        # Sin inspección de la pila en cada lectura de la hora (Odoo la lee en cada consulta SQL): la carga
        # es de un solo hilo y los módulos ignorados por defecto (threading, queue...) no se parchean igual.
        self._inspection_limit = freezegun_api.call_stack_inspection_limit
        freezegun_api.call_stack_inspection_limit = 0
        self._freezer = freeze_time(when)
        self._factory = self._freezer.start()
        self.current = when
        self.env.cr._now = when
        return self

    def stop(self, flush=True):
        """Libera la hora. ``flush=False`` tras un error (no se escribe nada más en la transacción)."""
        try:
            if self._freezer and flush:
                self.env.flush_all()
        finally:
            if self._freezer:
                self._freezer.stop()
                self._freezer = self._factory = None
                freezegun_api.call_stack_inspection_limit = self._inspection_limit
            self.env.cr._now = None
            self.current = None

    @property
    def running(self):
        return bool(self._freezer)

    def move(self, when):
        """Avanza el reloj a ``when`` (UTC naïve). Nunca retrocede ni supera la hora real."""
        if not self._freezer:
            raise RuntimeError('El reloj de la demo no está corriendo.')
        when = min(when, self.real_now)
        if when < self.current:
            when = self.current
        if when != self.current:
            # Los campos calculados pendientes se calculan con la hora en que se escribieron.
            self.env.flush_all()
            self._factory.move_to(when)
            self.current = when
        self.env.cr._now = when
        return when

    # ------------------------------------------------------------------
    # Agenda
    # ------------------------------------------------------------------
    def schedule(self, when, label, func, *args, **kwargs):
        """Programa ``func(*args, **kwargs)`` para ``when`` (UTC). Devuelve False si es futuro."""
        if when > self.real_now:
            return False
        if self.current and when < self.current:
            when = self.current
        self._seq += 1
        heapq.heappush(self._agenda, (when, self._seq, label, func, args, kwargs))
        return True

    def pending(self):
        return len(self._agenda)

    def run(self, runner):
        """Ejecuta la agenda en orden. ``runner(label, func, args, kwargs)`` envuelve cada evento."""
        while self._agenda:
            when, _seq, label, func, args, kwargs = heapq.heappop(self._agenda)
            self.move(when)
            runner(label, func, args, kwargs)
