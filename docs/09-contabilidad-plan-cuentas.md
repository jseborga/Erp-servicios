# 09 · Contabilidad y plan de cuentas

Implementado en el módulo [`addons/l10n_bo_spa`](../addons/l10n_bo_spa). Instalado y probado sobre Odoo 19.0 Community el 11-oct-2026 (9 pruebas automáticas, ver más abajo).

> **Validación obligatoria.** Es una propuesta técnica. Antes de operar con datos reales, un contador boliviano debe revisar las cuentas, las tasas de retención, el tratamiento de los gastos no deducibles y los porcentajes de reparto.

## 1. Principios de diseño

1. **Se construye sobre `l10n_bo`, no se reemplaza.** El plan oficial (127 cuentas) sigue siendo la base; el módulo agrega 62 cuentas. Así se conservan los impuestos, el reporte tributario y las actualizaciones de Odoo.
2. **La cuenta dice QUÉ es; la analítica dice DÓNDE.** Las cuentas se abren por naturaleza (electricidad, químicos, membresías). El área (piscina, spa, restaurante…) se registra en el plan analítico "Áreas del negocio". Así un mismo gasto se puede repartir entre áreas sin duplicar cuentas.
3. **Costos directos separados del gasto administrativo.** Los costos de operar los servicios usan el tipo de Odoo "Costo directo", para ver el margen bruto por área.
4. **Cada producto ya sabe a qué cuenta va.** Las categorías de producto traen sus cuentas de ingreso, gasto e inventario. El personal no elige cuentas al vender o comprar.
5. **Nada fuera de libros.** Lo no deducible tiene sus cuentas (56xx); no se oculta.

## 2. Códigos de 6 dígitos

`l10n_bo` define `code_digits = 6`: Odoo completa cada código con ceros a la derecha. La cuenta "1141 Crédito Fiscal IVA" aparece como **114100**, y "1237" como **123700**. Las tablas usan los códigos tal como se ven en Odoo.

## 3. Cuentas agregadas por el módulo

| Código | Cuenta | Tipo Odoo |
|---|---|---|
| 111210 | Fondo fijo – Recepción | Banco y caja |
| 111220 | Fondo fijo – Cocina y restaurante | Banco y caja |
| 111230 | Fondo fijo – Mantenimiento | Banco y caja |
| 111500 | Fondos en tránsito (QR, tarjetas, transferencias) | Activo corriente |
| 112210 | Cuentas por cobrar al personal (faltantes y anticipos) | Por cobrar |
| 113110 | Inventario – Productos para la venta | Activo corriente |
| 113310 | Inventario – Alimentos y bebidas | Activo corriente |
| 113320 | Inventario – Insumos de spa y masajes | Activo corriente |
| 113330 | Inventario – Químicos de piscina | Activo corriente |
| 113340 | Inventario – Amenities y artículos de limpieza | Activo corriente |
| 123700 | Equipos de piscina, sauna y jacuzzi | Activo fijo |
| 123710 | Depreciación acumulada equipos de piscina, sauna y jacuzzi | Activo fijo |
| 123800 | Equipos de cocina y restaurante | Activo fijo |
| 123810 | Depreciación acumulada equipos de cocina y restaurante | Activo fijo |
| 123900 | Instalaciones y mejoras en inmueble | Activo fijo |
| 123910 | Depreciación acumulada instalaciones y mejoras | Activo fijo |
| 213910 | Retenciones RC-IVA por pagar | Pasivo corriente |
| 213920 | IUE por pagar | Pasivo corriente |
| 215100 | Ingresos diferidos – Membresías | Pasivo corriente |
| 215200 | Ingresos diferidos – Paquetes y sesiones prepagadas | Pasivo corriente |
| 215300 | Tarjetas regalo y vales por canjear | Pasivo corriente |
| 216100 | Anticipos de clientes y saldos a favor de socios | Pasivo corriente |
| 216200 | Garantías recibidas por alquiler de ambientes | Pasivo corriente |
| 410110 | Ingresos – Membresías | Ingreso |
| 410120 | Ingresos – Entradas y pases diarios | Ingreso |
| 410130 | Ingresos – Masajes y terapias | Ingreso |
| 410140 | Ingresos – Tarifas de invitados | Ingreso |
| 410150 | Ingresos – Alimentos y bebidas | Ingreso |
| 410160 | Ingresos – Alquiler de ambientes y eventos | Ingreso |
| 410170 | Ingresos – Clases y actividades | Ingreso |
| 410180 | Ingresos – Venta de productos | Ingreso |
| 410190 | Ingresos – Penalidades por cancelación tardía y no-show | Ingreso |
| 410210 | Descuentos y promociones otorgados | Ingreso |
| 430410 | Sobrantes de caja | Otro ingreso |
| 510110 | Costo de alimentos y bebidas vendidos | Costo directo |
| 510120 | Costo de productos vendidos | Costo directo |
| 511100 | Personal operativo – Sueldos y salarios | Costo directo |
| 511200 | Personal operativo – Cargas sociales patronales | Costo directo |
| 511300 | Personal operativo – Provisión aguinaldo | Costo directo |
| 511400 | Personal operativo – Provisión indemnizaciones | Costo directo |
| 511500 | Honorarios de terapeutas e instructores independientes | Costo directo |
| 511600 | Químicos y tratamiento de agua | Costo directo |
| 511700 | Insumos de spa y masajes | Costo directo |
| 511800 | Amenities, lencería y limpieza | Costo directo |
| 511900 | Lavandería | Costo directo |
| 512100 | Electricidad | Costo directo |
| 512200 | Agua potable y alcantarillado | Costo directo |
| 512300 | Gas (calentamiento y cocina) | Costo directo |
| 512400 | Mantenimiento de equipos de piscina, sauna y jacuzzi | Costo directo |
| 512500 | Depreciación de equipos operativos | Depreciación |
| 520610 | Publicidad digital y redes sociales | Gasto |
| 520620 | Cortesías y degustaciones promocionales | Gasto |
| 520940 | Retenciones RC-IVA asumidas | Gasto |
| 530170 | Honorarios profesionales (contables y legales) | Gasto |
| 530180 | Software, licencias y facturación electrónica | Gasto |
| 530190 | Patentes, tasas municipales y otros tributos | Gasto |
| 530200 | Internet y telefonía | Gasto |
| 540410 | Comisiones por cobros QR y tarjetas | Gasto |
| 560400 | Gastos no deducibles – Retenciones asumidas | Gasto |
| 560500 | Gastos no deducibles – Sin respaldo de factura | Gasto |
| 560600 | Multas, recargos e intereses tributarios | Gasto |
| 560700 | Faltantes de caja | Gasto |

