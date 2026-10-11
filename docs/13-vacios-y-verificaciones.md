# 13 · Vacíos y verificaciones

Registro honesto de qué está verificado y qué no. **Actualizar este archivo al resolver cada punto.**

## ✅ Verificado (11-oct-2026)
| Hecho | Cómo se verificó |
|---|---|
| `membership`, `appointment`, `website_appointment`, `sale_subscription`, `whatsapp`, `account_accountant`, `account_reports`, `hr_payroll`, `pos_preparation_display` **no** existen en Odoo CE 19 | Listado de `addons/` en rama `19.0` de `github.com/odoo/odoo` |
| `l10n_bo`, `pos_restaurant`, `pos_self_order`, `hr_expense`, `crm`, `website_sale`, `loyalty`, `event`, `resource`, `calendar`, `purchase`, `stock`, `mrp`, `payment_custom` **sí** existen en CE 19 | Mismo listado |
| `l10n_bo` v2.0: 127 cuentas, retenciones 8 %/15,5 % en grossing-up, cuentas 1112, 1141, 2137, 2138, 215 | Lectura de los CSV del módulo |
| OCA 19.0 tiene `membership`, `membership_variable_period`, `contract`, `subscription_oca`, `resource_booking` | Listado de ramas 19.0 de los repos OCA |
| No existe repo `OCA/l10n-bolivia` | `git ls-remote` sin resultado |

## ⚠️ Por verificar — técnico
1. Calidad y completitud de la migración a 19.0 de `resource_booking`, `contract`, `subscription_oca` y `membership` OCA.
2. Pantalla de cocina: el módulo `pos_preparation_display` no está en CE 19; verificar qué ofrece `pos_restaurant` estándar (impresión de comandas por impresora de cocina) y si hay alternativa OCA.
3. Existencia en OCA 19.0 de: distribución de costos analíticos con claves, nómina, aprobación multinivel de compras.
4. Requisitos oficiales de Odoo 19 (versión de Python y PostgreSQL).
5. Formato exacto del QR de facturas SIAT en línea (probar con facturas reales).
6. Si el SIN ofrece un servicio automatizable para verificar facturas de compra desde un sistema externo.

## ⚠️ Por verificar — fiscal / legal (contador boliviano)
1. Porcentajes vigentes de retención (bienes 8 %, servicios 15,5 %, alquileres RC-IVA 13 % + IT 3 %). Fuente usada: boliviaimpuestos.com (secundaria).
2. Deducibilidad de retenciones asumidas (grossing-up). Fuente secundaria cita jurisprudencia del TSJ.
3. Casos en que se permite **vender sin factura** y cómo se registran (IT, ingresos).
4. Devengo de IVA e IT en membresías cobradas por adelantado.
5. Campos y formato vigentes del **Registro/Libro de Compras** en el SIAT (tipo de compra, uso del "1" en número de autorización para CUF).
6. Aportes sociales del empleador y planilla.
7. Ajuste por inflación / reexpresión de estados financieros.

## ⚠️ Por decidir — negocio / proveedores
1. Proveedor de facturación SIAT (certificación, costo por factura, contingencias, API).
2. Proveedor de QR con notificación de pago.
3. WhatsApp: número para API oficial y proveedor (Meta directo u otro). Evolution API: confirmar riesgos antes de cualquier uso productivo.
4. Comprar o replicar la validación de CUF de `l10n_bo_siat_inbound` (licencia propietaria de Odoo).
5. Hosting (VPS propio, Odoo.sh no aplica a CE con módulos propios sin plan pago — **verificar**).

## ❌ Descartado por diseño
- Cuentas bancarias o cajas no registradas en la contabilidad para compras sin factura: es contabilidad paralela y defraudación tributaria. Se reemplaza por retenciones o gastos no deducibles registrados.
