# 13 · Vacíos y verificaciones

Registro honesto de qué está verificado y qué no. **Actualizar este archivo al resolver cada punto.**

## ✅ Verificado (11-oct-2026)
| Hecho | Cómo se verificó |
|---|---|
| `membership`, `appointment`, `website_appointment`, `sale_subscription`, `whatsapp`, `account_accountant`, `account_reports`, `hr_payroll`, `pos_preparation_display` **no** existen en Odoo CE 19 | Listado de `addons/` en rama `19.0` de `github.com/odoo/odoo` |
| `l10n_bo`, `pos_restaurant`, `pos_self_order`, `hr_expense`, `crm`, `website_sale`, `loyalty`, `event`, `resource`, `calendar`, `purchase`, `stock`, `mrp`, `payment_custom`, `auth_totp` **sí** existen en CE 19 | Mismo listado |
| `l10n_bo` v2.0: 127 cuentas, códigos de 6 dígitos, retenciones 8 %/15,5 % en grossing-up | Lectura de los CSV y prueba de instalación |
| **`l10n_bo` 19: grossing-up con signos invertidos e IVA de compras calculado sin incluir** | Facturas de prueba en Odoo 19 (ver `docs/09` §4). Corregido en `l10n_bo_spa` |
| OCA 19.0 tiene `membership`, `contract`, `subscription_oca`, `resource_booking`, `account_financial_report`, `mis_builder`, `account_asset_management`, `account_fiscal_year` | Listado de ramas 19.0 |
| `account_financial_report`, `account_tax_balance`, `mis_builder`, `account_asset_management`, `account_fiscal_year` se instalan junto a `l10n_bo_spa` sin errores | Instalación real en Odoo 19 + PostgreSQL 16 |
| Odoo 19: Python 3.10 a 3.14, PostgreSQL ≥ 13 | `odoo/release.py` (`MIN_PY_VERSION`, `MAX_PY_VERSION`, `MIN_PG_VERSION`) |
| Imagen oficial `odoo:19.0` existe; `odoo:latest` = Odoo 20 | `docker-library/official-images/library/odoo` |
| `l10n_bo_spa`: 9 pruebas automáticas, 0 fallos | `--test-tags /l10n_bo_spa` |
| Script de arranque: crea la base en es_BO/BO, instala módulos una sola vez, actualiza módulos, bloquea el gestor de bases | Ejecución real del script contra Odoo 19 local |
| SIN: servicio eventual de persona no registrada → RC-IVA 13 % + IT 3 % | *Retenciones – Preguntas frecuentes*, impuestos.gob.bo |
| No existe repo `OCA/l10n-bolivia` | `git ls-remote` sin resultado |

## ⚠️ Por verificar — técnico
1. **`docker build` de la imagen**: no se pudo ejecutar en el entorno de trabajo (sin acceso a Docker Hub). El primer despliegue en el servidor es la prueba.
2. Calidad y completitud de la migración a 19.0 de `resource_booking`, `contract`, `subscription_oca` y `membership` OCA.
3. Pantalla de cocina: `pos_preparation_display` no está en CE 19; verificar alternativa (impresora de cocina u OCA).
4. Etiquetas del reporte tributario (`tax_tags`) para las retenciones nuevas de `l10n_bo_spa`: no se asignaron. El reporte tributario de Odoo es de Enterprise; en CE usar `account_tax_balance` y los saldos de 213700/213800/213910.
5. Formato exacto del QR de facturas SIAT en línea (probar con facturas reales).
6. Si el SIN ofrece un servicio automatizable para verificar facturas de compra desde un sistema externo.
7. Existencia en OCA 19.0 de nómina y aprobación multinivel de compras.

## ⚠️ Por verificar — fiscal / legal (contador boliviano)
1. Cuándo aplica cada retención de servicios: 15,5 % (IUE + IT, profesiones u oficios) o 16 % (RC-IVA + IT, servicios eventuales).
2. Deducibilidad de retenciones asumidas (grossing-up). Fuente secundaria cita jurisprudencia del TSJ.
3. Casos en que se permite **vender sin factura** y cómo se registran (IT, ingresos).
4. Devengo de IVA e IT en membresías cobradas por adelantado.
5. Campos y formato vigentes del **Registro/Libro de Compras** en el SIAT.
6. Aportes sociales del empleador y planilla.
7. Ajuste por inflación / reexpresión de estados financieros.
8. Porcentajes reales de reparto analítico (los de `l10n_bo_spa` son ilustrativos).
9. Separar IVA de compras en 114100 (cambio respecto a `l10n_bo`, que usa 213500 para ambos).

## ⚠️ Por decidir — negocio / proveedores
1. Proveedor de facturación SIAT (certificación, costo por factura, contingencias, API).
2. Proveedor de QR con notificación de pago.
3. WhatsApp: número para API oficial y proveedor (Meta directo u otro). Evolution API: confirmar riesgos antes de cualquier uso productivo.
4. Comprar o replicar la validación de CUF de `l10n_bo_siat_inbound` (licencia propietaria de Odoo).
5. Servidor: tamaño definitivo (ver `docs/14`).

## ❌ Descartado por diseño
- Cuentas bancarias o cajas no registradas en la contabilidad para compras sin factura: es contabilidad paralela y defraudación tributaria. Se reemplaza por retenciones o gastos no deducibles registrados.
