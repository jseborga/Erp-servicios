# 12 · Plan por fases

## Fase 0 — Fundamentos (verificación y entorno)
- Entorno Docker Odoo 19 CE + PostgreSQL; repos OCA `contract`, `vertical-association`, `calendar` (19.0).
- **Spikes de evaluación**: `resource_booking` (masajes), `contract`/`subscription_oca` (facturación recurrente).
- Instalar `l10n_bo` y revisar plan e impuestos con el contador.
- Elegir proveedor SIAT y proveedor de QR (comparativa).
- Resolver los ítems de `docs/13`.

**Entregable**: decisión documentada de cada punto + base instalada.

## Fase 1 — MVP operativo
- `spa_base`, `spa_booking`, `spa_membership`, `spa_access` (check-in QR).
- `spa_billing` con QR + validación manual, renovación con aviso, días de gracia, suspensión.
- `spa_portal`: planes, registro, reservas, saldo, invitados, pagos.
- `spa_messaging` con proveedor `wa_link`.
- `l10n_bo_spa`: cuentas adicionales, analítica por área.
- `pos_restaurant` configurado + `spa_pos` (socio en comanda, descuentos por plan, cargo a cuenta).
- Roles y permisos.

**Criterios de aceptación**: un socio puede comprar un plan desde la web, pagar con QR, reservar un masaje y la piscina, traer un invitado y consumir en cafetería con descuento; el administrador ve el saldo consumido, el ingreso diferido y la venta por área.

## Fase 2 — Fiscal y compras
- `l10n_bo_siat_edi` con el proveedor elegido (web y POS).
- `l10n_bo_purchase`: tipos de documento, unicidad, lector QR, Libro de Compras.
- `l10n_bo_petty_cash`: fondos, rendición, reposición.
- Retenciones en ambos modos + cuentas no deducibles.

## Fase 3 — CRM y crecimiento
- `spa_crm`: fuentes, embudo de captación y de retención, cortesías, invitados → leads, actividades automáticas.
- `spa_messaging` con API oficial de WhatsApp.
- Promociones (`loyalty`), ofertas de pago con vigencia y cuotas.
- `spa_reports`: tableros de ocupación, uso por plan, MRR, mora, conversión, rentabilidad por área con prorrateo.

## Fase 4 — Ampliaciones
- Alquiler de ambientes para eventos y actividades recurrentes (clases de natación, aquagym) con instructores.
- Costeo por receta en restaurante (`mrp`).
- Conciliación QR automática, pago con tarjeta.
- Nómina boliviana.
