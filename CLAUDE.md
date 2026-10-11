# Guía para implementar este repositorio

Este archivo orienta a cualquier desarrollador (o asistente de IA) que implemente los módulos.

## Objetivo técnico
Módulos Odoo **Community 19.0** (Python 3.10+ / PostgreSQL / OWL) para un spa/piscina VIP en Bolivia. Las especificaciones están en `docs/`. **Leer `docs/13-vacios-y-verificaciones.md` antes de implementar cualquier cosa que dependa de un ítem marcado como no verificado.**

## Reglas
1. **Solo Community + OCA.** Nunca depender de módulos Enterprise (`appointment`, `sale_subscription`, `account_accountant`, `whatsapp`, `account_reports`, `web_studio`…).
2. **Todo configurable desde el backend.** Aforos, tasas de retención, políticas de cancelación, días de gracia, cupos de invitados, descuentos: son datos, no constantes en código.
3. **No reinventar lo estándar.** Contabilidad → `account` + `l10n_bo`; POS → `point_of_sale` + `pos_restaurant`; CRM → `crm`; web → `website`/`portal`; empleados → `hr`.
4. **Prefijo de módulos propios:** `spa_` (negocio) y `l10n_bo_` (fiscal). Carpeta: `addons/`.
5. **Multiempresa-safe:** todo modelo propio con `company_id` y reglas `ir.rule`.
6. **Seguridad:** cada modelo nuevo con `ir.model.access.csv` por grupo (ver `docs/10`).
7. **Tests:** `odoo.tests.TransactionCase` para reglas de negocio (saldo de derechos, aforo, unicidad de facturas de compra, asiento de reposición de fondo fijo).
8. **Idioma:** código y nombres técnicos en inglés; etiquetas y traducciones `es_BO`/`es_419`.
9. **Nunca** diseñar mecanismos para ocultar operaciones a la contabilidad (cuentas bancarias no registradas, ventas sin registro). Toda operación se registra; las no deducibles van a su cuenta.

## Estructura prevista
```
addons/
  spa_base/              # espacios, servicios, configuración general
  spa_booking/           # motor de reservas y aforo
  spa_membership/        # planes, derechos, saldos, invitados, políticas
  spa_access/            # check-in/out con QR, control de aforo en vivo
  spa_billing/           # cobro de membresías, mora, ofertas de pago
  spa_crm/               # fuentes, embudo, cortesías → leads
  spa_portal/            # web del socio (website + portal)
  spa_pos/               # POS: socio en comanda, cargo a cuenta, descuentos por plan
  spa_messaging/         # capa de mensajería intercambiable (wa.me / API)
  spa_reports/           # tableros y métricas
  l10n_bo_spa/           # cuentas adicionales, impuestos RC-IVA, analítica por área
  l10n_bo_purchase/      # registro de compras SIAT: tipo doc, CUF, unicidad
  l10n_bo_petty_cash/    # fondo fijo: rendición y reposición
  l10n_bo_siat_edi/      # conector a proveedor de facturación SIAT (por API)
mvp/                     # maqueta HTML
docs/                    # especificaciones
```

## Entorno de desarrollo sugerido
- Odoo `19.0` community + `OCA/contract`, `OCA/vertical-association`, `OCA/calendar` en rama `19.0`.
- Docker Compose con `odoo:19` y `postgres:16` (versión exacta de PostgreSQL a confirmar con los requisitos oficiales de Odoo 19).
