# ERP-CRM Servicios — Spa / Piscina sobre Odoo Community 19

Sistema de gestión para un centro **VIP de piscina, sauna, jacuzzi, masajes y cafetería/restaurante**, construido de forma modular sobre **Odoo Community Edition 19** con localización contable para **Bolivia**.

> **Estado (13-oct-2026): sistema completo y probado.** 17 módulos propios instalables (más 8 de la OCA), probados juntos sobre una base nueva: **315 pruebas automáticas en verde**, incluidas una prueba de punta a punta de «un mes de negocio» con usuarios reales por rol y recorridos en navegador. Antes de operar con datos reales: revisión del contador (ver [`docs/13`](docs/13-vacios-y-verificaciones.md)) y contrato con un proveedor SIAT si se factura por API.

## Inicio rápido (Docker)

```bash
git clone https://github.com/jseborga/erp-servicios.git && cd erp-servicios
cp .env.example .env        # cambie TODAS las contraseñas
docker compose -f docker-compose.yml -f docker-compose.ports.yml up -d --build
```

El primer arranque crea la base `spa` en español de Bolivia, moneda BOB, e instala `spa_all` (todo el sistema). Para un **servidor de demostración** use `ODOO_INIT_MODULES=spa_all,spa_demo`: carga un spa ficticio con seis semanas de operación y usuarios por rol con clave `demo` (nunca en producción). Easypanel y actualizaciones: [`docs/14`](docs/14-despliegue-docker-easypanel.md). Uso diario por rol: [`docs/15`](docs/15-guia-rapida-por-rol.md).

## Qué hace

| Área | Módulo | Funciones |
|---|---|---|
| Contabilidad Bolivia | `l10n_bo_spa` | Plan de cuentas sobre `l10n_bo` (+62 cuentas), retenciones 8 % / 15,5 % / 16 %, correcciones a `l10n_bo`, analítica por área, categorías con cuentas |
| | `l10n_bo_purchase` | Compras con CUF / dosificación, factura única (NIT + número + CUF), lector QR, retenciones sin factura, Libro de Compras |
| | `l10n_bo_petty_cash` | Fondo fijo imprest: vales con foto, rendición con arqueo, facturas y reposición al aprobar |
| | `l10n_bo_siat_edi` | Facturación de ventas: Portal Web del SIN (registro de número y CUF), proveedor por API (solo **simulador**), venta sin factura autorizada, anulación, Libro de Ventas |
| Operación | `spa_base` | Espacios (aforo, horario, modo por franja o libre), servicios, personal y roles |
| | `spa_membership` | Planes con derechos (cantidad, tope por semana, horario, traslado de saldo), invitados, políticas de cancelación, congelamiento |
| | `spa_booking` | Reservas con aforo y personal, lista de espera, cancelación tardía y no-show |
| | `spa_access` | Check-in con credencial QR, aforo en vivo, pase diario para no socios |
| | `spa_messaging` | WhatsApp con proveedor intercambiable: enlace wa.me (hoy) o API oficial de Meta |
| | `spa_billing` | Cobros (la factura se emite al cobrar o al prestar el servicio), pagos QR por validar, escalera de cobranza, cuotas, cambio de plan, devengo de planes prepagados |
| | `spa_rental` | Alquiler de ambientes para eventos (exclusivo o parcial, con garantía) y clases recurrentes (natación, aquagym) con inscripciones |
| Clientes | `spa_portal` | Web pública de planes y portal del socio: alta, credencial QR, saldos, reservas, invitados, pago con comprobante |
| | `spa_crm` | Fuentes, embudos de Captación y Retención, invitados y cortesías como prospectos, riesgo de baja |
| | `spa_pos` | Restaurante (mesas) y Cafetería: descuento del plan, cargo a la cuenta del socio con límite, analítica por área |
| Gestión | `spa_reports` | Tablero, ocupación por hora, uso y rentabilidad por plan, ingresos, mora, estado de resultados por área (MIS) |
| Instalación | `spa_all` | Instala todo y contiene las pruebas de punta a punta |
| | `spa_demo` | Opcional: datos de demostración |

Módulos OCA incluidos en [`third_party/oca`](third_party/oca): reportes contables, MIS Builder, activos fijos, gestiones fiscales.

## Documentación

| Ruta | Contenido |
|---|---|
| [`docs/00`](docs/00-vision-y-alcance.md) – [`docs/11`](docs/11-integraciones.md) | Visión, arquitectura, modelo de datos, reservas, membresías, cobros, CRM, POS, compras, contabilidad, roles, integraciones |
| [`docs/12-plan-por-fases.md`](docs/12-plan-por-fases.md) | Qué está hecho y qué falta |
| [`docs/13-vacios-y-verificaciones.md`](docs/13-vacios-y-verificaciones.md) | **Lo que NO está verificado** y lo que debe confirmar el contador o el SIN |
| [`docs/14-despliegue-docker-easypanel.md`](docs/14-despliegue-docker-easypanel.md) | Despliegue, variables, actualizaciones, copias de seguridad, pruebas |
| [`docs/15-guia-rapida-por-rol.md`](docs/15-guia-rapida-por-rol.md) | Cómo se usa el sistema en el día a día, por rol |
| [`mvp/index.html`](mvp/index.html) | Maqueta navegable inicial (anterior a la implementación) |
| [`CLAUDE.md`](CLAUDE.md) | Convenciones para quien desarrolle |

## Pruebas

```bash
# Dentro del contenedor (o con odoo-bin local), sobre una base SIN datos de negocio:
odoo -c /etc/odoo/odoo.conf -d <base_de_prueba> -u spa_all --test-tags /spa_all --stop-after-init
```

Suite completa: ver [`docs/14`](docs/14-despliegue-docker-easypanel.md#pruebas). Las pruebas asumen una base nueva: no las ejecute sobre la base de producción.

## Licencia

Módulos propios: LGPL-3. Módulos OCA en `third_party/oca`: AGPL-3.0.
