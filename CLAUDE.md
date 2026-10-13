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

## Estructura (implementada)
```
addons/
  l10n_bo_spa/           # plan de cuentas sobre l10n_bo, retenciones, correcciones, analítica por área
  l10n_bo_purchase/      # compras SIAT: tipo de documento, CUF/dosificación, unicidad, QR, Libro de Compras
  l10n_bo_petty_cash/    # fondo fijo imprest: vales, rendición, reposición
  l10n_bo_siat_edi/      # facturación de ventas: Portal Web, proveedor por API (solo simulador), Libro de Ventas
  spa_base/              # espacios, servicios, personal, roles, utilidades (spa.tools.local_today)
  spa_membership/        # planes, derechos, saldos, invitados, políticas, congelamiento
  spa_booking/           # reservas, aforo, lista de espera, no-show
  spa_access/            # check-in/out con QR, aforo en vivo, pase diario
  spa_messaging/         # mensajería intercambiable (wa.me / API de Meta)
  spa_billing/           # cobros, pagos por validar, cobranza, cuotas, cambio de plan, devengo
  spa_portal/            # web pública y portal del socio
  spa_crm/               # fuentes, Captación y Retención, cortesías, riesgo de baja
  spa_pos/               # restaurante y cafetería: descuento del plan, cuenta del socio
  spa_reports/           # tablero y reportes, estado de resultados por área (MIS)
  spa_rental/            # alquiler de ambientes y clases recurrentes
  spa_all/               # instala todo, cruza roles, pruebas de punta a punta y recorridos en navegador
  spa_demo/              # datos de demostración (nunca en producción)
third_party/oca/         # módulos OCA fijados por commit (no editar a mano: scripts/update_oca.sh)
docker/                  # entrypoint de la imagen
mvp/                     # maqueta HTML inicial
docs/                    # especificaciones, estado (docs/12), vacíos (docs/13), despliegue (docs/14), guía por rol (docs/15)
```

## Entorno de desarrollo
- `docker compose -f docker-compose.yml -f docker-compose.ports.yml up -d --build` (ver `docs/14`).
- Imagen base `odoo:19.0`, **nunca** `latest` (apunta a Odoo 20). PostgreSQL 16 (Odoo 19 exige ≥ 13).
- Pruebas de un módulo: `odoo -c /etc/odoo/odoo.conf -d <base_de_prueba> -u <módulo> --test-tags /<módulo> --stop-after-init`. Suite completa: `docs/14` § Pruebas. **Siempre sobre una base nueva**, nunca sobre producción ni sobre la demostración (hay conteos globales).
- Recorridos en navegador: definir `ODOO_BROWSER_BIN` con la ruta de Chrome/Chromium; sin ella se omiten.
- Los módulos que dependan del plan de cuentas usan `self.env['account.chart.template'].ref('<xmlid>')` para obtener cuentas por compañía (p. ej. `ref('l10n_bo_spa_1115')`).
- En una base nueva los `post_init_hook` corren **antes** de cargar el plan contable: encadenar con `registry._auto_install_template` (ver `l10n_bo_spa/__init__.py`, `spa_pos/__init__.py`) o usar `@template('bo', ...)`.
- Fechas de negocio con `self.env['spa.tools'].local_today()` (zona de la compañía), no `fields.Date.today()` (UTC).
