# 03 · Espacios, servicios y reservas

## Configuración inicial acordada (editable)
| Espacio | Aforo | Modo | Personal |
|---|---|---|---|
| Piscina | 15 | configurable (franja o libre) | No (activable: salvavidas) |
| Sauna | 5 | configurable | No |
| Jacuzzi | 5 | configurable | No |
| Cabina de masajes | 1 | franja | Sí: 1 masajista |

Agregar un segundo masajista = crear el empleado con la especialidad "Masajista" y su turno. Agregar una cabina = crear otro espacio. **No requiere código.**

## Modo por franja (`slot`)
- Un cron genera `spa.slot` a N días (configurable, p. ej. 30) según el horario del espacio, la duración de franja y el tiempo de limpieza.
- El socio elige franja; se descuentan cupos.
- Si la franja está llena: **lista de espera** con aviso automático si se libera un cupo.

## Modo libre (`free`)
- No hay franjas: el socio llega y hace **check-in con su QR**.
- Si la ocupación actual = aforo, recepción ve "Lleno" y el sistema ofrece la próxima hora estimada.
- Opcional: **pre-reserva de llegada** (ventana de 30 min) para garantizar cupo sin franja fija.
- Check-out por QR o automático al cumplirse `max_stay`.

## Servicios con personal
Disponibilidad = **mínimo** entre cupos del espacio y personal libre con la especialidad, respetando su turno (`resource.calendar`) y ausencias (`resource.calendar.leaves`).

## Flujo de reserva (cualquier canal)
1. Elegir servicio → fecha → franja disponible.
2. El sistema valida, en este orden:
   1. Membresía activa (no `suspended`/`expired`) o pago suelto.
   2. Horario permitido por el plan y por la línea de derecho.
   3. Saldo disponible del derecho en el período.
   4. Tope de frecuencia (p. ej. 1 masaje por semana).
   5. Cupos libres (incluyendo invitados).
   6. Anticipación mínima/máxima.
3. Confirmación → consumo provisional en `spa.consumption` (reason `booking`).
4. Recordatorio automático (WhatsApp/email) X horas antes.
5. Check-in → `checked_in`. Al final → `done`.

## Cancelaciones y no-show
- Cancelación dentro de `free_cancel_hours` → se revierte el consumo.
- Cancelación tardía → según política: nada / pierde la sesión (consumo se mantiene) / cobro de penalidad (factura).
- No-show (cron tras fin de franja sin check-in) → según política de no-show.
- `max_cancellations_per_month` → bloquea nuevas cancelaciones sin penalidad.

## Recepción (vista de agenda)
Vista calendario por espacio y por terapeuta, con ocupación por franja (p. ej. "Piscina 10:00–12:00 · 9/15"). Reserva rápida buscando socio por nombre, CI o teléfono.

## Criterios de aceptación (tests)
- No se puede confirmar una reserva que exceda el aforo, aun con dos usuarios simultáneos.
- Un masaje no se puede reservar si el masajista no tiene turno o ya está ocupado.
- Una reserva fuera del horario permitido del plan se rechaza con mensaje claro.
- Cambiar el aforo de un espacio no afecta reservas ya confirmadas (se marca sobre-aforo para revisión).