Cuentas de `l10n_bo` que el diseño usa directamente: 112100 Cuentas por cobrar (socios), 114100 Crédito Fiscal IVA, 212100 Proveedores, 213500 Débito Fiscal IVA, 213600 IT por pagar, 213700 Retenciones IT por pagar, 213800 Retenciones IUE por pagar, 520910 IT (gasto), 520920/520930 Retenciones IT/IUE asumidas, 530010–530160 Gastos de administración, 570000 IUE.

**Servicios básicos:** se registran en 512100 Electricidad, 512200 Agua y 512300 Gas, y no en 530070 Servicios básicos de `l10n_bo`. En un spa con piscina son costo de operación. La parte de oficina se separa con la analítica (área Administración).

## 4. Correcciones a `l10n_bo` 19.0 encontradas en las pruebas

Al registrar facturas de prueba con los impuestos oficiales aparecieron dos problemas. El módulo los corrige, pero solo en impuestos que aún no tienen movimientos.

| Problema en `l10n_bo` | Efecto | Corrección en `l10n_bo_spa` |
|---|---|---|
| Retenciones *grossing-up* (8 % bienes, 15,5 % servicios) con signos invertidos | La factura **debitaba** 213700/213800 (pasivo) y **acreditaba** 520920/520930 (gasto). Es el asiento al revés. | Se invierten los signos: debita el gasto y acredita la retención por pagar. Probado: Bs 1.000 → Dr 520930 147,93 / Dr 520920 35,50 / Cr 213800 147,93 / Cr 213700 35,50 / Cr proveedor 1.000. |
| IVA de compras con el criterio por defecto de la compañía (precio sin impuesto) | Una factura de Bs 1.130 daba crédito fiscal de 168,85 (13/87), cuando en Bolivia es el 13 % del importe facturado: 146,90. | IVA de compras con **precio IVA incluido**. Probado: Bs 1.130 → gasto 983,10 + crédito fiscal 146,90. |
| IVA de compras y de ventas en la misma cuenta 213500 | El saldo de crédito fiscal no se ve por separado. | El IVA de compras va a **114100 Crédito Fiscal IVA**; el de ventas sigue en 213500. La compensación mensual se hace con un asiento. |
| Diferencias de caja enviadas a 430100/560100 "Ajuste por inflación y tenencia de bienes" | Mezcla faltantes de caja con la reexpresión monetaria. | Diferencias de caja a **430410 Sobrantes de caja** y **560700 Faltantes de caja**. |

