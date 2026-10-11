# 05 · Pagos, mora y facturación

## Medios de pago
| Medio | Implementación | Validación |
|---|---|---|
| QR interbancario | Fase 1: QR estático/dinámico mostrado en portal y enviado por WhatsApp; el socio sube comprobante | Manual por caja/recepción |
| QR con conciliación automática | Fase 2: integración con banco o proveedor que notifique el pago (webhook) | Automática — **proveedor a elegir, ver `docs/13`** |
| Transferencia / depósito | `payment_custom` (Odoo CE) con instrucciones + comprobante | Manual |
| Efectivo | Caja de recepción o POS | En el momento |
| Tarjeta | Fase posterior: pasarela que opere en Bolivia | Automática |

En Odoo: cada medio es un diario (`account.journal`) y, en el portal, un `payment.provider`. La validación manual se hace desde una bandeja "Pagos por validar" (comprobante adjunto + botón Validar → `account.payment` conciliado).

## Renovación
- **Sin débito automático.** X días antes del vencimiento (configurable) se genera la factura/orden de renovación y se envía aviso con enlace de pago y QR.
- El pago confirmado extiende la membresía al siguiente período.

## Mora (`spa.dunning.step`)
Ejemplo configurable:
| Día | Acción |
|---|---|
| −5 | Aviso amable de próximo vencimiento |
| 0 | Aviso de vencimiento con QR |
| +3 | Recordatorio (estado `grace`) |
| +5 (fin de gracia) | Suspensión de acceso + aviso |
| +15 | Lead a etapa "En riesgo" y actividad para atención al cliente |

## Ofertas de pago (`spa.payment.offer`)
Configurables con **vigencia** y **condiciones**:
- Descuento por pago anual o trimestral (p. ej. 15 % anual hasta el 31-dic).
- Pago en cuotas (p. ej. anual en 3 cuotas sin recargo).
- Aplicables a planes/períodos específicos y a socios nuevos o renovaciones.

Las cuotas generan `spa.payment.plan`; la mora de una cuota activa la escalera de avisos igual que una renovación.

## Ingresos diferidos (clave contable)
Un plan trimestral o anual cobrado por adelantado **no es ingreso del mes del cobro**:
- Al facturar: Debe Cuentas por cobrar / Haber **215 Ingresos Diferidos** (más IVA débito fiscal e IT según corresponda).
- Cron mensual: Debe 215 / Haber Ingreso por membresías (cuenta del plan, con analítica).

> **A validar con el contador:** el momento de devengo del IVA y del IT en ventas de servicios cobradas por adelantado. La regla tributaria puede diferir del reconocimiento contable del ingreso.

## Facturación
Por venta o por configuración se elige:
- **Factura electrónica en línea (SIAT)** — emitida vía proveedor certificado (módulo `l10n_bo_siat_edi`).
- **Sin factura** — la venta se registra igual (ingreso + IT si corresponde, a confirmar con el contador); no se envía al SIAT.

> **Advertencia legal (honesta):** la emisión de factura en Bolivia, por regla general, es obligatoria en cada venta de un contribuyente del régimen general. La opción "sin factura" debe usarse solo en los casos que la norma permita (p. ej. ventas por debajo del monto mínimo facturable si aplica, o regímenes especiales). **Debe validarse con un contador antes de habilitarla.** El sistema la deja configurable pero con permiso restringido y con registro contable completo.

## Integración SIAT
Odoo CE 19 **no trae** emisión SIAT. Opciones:
1. **Proveedor certificado por API** (recomendado): el módulo envía la venta, recibe CUF, XML/PDF y estado; maneja contingencias (eventos significativos) del proveedor.
2. Desarrollo propio contra los servicios web del SIN: requiere certificación del sistema ante el SIN, firma digital y mantenimiento de catálogos. **No recomendado** para la primera versión.

Ver comparación pendiente en `docs/13`.
