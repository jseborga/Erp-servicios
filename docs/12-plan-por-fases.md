# 12 · Estado y plan por fases

Estado al 13-oct-2026. «Hecho» = implementado y cubierto por pruebas automáticas que pasan sobre una base nueva con todos los módulos.

## Fase 0 — Fundamentos ✅
- Odoo 19 CE + PostgreSQL 16 en Docker; módulos OCA fijados por commit.
- Plan de cuentas boliviano extendido (`l10n_bo_spa`), con correcciones a `l10n_bo` encontradas en pruebas.

## Fase 1 — Operación del spa ✅
| Proceso | Estado | Módulo |
|---|---|---|
| Espacios con aforo, horario, modo por franja o libre, cierres | Hecho | `spa_base` |
| Planes con derechos, saldos mensuales, traslado, tope de frecuencia, horario permitido | Hecho | `spa_membership` |
| Invitados (free pass y tarifa) | Hecho | `spa_membership`, `spa_billing` |
| Reservas con aforo y personal, cancelación tardía, no-show, lista de espera | Hecho | `spa_booking` |
| Congelamiento de membresía | Hecho | `spa_membership` |
| Check-in con QR, aforo en vivo, pase diario de no socios | Hecho | `spa_access`, `spa_billing` |
| Cobros: factura al cobrar, pagos QR por validar, renovación, escalera de cobranza, cuotas, cambio de plan | Hecho | `spa_billing` |
| Devengo de planes prepagados (215100 → ingresos) | Hecho | `spa_billing` |
| Web del socio: planes, alta, credencial, reservas, invitados, pago, clases | Hecho | `spa_portal`, `spa_rental` |
| WhatsApp por enlace wa.me | Hecho | `spa_messaging` |
| Restaurante y cafetería: descuento por plan, cuenta del socio | Hecho | `spa_pos` |
| Roles y permisos por área | Hecho | todos (`spa_all` cruza roles) |

## Fase 2 — Fiscal y compras ✅ (con verificaciones pendientes)
| Proceso | Estado | Pendiente |
|---|---|---|
| Compras con CUF / dosificación, unicidad, lector QR, Libro de Compras | Hecho | Formato oficial del RCV y catálogos del SIN |
| Compras sin factura con retenciones (8 / 15,5 / 16 %) | Hecho | Confirmar casos con el contador |
| Fondo fijo imprest | Hecho | — |
| Facturación SIAT: Portal Web (registro manual de número y CUF) | Hecho | — |
| Facturación SIAT por API de proveedor | **Solo simulador** | Elegir proveedor certificado y programar su conector |
| Venta sin factura autorizada, anulación, Libro de Ventas | Hecho | Confirmar casos legales y formato |

## Fase 3 — CRM y gestión ✅
- Captación y retención, invitados y cortesías como prospectos, altas web abandonadas → «Propuesta».
- Tablero y reportes: ocupación, uso y rentabilidad por plan, ingresos, mora, resultado por área (MIS).

## Fase 4 — Ampliaciones
| Proceso | Estado |
|---|---|
| Alquiler de ambientes para eventos (con garantía) | Hecho (`spa_rental`) |
| Clases recurrentes con instructor e inscripciones | Hecho (`spa_rental`) |
| Datos de demostración | Hecho (`spa_demo`) |
| WhatsApp por API oficial de Meta | Código listo, **no probado** contra Meta (requiere número y token) |
| Conciliación automática de pagos QR con el banco | Pendiente (requiere API del banco o proveedor) |
| Pago con tarjeta en línea | Pendiente |
| Costeo por receta en restaurante | Pendiente (estructura de cuentas lista; requiere `mrp`) |
| Nómina boliviana | Pendiente (CE no incluye nómina; asiento de planilla manual en el diario PLAN) |
| Códigos promocionales en la web | Pendiente (las ofertas de pago sí existen) |
| «Un café diario incluido en el plan» | Pendiente |

## Para salir a producción
1. Revisión del contador: plan de cuentas, retenciones, deducibilidad, venta sin factura, devengo de IVA en cuotas y planes prepagados ([`docs/13`](13-vacios-y-verificaciones.md)).
2. Datos reales: NIT de la empresa, QR del banco, diarios bancarios, precios, planes, personal y horarios.
3. Modalidad SIAT: Portal Web desde el día 1; proveedor por API cuando haya contrato.
4. Capacitación por rol con la base de demostración (`spa_demo`) en un servidor aparte.
5. Copias de seguridad automáticas probadas.
