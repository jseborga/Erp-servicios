# 00 · Visión y alcance

## El negocio
Centro de bienestar **exclusivo** con: piscina, sauna, jacuzzi, masajes y cafetería/restaurante. El concepto VIP depende de **controlar el aforo y los horarios**: pocas personas a la vez, todas con reserva o con acceso controlado.

Fuentes de ingreso:
- Membresías (mensual, trimestral, anual, configurables).
- Entradas sueltas y servicios sueltos (p. ej. un masaje).
- Tarifas de invitados.
- Restaurante / cafetería.
- Alquiler de ambientes para eventos y actividades recurrentes (clases de natación, baile acuático) — **alcance de fase posterior**, ver `docs/12`.
- Penalidades (cancelación tardía, no-show), si el plan lo define.

## Las tres capas

```
┌────────────────────────────────────────────────────────────┐
│ 1. CARA AL CLIENTE                                         │
│   Web/portal del socio · WhatsApp · Atención telefónica    │
│   registro · planes · reservas · invitados · pago QR       │
├────────────────────────────────────────────────────────────┤
│ 2. NÚCLEO DEL NEGOCIO                                      │
│   Espacios y servicios · Motor de reservas y aforo         │
│   Membresías con derechos y saldos · Check-in · CRM        │
├────────────────────────────────────────────────────────────┤
│ 3. TRASTIENDA                                              │
│   POS restaurante · Compras · Fondo fijo · Personal        │
│   Contabilidad l10n_bo · Analítica por área · SIAT         │
└────────────────────────────────────────────────────────────┘
```

## Principios de diseño
1. **Simple para el socio, completo para el administrador.** El socio ve "te quedan 3 masajes"; el administrador ve el libro de consumos que lo explica.
2. **Todo configurable.** Ninguna regla comercial (aforo, cupos, precios, políticas, tasas) vive en el código.
3. **Un solo modelo para todos los servicios:** espacio + personal opcional + reglas.
4. **Canales intercambiables:** la misma operación (reservar, pagar) se puede hacer desde la web, desde recepción o vía WhatsApp asistido.
5. **Contabilidad completa y legal.** Todo se registra; lo no deducible se separa, no se oculta.
6. **Community primero.** Se usan módulos estándar de Odoo CE 19 y de la OCA; lo específico se construye como módulos propios.

## Fuera de alcance de la primera versión
- Débito automático recurrente con tarjeta (poco usual en Bolivia; se deja preparada la pasarela para fase futura).
- Costeo por receta en restaurante (estructura lista; se activa en fase posterior).
- App móvil nativa (el portal será responsive / PWA).
- Planillas de sueldos completas con aportes (requiere módulo de nómina boliviana; ver `docs/13`).