> Estas observaciones se basan en el comportamiento probado en Odoo, no en una norma. Conviene reportarlas a Odoo (proyecto `odoo/odoo`, módulo `l10n_bo`) y que el contador confirme el criterio.

## 5. Retenciones en compras sin factura

| Impuesto en Odoo | Cuándo | Asiento (Bs 1.000) |
|---|---|---|
| **Ret. 8% bienes** | Compra de bienes a persona natural sin factura; retiene IUE 5 % + IT 3 % | Proveedor recibe 920 · Cr 213800 50 · Cr 213700 30 |
| **Ret. 15.5% servicios prof.** | Profesión liberal u oficio sin factura; IUE 12,5 % + IT 3 % | Proveedor recibe 845 · Cr 213800 125 · Cr 213700 30 |
| **Ret. 16% eventuales/alquiler** | Servicio eventual de persona no registrada, alquiler eventual, intereses; RC-IVA 13 % + IT 3 % | Proveedor recibe 840 · Cr 213910 130 · Cr 213700 30 |
| 8 % / 15,5 % Whh. *gross-up* (de `l10n_bo`) y **16% gross-up eventuales/alquiler** | La empresa asume la retención | Proveedor recibe 1.000; el gasto por la retención va a 520920/520930/520940 |

**Importante (corrige lo dicho antes en esta conversación):** las *Preguntas frecuentes de retenciones* del SIN indican que, para un servicio eventual prestado por una persona natural **no registrada**, se retiene **RC-IVA 13 % + IT 3 %**. Ejemplos citados: conexión eléctrica, reparación de maquinaria y seguridad eventual. El IUE no figura como retención para servicios en ese documento. Por eso el módulo trae **las dos** retenciones de servicios: el contador decide en cada caso cuál aplica (15,5 % o 16 %).

Las retenciones asumidas (*grossing-up*) quedan en 520920, 520930 y 520940. Si el contador las considera no deducibles, se reclasifican a 560400 o se ajustan en la conciliación del IUE.

## 6. Plan analítico "Áreas del negocio"

Áreas: Piscina (PIS), Sauna y jacuzzi (SAJ), Spa y masajes (SPA), Restaurante (RES), Cafetería (CAF), Eventos, clases y alquileres (EVE), Administración y servicios generales (ADM).

- **Obligatoria en facturas de proveedor** para cuentas 51, 52 y 53: Odoo no deja validar una factura de gasto sin área. Probado.
- **Modelos de reparto automático** (Contabilidad → Configuración → Modelos de distribución analítica). Los porcentajes son **ilustrativos** y deben reemplazarse con mediciones reales (kWh por medidor, m³, m², horas de uso).

| Prefijo de cuenta | Reparto por defecto |
|---|---|
| 512100 Electricidad | PIS 35 · SAJ 30 · SPA 5 · RES 15 · CAF 5 · ADM 10 |
| 512200 Agua | PIS 45 · SAJ 15 · SPA 5 · RES 15 · CAF 5 · ADM 15 |
| 512300 Gas | PIS 50 · SAJ 30 · RES 15 · CAF 5 |
| 511600 Químicos | PIS 80 · SAJ 20 |
| 512400 Mantenimiento equipos | PIS 60 · SAJ 40 |
| 511500 Honorarios terapeutas · 511700 Insumos spa | SPA 100 |
| 530120 Alquileres | PIS 40 · SAJ 15 · SPA 10 · RES 20 · CAF 5 · ADM 10 |
| Resto de 52 y 53 | ADM 100 |

**Estado de resultados por área (en Odoo Community):** Contabilidad → Analítica → Apuntes analíticos, vista pivote: filas = "Áreas del negocio", columnas = cuenta financiera. Los montos ya vienen prorrateados (probado: una factura de luz de Bs 983,10 netos se reparte 344,08 / 294,92 / 147,47 / 98,31 / 49,16 / 49,16).

## 7. Categorías de producto

