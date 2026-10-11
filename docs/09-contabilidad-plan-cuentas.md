# 09 · Contabilidad y plan de cuentas

## Punto de partida: `l10n_bo` en Odoo 19 (verificado)
Revisado en `odoo/odoo` rama `19.0`, carpeta `addons/l10n_bo`, el 11-oct-2026:

- Versión del módulo **2.0**, autor "Odoo / Cubic ERP", licencia LGPL-3.
- **127 cuentas**, 43 grupos, 99 filas de impuestos, 9 grupos de impuestos, 3 posiciones fiscales.
- Código de 6 dígitos; prefijos de caja `11110`, bancos `11130`.
- Contabilidad anglosajona activada por defecto.
- Impuestos: IVA 13 % (ventas/compras, incluidos en precio), IVA 0 %/exento/no sujeto, IT 3 % (venta, con línea de gasto), **retenciones por bienes 8 % y por servicios 15,5 % en modo grossing-up**.
- El PR #196344 (versión 18, 661 cuentas) figura cerrado y **su contenido no está en la rama 19.0**.

**Decisión**: usar `l10n_bo` como base y **agregar** cuentas en `l10n_bo_spa`; no reemplazar el plan.

## Cuentas existentes que usaremos
| Código | Cuenta | Uso en este sistema |
|---|---|---|
| 1112 | Fondo fijo | Padre de subcuentas por fondo |
| 1121 / 11211 | Cuentas por cobrar comerciales / PoS | Socios, cargos a cuenta |
| 1122 | Otras cuentas por cobrar | Faltantes de arqueo |
| 1124 | Anticipo a proveedores | |
| 1131 / 1133 | Inventarios | Restaurante, insumos |
| 1141 | Crédito Fiscal IVA | Compras con factura |
| 1235 / 1233 | Muebles y enseres / Maquinaria | Equipos de piscina, sauna, cocina |
| 2121 | Cuentas por pagar comerciales | Proveedores |
| 2132 / 2133 / 2134 | Sueldos / Beneficios sociales / Cargos sociales por pagar | Personal |
| 2135 | Débito Fiscal IVA | Ventas |
| 2136 | IT por pagar | Ventas |
| 2137 / 2138 | Retenciones IT / IUE por pagar | Compras sin factura |
| **215** | **Ingresos diferidos** | Membresías cobradas por adelantado |
| 223 | Provisión para indemnizaciones | |
| 3101 · 3201 · 331 · 332 | Capital · Reserva legal · Resultados acumulados · Resultado de la gestión | |
| 4101 | Ventas | Padre de ingresos por línea |
| 4304 | Otros ingresos | Penalidades, sobrantes de caja |
| 5101 | Costos de productos | Costo de ventas del restaurante |
| 52091 | Impuesto a las Transacciones (gasto) | |
| 52092 / 52093 | Retenciones IT / IUE (gasto) | Grossing-up |
| 53001–53016 | Gastos de administración (sueldos, beneficios, aguinaldo, indemnizaciones, servicios básicos, materiales, mantenimiento, depreciación, alquileres, seguros, seguridad…) | Operación |
| 5404 | Comisiones bancarias | QR / tarjetas |
| 570 | IUE | |

## Cuentas a agregar (`l10n_bo_spa`) — propuesta
| Código | Cuenta | Motivo |
|---|---|---|
| 11121, 11122… | Fondo fijo – [Cocina / Mantenimiento / Recepción] | Un fondo por custodio |
| 11140 | Cobros QR por validar | Pagos informados aún no confirmados en banco (opcional) |
| 21391 | Retenciones RC-IVA por pagar | Alquileres sin factura |
| 2161 | Anticipos y saldos a favor de socios | Pagos adelantados sin factura emitida |
| 41011 | Ingresos por membresías | Devengo mensual desde 215 |
| 41012 | Ingresos por entradas y servicios sueltos | |
| 41013 | Ingresos por masajes y terapias | |
| 41014 | Ingresos por tarifas de invitados | |
| 41015 | Ventas restaurante | |
| 41016 | Ventas cafetería | |
| 41017 | Alquiler de ambientes y actividades | Fase posterior |
| 5604 | Gastos no deducibles – Retenciones asumidas | Grossing-up (si el contador lo confirma) |
| 5605 | Gastos no deducibles – Sin respaldo | Compras sin factura ni retención |
| 5606 | Gastos no deducibles – Otros | Multas, etc. |

> El detalle de servicios básicos (luz, agua, gas) puede quedar en **53007** y separarse por **analítica**, o abrirse en subcuentas 530071 Luz / 530072 Agua / 530073 Gas si el contador prefiere verlo en el balance. Recomendación: subcuentas, porque son los costos fijos que más se querrán seguir.

## Observación sobre la configuración de `l10n_bo`
El módulo asigna las **diferencias de caja** a 4301/5601 ("Ajuste por inflación y tenencia de bienes"). Para este negocio se recomienda reasignarlas a **4304 Otros ingresos / 5603 Otros gastos** al configurar la compañía. Confirmar con el contador.

## Contabilidad analítica (rentabilidad por área)
Plan analítico **"Áreas"**:
- Piscina · Sauna/Jacuzzi · Spa/Masajes · Restaurante · Cafetería · Administración (centro de apoyo).

Reglas:
1. Toda venta y todo gasto directo lleva su área (por producto, por espacio o por fondo fijo).
2. Los costos compartidos (luz, agua, gas, sueldos de recepción, alquiler del local) se registran en **Administración** y se **prorratean** mensualmente con claves configurables: m², horas de operación, consumo medido, % fijo.
3. Implementación del prorrateo: asiento analítico mensual generado por `spa_reports` (Odoo CE no tiene distribución automática de costos indirectos entre cuentas analíticas con claves variables; **verificar** si algún módulo OCA 19.0 lo cubre).

## Asientos tipo
**Venta de membresía anual Bs 6.000 con factura** (IVA incluido; IT 3 %):
| Cuenta | Debe | Haber |
|---|---|---|
| 1121 Cuentas por cobrar | 6.000,00 | |
| 2135 Débito Fiscal IVA (6.000 × 13 %) | | 780,00 |
| 215 Ingresos diferidos | | 5.220,00 |
| 52091 IT (gasto) | 180,00 | |
| 2136 IT por pagar | | 180,00 |

Mensual (× 12): Debe 215 435,00 / Haber 41011 435,00.

> Cálculos ilustrativos con IVA incluido en precio (como lo configura `l10n_bo`). **El devengo fiscal del IVA/IT en cobros anticipados debe confirmarlo el contador.**

## Personal
- Empleados, contratos y turnos con `hr` (CE). Asistencia con `hr_attendance`.
- **Planilla de sueldos boliviana** (aportes a gestora, CNS, aguinaldo, RC-IVA dependientes): **Odoo CE 19 no incluye nómina** (`hr_payroll` es Enterprise). Opciones: módulo de nómina OCA (verificar disponibilidad para 19.0 y adaptación a Bolivia) o registrar el asiento de planilla mensual desde la planilla externa. Ver `docs/13`.

## Validación obligatoria
Este plan es una **propuesta técnica**. Antes de cargar datos reales debe revisarlo un **contador boliviano**, en especial: devengo de IVA/IT, tratamiento de retenciones asumidas, venta sin factura, aportes sociales y reexpresión/ajuste por inflación.
