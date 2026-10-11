# 04 · Membresías

## Concepto: plan con derechos
El administrador crea planes, los nombra y agrega **líneas de derechos**. Cada línea tiene sus reglas.

Ejemplo **Premium** (ilustrativo):

| Servicio | Cantidad | Período | Tope frecuencia | Horario | Saldo no usado | Invitados |
|---|---|---|---|---|---|---|
| Masaje 60' | 4 | mes | 1 por semana | agenda del masajista | se pierde | No |
| Piscina | ilimitado | — | — | 07:00–21:00 | — | Sí |
| Jacuzzi | 5 | mes | — | 10:00–20:00 | traslada máx. 2 | Sí |

Nivel plan: 2 invitados/mes en free pass; luego tarifa de invitado; 10 % en cafetería; política de cancelación "Estándar"; 5 días de gracia.

## Duraciones y precios
`spa.plan.period`: mensual, trimestral, anual (y cualquier otra). Cada una con su producto y precio. Los descuentos por pago adelantado se pueden expresar como precio del período o como **oferta de pago** con vigencia (ver `docs/05`).

## Ciclo de vida
```
draft ──pago──► active ──vence sin pago──► grace ──días de gracia──► suspended
                  ▲                          │                            │
                  └──────────pago────────────┴────────────pago────────────┘
active/suspended ──fin sin renovación──► expired      cualquier estado ──► cancelled
```
- `grace`: acceso permitido, avisos activos.
- `suspended`: sin reservas nuevas ni check-in; reservas futuras quedan "en espera de pago" (configurable: cancelar o mantener).

## Generación de saldos
Cron diario: para cada membresía activa crea los `spa.entitlement` del período que comienza, aplicando la regla de traslado de la línea:
- `lose`: el saldo nuevo = cantidad.
- `accumulate`: nuevo = cantidad + restante anterior (tope `carryover_max` si se define).
- `carry_limited`: nuevo = cantidad + min(restante, `carryover_max`).

## Invitados
Dos niveles acumulativos:
1. **Plan**: cupo de free pass por período.
2. **Línea**: si ese servicio admite invitados y cuántos por reserva.

Si el cupo de free pass está agotado → se agrega la **tarifa de invitado** a la cuenta del socio (orden de venta/factura). Cada invitado: ocupa aforo, se registra con nombre y teléfono, y **crea o actualiza un lead en el CRM** con `referred_by_partner_id` = socio.

## Cambios de plan
- Upgrade a mitad de período: prorrateo del precio (fórmula configurable: días restantes / días del período).
- Downgrade: efectivo al siguiente período.
- Congelamiento (viaje, salud): opcional, extiende `date_end` por los días congelados; máximo configurable por plan.

## Lo que ve el socio (portal)
- Plan actual, vencimiento, estado.
- Por servicio: "Te quedan 3 de 4 masajes este mes · próximo disponible: martes".
- Invitados: "1 de 2 free pass usados".
- Historial de uso y pagos.

## Métricas para administración
- Uso real vs. derechos otorgados por plan (tasa de utilización).
- Costo de servir por plan (consumos × costo estándar del servicio) vs. ingreso del plan → **rentabilidad por plan**.
- Socios con uso bajo (riesgo de baja) → alimenta la etapa "En riesgo" del CRM.
