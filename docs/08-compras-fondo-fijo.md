# 08 · Compras, retenciones y fondo fijo

## Flujo de compras
```
Solicitud ──► Aprobación por monto ──► Orden de compra ──► Recepción ──► Documento del proveedor ──► Pago
 (comprador)   (umbral configurable)    (purchase)          (stock)      (con o sin factura)
```
- Umbrales de aprobación por monto y por categoría (p. ej. > Bs 1.000 aprueba Gerente). Base: `purchase` CE (doble validación por monto de la compañía) + extensión si se requieren varios niveles.
- **Usuarios designados**: solo el grupo *Comprador* crea órdenes; solo *Custodio* registra gastos de su fondo; solo *Contador* valida documentos fiscales.

## Compras CON factura → crédito fiscal
No llevan retención. Generan **Crédito Fiscal IVA (1141)** y van al Libro de Compras.

### Datos obligatorios según tipo de documento
| Tipo (`l10n_bo_doc_type`) | Campos | Clave única |
|---|---|---|
| `siat_online` (electrónica, computarizada en línea, portal web) | NIT emisor, número, **CUF** | NIT + número + CUF |
| `dosificacion` (computarizada antigua) | NIT emisor, número, **nº de autorización**, **código de control** | NIT + número + autorización |
| `manual` | NIT emisor, número, nº de autorización | NIT + número + autorización |

- Para facturas con CUF, el campo "número de autorización" del Libro de Compras se exporta con valor **1** (práctica reportada por fuentes secundarias; **verificar formato vigente del SIN**).
- **Unicidad**: índice único parcial en base de datos (ver `docs/02`). Si se intenta registrar una factura repetida, **se bloquea** con mensaje indicando el documento existente. No es una advertencia.
- **Lector QR**: desde el celular/escáner, el QR llena NIT, número, autorización/CUF, fecha y monto. El formato del QR de facturas SIAT en línea **debe verificarse con facturas reales**.
- **Validación del CUF**: replicar la verificación (módulo 11 y coincidencia del NIT embebido) que hace el módulo de terceros `l10n_bo_siat_inbound` (licencia propietaria; decidir comprar o desarrollar).

## Compras SIN factura → retenciones
Porcentajes (configurables, **validar con el contador**):
| Concepto | IUE | IT | Total | Otro |
|---|---|---|---|---|
| Bienes (persona natural eventual) | 5 % | 3 % | 8 % | — |
| Servicios / oficios | 12,5 % | 3 % | 15,5 % | — |
| Alquileres | — | 3 % | — | RC-IVA 13 % (**no incluido en `l10n_bo`**, se agrega en `l10n_bo_spa`) |

### Dos modos
**A. El proveedor asume** (recibe el neto). `l10n_bo` 19 **no trae** estos impuestos → `l10n_bo_spa` agrega impuestos negativos:
- `Ret. IUE servicios −12,5 %` → 2138, `Ret. IT −3 %` → 2137 (idem bienes 5 %/3 %).

Ejemplo servicio Bs 1.000:
| Cuenta | Debe | Haber |
|---|---|---|
| 53xxx Gasto servicios | 1.000,00 | |
| 2121 Proveedor / 1112x Fondo fijo | | 845,00 |
| 2138 Retenciones IUE por pagar | | 125,00 |
| 2137 Retenciones IT por pagar | | 30,00 |

**B. La empresa asume (grossing-up)**: es lo que **ya trae `l10n_bo` 19** (grupos "8 % Whh. IT+IUE goods gross-up" y "15,5 % Whh. IT+IUE services gross-up"). Base 1.000 → tasas 14,7929 % IUE y 3,5503 % IT sobre el neto (equivalen a 12,5 % y 3 % sobre 1.183,43). Las líneas de gasto van a **52093 Retenciones IUE** y **52092 Retenciones IT**.

| Cuenta | Debe | Haber |
|---|---|---|
| 53xxx Gasto servicios | 1.000,00 | |
| 52093 Retenciones IUE (gasto) | 147,93 | |
| 52092 Retenciones IT (gasto) | 35,50 | |
| 2121 Proveedor / Fondo fijo | | 1.000,00 |
| 2138 Retenciones IUE por pagar | | 147,93 |
| 2137 Retenciones IT por pagar | | 35,50 |

> Una fuente secundaria cita jurisprudencia del TSJ que considera **no deducibles** las retenciones asumidas. Propuesta: en `l10n_bo_spa` redirigir esas líneas a **5604 Gastos no deducibles – Retenciones asumidas** o marcar 52092/52093 para la conciliación tributaria del IUE. **Decisión del contador.**

**C. Sin factura y sin retención** (casos que la norma exime o compras no respaldadas): todo el gasto a **5605 Gastos no deducibles – Sin respaldo**. Se registra siempre.

> **No se implementa** ningún mecanismo de cuentas bancarias o cajas fuera de la contabilidad. Toda compra se registra; lo no deducible se separa en sus cuentas y se ajusta en la conciliación tributaria del IUE.

## Fondo fijo (caja chica)
Sistema de **fondo fijo puro (imprest)**: la cuenta del fondo siempre muestra el monto asignado.

### Configuración (`l10n_bo.petty.cash.fund`)
- Subcuenta de **1112 Fondo fijo** por fondo: `11121 Fondo fijo – Cocina`, `11122 Fondo fijo – Mantenimiento`…
- Custodio designado, monto fijo, tope por gasto, categorías permitidas, área analítica.

### Ciclo
| Paso | Quién | Asiento |
|---|---|---|
| Creación | Gerente | Debe 1112x / Haber Banco |
| Gastos del período | Custodio (app/portal móvil, foto del comprobante) | **Ninguno** (vouchers en borrador) |
| Rendición | Custodio | Ninguno; se adjunta arqueo |
| Validación | Contador | Revisa documentos (unicidad y datos fiscales como compras con factura; retención si es sin factura) |
| **Reposición** | Contador / Tesorería | **Un asiento**: Debe gastos (+ 1141 Crédito Fiscal) / Haber 2137-2138 retenciones / Haber **Banco** por el neto repuesto |
| Arqueo con diferencia | Contador | Faltante → 1122 Otras cuentas por cobrar (custodio); sobrante → 4304 Otros ingresos |
| Cambio de monto | Gerente | Debe/Haber 1112x contra Banco |

**Regla**: efectivo + comprobantes pendientes = monto fijo. El sistema lo calcula en la rendición.

### Por qué no un diario de caja con saldo variable
Odoo permite modelar la caja chica como diario de efectivo con movimientos individuales; es válido, pero el fondo fluctúa y mezcla gastos no validados con la contabilidad. El modelo imprest mantiene la contabilidad limpia hasta que el contador valida.