| Categoría | Ingreso | Gasto / costo | Inventario |
|---|---|---|---|
| Spa / Membresías mensuales | 410110 | — | — |
| Spa / Membresías trimestrales y anuales (diferidas) | **215100** (pasivo) | — | — |
| Spa / Entradas y pases diarios | 410120 | — | — |
| Spa / Masajes y terapias | 410130 | 511500 | — |
| Spa / Paquetes y sesiones prepagadas (diferidas) | **215200** (pasivo) | — | — |
| Spa / Tarifas de invitados | 410140 | — | — |
| Spa / Clases y actividades | 410170 | 511500 | — |
| Spa / Alquiler de ambientes y eventos | 410160 | — | — |
| Spa / Penalidades | 410190 | — | — |
| Restaurante y cafetería / Alimentos y bebidas | 410150 | 510110 | 113310 |
| Tienda / Productos para la venta | 410180 | 510120 | 113110 |
| Insumos de operación / Químicos de piscina | — | 511600 | 113330 |
| Insumos de operación / Insumos de spa y masajes | — | 511700 | 113320 |
| Insumos de operación / Amenities y limpieza | — | 511800 | 113340 |
| Tarjetas regalo y vales | **215300** (pasivo) | — | — |
| Descuentos y promociones | 410210 | — | — |

Las cuentas de inventario se aplican solo si se instala Inventario con valoración automática.

**Ingresos diferidos.** Odoo Community no tiene diferimiento automático de ingresos (es función de Enterprise). Los planes trimestrales y anuales se facturan a 215100. Cada mes se pasa la porción del mes a 410110 con un asiento en el diario **DIFE**. El módulo `spa_billing` (fase 1) lo automatizará.

## 8. Diarios agregados

| Código | Diario | Uso |
|---|---|---|
| FFIJ | Fondos fijos | Creación, rendición y reposición de cajas chicas |
| DIFE | Ingresos diferidos | Devengo mensual de membresías y paquetes |
| PLAN | Planillas de sueldos | Asiento mensual de planilla (Odoo CE no trae nómina) |
| DEPR | Depreciaciones | Asientos de depreciación (`account_asset_management`) |

## 9. Asientos tipo verificados en Odoo

**Membresía anual de Bs 6.000 con factura** (IVA incluido + IT), facturada a diferidos:

| Cuenta | Debe | Haber |
|---|---|---|
| 112100 Cuentas por cobrar | 6.000,00 | |
| 520910 IT (gasto) | 180,00 | |
| 215100 Ingresos diferidos – Membresías | | 5.220,00 |
| 213500 Débito Fiscal IVA | | 780,00 |
| 213600 IT por pagar | | 180,00 |

Cada mes, en el diario DIFE: Debe 215100 435,00 / Haber 410110 435,00.

> El momento en que nacen el débito fiscal y el IT en cobros anticipados lo debe confirmar el contador.

## 10. Pruebas automáticas

`addons/l10n_bo_spa/tests/test_l10n_bo_spa.py` (se ejecutan con `--test-tags /l10n_bo_spa`):

1. Cuentas y diarios creados con su tipo y código.
2. Cuentas de diferencia de caja.
3. Retención 15,5 % retenida al proveedor (845 / 125 / 30).
4. Retención 16 % RC-IVA + IT (840 / 130 / 30).
5. Signos correctos del *grossing-up* (`l10n_bo` y RC-IVA).
6. IVA de compras incluido y en 114100 (146,90 sobre 1.130).
7. Reparto analítico automático suma 100 %.
8. Analítica obligatoria bloquea la factura sin área.
9. Cuentas de las categorías de producto.

Resultado el 11-oct-2026: **0 fallos, 0 errores de 9 pruebas**.

## 11. Reportes contables disponibles (Community + OCA)

Odoo Community no trae balance general, estado de resultados ni libro mayor imprimibles (son de Enterprise). La imagen Docker incluye módulos OCA para cubrirlo:

- `account_financial_report`: balance de comprobación, libro mayor, libro diario, antigüedad de saldos (PDF y Excel).
- `account_tax_balance`: saldos por impuesto.
- `mis_builder`: estados financieros configurables (resultados, balance, presupuestos).
- `account_asset_management`: activos fijos y depreciación.
- `account_fiscal_year`: gestiones fiscales.

## 12. Pendiente con el contador

1. Confirmar tasas y casos de retención (8 %, 15,5 %, 16 %) y su formulario (410, 570, 604).
2. Deducibilidad de retenciones asumidas (520920–520940) y uso de 560400–560600.
3. Aportes patronales y provisiones laborales (511200–511400 y 530020–530040).
4. Devengo de IVA e IT en cobros anticipados.
5. Reexpresión / ajuste por inflación (430100 / 560100 de `l10n_bo`).
6. Porcentajes reales de reparto analítico.
