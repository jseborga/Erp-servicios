# ERP-CRM Servicios — Spa / Piscina sobre Odoo Community 19

Sistema de gestión para un centro **VIP de piscina, sauna, jacuzzi, masajes y cafetería/restaurante**, construido de forma modular sobre **Odoo Community Edition 19** con localización contable para **Bolivia**.

> Estado: **diseño y especificación (fase 0)**. Este repositorio contiene las especificaciones técnicas para la implementación y un **MVP navegable en HTML** (maqueta con datos ilustrativos, sin backend).

## Objetivos

1. **Para el socio**: registrarse, elegir membresía, reservar horarios, gestionar invitados y pagar con QR desde la web o por WhatsApp, con el mínimo de pasos.
2. **Para la operación**: control de aforo y agenda, check-in, comandas del restaurante, compras y caja chica.
3. **Para la administración**: métricas de uso y rentabilidad por área, CRM con embudo, contabilidad boliviana (IVA, IT, IUE, retenciones, SIAT).

## Contenido

| Ruta | Contenido |
|---|---|
| [`docs/00-vision-y-alcance.md`](docs/00-vision-y-alcance.md) | Visión, alcance, principios de diseño |
| [`docs/01-arquitectura-modulos.md`](docs/01-arquitectura-modulos.md) | Módulos Odoo CE / OCA / propios y dependencias |
| [`docs/02-modelo-de-datos.md`](docs/02-modelo-de-datos.md) | Modelos, campos y relaciones |
| [`docs/03-espacios-servicios-reservas.md`](docs/03-espacios-servicios-reservas.md) | Espacios, aforo, franjas, motor de disponibilidad |
| [`docs/04-membresias.md`](docs/04-membresias.md) | Planes, derechos, saldos, invitados, cancelación |
| [`docs/05-pagos-mora-facturacion.md`](docs/05-pagos-mora-facturacion.md) | Cobros, QR, mora, ofertas, facturación SIAT |
| [`docs/06-crm.md`](docs/06-crm.md) | Fuentes, embudo, cortesías e invitados como prospectos |
| [`docs/07-restaurante-pos.md`](docs/07-restaurante-pos.md) | Mesas, mostrador, comanda abierta, cargo a cuenta |
| [`docs/08-compras-fondo-fijo.md`](docs/08-compras-fondo-fijo.md) | Compras con/sin factura, retenciones, unicidad, caja chica |
| [`docs/09-contabilidad-plan-cuentas.md`](docs/09-contabilidad-plan-cuentas.md) | Plan de cuentas sobre `l10n_bo`, analítica, asientos tipo |
| [`docs/10-roles-permisos.md`](docs/10-roles-permisos.md) | Roles, grupos y reglas de acceso |
| [`docs/11-integraciones.md`](docs/11-integraciones.md) | WhatsApp, QR de pago, proveedor SIAT |
| [`docs/12-plan-por-fases.md`](docs/12-plan-por-fases.md) | Roadmap y criterios de aceptación |
| [`docs/13-vacios-y-verificaciones.md`](docs/13-vacios-y-verificaciones.md) | **Lo que NO está verificado** y debe confirmarse |
| [`mvp/index.html`](mvp/index.html) | MVP navegable (portal del socio + panel administrador). Versión publicada: https://claude.ai/artifact/VZxugYxhRMrm3b3msgXjfC (privada hasta que se comparta) |
| [`CLAUDE.md`](CLAUDE.md) | Convenciones para quien implemente (humano o IA) |

## Hechos verificados sobre Odoo 19 (11-oct-2026)

Verificado directamente contra las ramas `19.0` de `odoo/odoo` y de la OCA:

- **No están en Community 19**: `membership`, `appointment`, `website_appointment`, `sale_subscription`, `whatsapp`, `account_accountant`.
- **Sí están en Community 19**: `l10n_bo`, `pos_restaurant`, `pos_self_order`, `hr_expense`, `crm`, `website_sale`, `website_crm`, `loyalty`, `sale_loyalty`, `event`, `resource`, `calendar`, `purchase`, `stock`, `mrp`, `hr_attendance`, `sms`.
- **OCA rama 19.0 disponible**: `membership`, `membership_variable_period` (vertical-association); `contract`, `subscription_oca` (contract); `resource_booking` (calendar).
- **`l10n_bo` v2.0** (Odoo / Cubic ERP): 127 cuentas, 99 filas de impuestos, incluye retenciones de bienes (8 %) y servicios (15,5 %) en modo *grossing-up*. Detalle en `docs/09`.

## Licencia

Por definir por el propietario del repositorio. Los módulos propios que dependan de módulos LGPL/AGPL de Odoo/OCA deben respetar esas licencias.
