# 01 · Arquitectura de módulos

## Base estándar (Odoo Community 19)
Verificado en la rama `19.0` de `odoo/odoo` el 11-oct-2026.

| Módulo | Uso |
|---|---|
| `base`, `mail`, `contacts` | Socios como `res.partner`, chatter, actividades |
| `website`, `portal` | Web pública y portal del socio |
| `website_sale` | Compra de planes desde la web (carrito → pago) |
| `crm`, `website_crm` | Embudo de prospectos, formulario web → lead |
| `sale`, `sale_management` | Órdenes de venta de planes y servicios |
| `account`, `l10n_bo` | Contabilidad y localización boliviana |
| `account_payment`, `payment_custom` | Pagos online; `payment_custom` sirve para "QR / transferencia" con validación manual |
| `point_of_sale`, `pos_restaurant` | Restaurante, cafetería, mesas, comandas a cocina |
| `purchase`, `stock` | Compras e inventario |
| `hr`, `hr_attendance`, `hr_expense` | Personal, asistencia, gastos (base para rendiciones) |
| `resource`, `calendar` | Calendarios de trabajo y horarios |
| `loyalty`, `sale_loyalty` | Cupones, códigos promocionales, tarjetas regalo |
| `analytic` | Centros de costo por área |
| `sms`, `mass_mailing` | Comunicaciones (opcional) |

## Módulos OCA candidatos (rama 19.0 existente)
| Repositorio | Módulo | Decisión |
|---|---|---|
| `OCA/calendar` | `resource_booking` | **Evaluar en fase 0** para masajes (recurso 1:1 con portal de reserva). Probablemente insuficiente para aforo compartido (15 personas en piscina) → por eso `spa_booking` propio |
| `OCA/contract` | `contract`, `subscription_oca` | **Evaluar** como motor de facturación recurrente. Alternativa: facturación propia en `spa_billing` |
| `OCA/vertical-association` | `membership`, `membership_variable_period` | Modelo de membresía clásico (estado de socio). **No cubre derechos/saldos**; se puede usar solo para el estado "socio activo" o no usarlo |

> La existencia del módulo en la rama 19.0 se verificó; **su calidad y estado de migración no**. Ver `docs/13`.

## Módulos propios

```
                     ┌──────────────┐
                     │  spa_base    │  espacios · servicios · config
                     └──────┬───────┘
          ┌─────────────────┼────────────────────┐
   ┌──────▼──────┐   ┌──────▼───────┐     ┌──────▼──────┐
   │ spa_booking │◄──┤spa_membership│     │  spa_crm    │
   └──────┬──────┘   └──────┬───────┘     └──────▲──────┘
          │                 │                    │
   ┌──────▼──────┐   ┌──────▼───────┐            │ invitados/cortesías
   │ spa_access  │   │ spa_billing  ├────────────┘
   └─────────────┘   └──────┬───────┘
                            │
   ┌─────────────┐   ┌──────▼───────┐   ┌───────────────┐
   │ spa_portal  │   │spa_messaging │   │   spa_pos     │
   └─────────────┘   └──────────────┘   └───────────────┘

   Fiscal Bolivia:  l10n_bo_spa · l10n_bo_purchase · l10n_bo_petty_cash · l10n_bo_siat_edi
   Reportes:        spa_reports
```

| Módulo | Depende de | Responsabilidad |
|---|---|---|
| `spa_base` | `base`, `mail`, `hr`, `resource`, `product`, `analytic` | Espacios (`spa.space`), servicios (`spa.service`), especialidades del personal, configuración general |
| `spa_booking` | `spa_base`, `calendar` | Franjas, reservas, cálculo de disponibilidad (aforo ∩ personal), lista de espera |
| `spa_membership` | `spa_base`, `sale` | Planes, líneas de derechos, membresías de socios, libro de consumos, cupos de invitados, políticas de cancelación |
| `spa_access` | `spa_booking`, `spa_membership` | Credencial QR del socio, check-in/out, ocupación en vivo para espacios de modo libre |
| `spa_billing` | `spa_membership`, `account`, `account_payment` | Renovaciones, avisos, días de gracia, suspensión, ofertas de pago (cuotas, descuentos por período) |
| `spa_crm` | `crm`, `spa_membership` | Fuentes configurables, etapas, alta automática de invitados/cortesías como leads, campañas |
| `spa_portal` | `website`, `portal`, `website_sale`, `spa_booking`, `spa_billing` | Web del socio: planes, registro, reservas, saldo, invitados, pagos |
| `spa_messaging` | `mail` | Capa de mensajería con proveedores: `wa_link` (wa.me), `meta_cloud_api`, `evolution` (solo pruebas) |
| `spa_pos` | `pos_restaurant`, `spa_membership` | Identificar socio en comanda, cargo a cuenta, descuentos por plan y categoría |
| `spa_reports` | todos | Tableros: ocupación, uso por plan, MRR, mora, conversión CRM, rentabilidad por área |
| `l10n_bo_spa` | `l10n_bo`, `analytic` | Cuentas adicionales (no deducibles, subcuentas de fondo fijo, ingresos por línea), impuesto RC-IVA alquileres, plan analítico por área |
| `l10n_bo_purchase` | `l10n_bo`, `purchase` | Tipo de documento fiscal, CUF / autorización / código de control, restricción de unicidad, lector QR, Libro de Compras |
| `l10n_bo_petty_cash` | `l10n_bo`, `hr_expense` o `account` | Fondos fijos por custodio, rendición, arqueo, reposición en un asiento |
| `l10n_bo_siat_edi` | `account`, `point_of_sale` | Emisión de facturas vía API de un proveedor certificado SIAT; opción "sin factura" |

## Por qué módulos propios para membresías y reservas
Las reglas acordadas (derechos por línea con cantidad, período, tope de frecuencia, horario permitido, invitados por servicio, saldo que se pierde/acumula/traslada, políticas de cancelación y no-show por plan) **no las cubre ningún módulo Community ni OCA verificado**. Construirlas sobre `sale` + `account` da control total y evita depender de módulos Enterprise.
