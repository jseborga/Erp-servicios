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
Implementado y probado en `l10n_bo_spa`; detalle de cuentas y asientos en [`09`](09-contabilidad-plan-cuentas.md#5-retenciones-en-compras-sin-factura). Tasas configurables, **validar con el contador**.

| Impuesto en Odoo | Caso | Retención |
|---|---|---|
| Ret. 8% bienes | Bienes de persona natural sin factura | IUE 5 % + IT 3 % |
| Ret. 15.5% servicios prof. | Profesión liberal u oficio sin factura | IUE 12,5 % + IT 3 % |
| Ret. 16% eventuales/alquiler | Servicio eventual de persona no registrada, alquiler eventual, intereses | RC-IVA 13 % + IT 3 % |

Las *Preguntas frecuentes de retenciones* del SIN asignan RC-IVA + IT a los servicios eventuales de personas no registradas, por ejemplo conexión eléctrica o reparación de maquinaria. Antes este documento solo contemplaba el 15,5 % para servicios; ahora se dejan las dos opciones para que el contador elija según el caso.

### Dos modos
**A. Se retiene al proveedor** (recibe el neto). Ejemplo, servicio de Bs 1.000 con 15,5 %: Dr gasto 1.000 / Cr proveedor o fondo fijo 845 / Cr 213800 125 / Cr 213700 30.

**B. La empresa asume la retención (grossing-up).** `l10n_bo` 19 trae los grupos de 8 % y 15,5 %, pero **con los signos invertidos**: debitaba la retención por pagar y acreditaba el gasto. `l10n_bo_spa` lo corrige y agrega el 16 % RC-IVA. Ejemplo, Bs 1.000 con 15,5 %:

| Cuenta | Debe | Haber |
|---|---|---|
| Gasto del servicio | 1.000,00 | |
| 520930 Retenciones IUE (gasto) | 147,93 | |
| 520920 Retenciones IT (gasto) | 35,50 | |
| 212100 Proveedor / fondo fijo | | 1.000,00 |
| 213800 Retenciones IUE por pagar | | 147,93 |
| 213700 Retenciones IT por pagar | | 35,50 |

> Una fuente secundaria cita jurisprudencia del TSJ que considera **no deducibles** las retenciones asumidas. Si el contador lo confirma, se reclasifican a **560400 Gastos no deducibles – Retenciones asumidas** o se ajustan en la conciliación del IUE.

**C. Sin factura y sin retención** (casos que la norma exime o compras no respaldadas): todo el gasto a **560500 Gastos no deducibles – Sin respaldo de factura**. Se registra siempre.

> **No se implementa** ningún mecanismo de cuentas bancarias o cajas fuera de la contabilidad. Toda compra se registra; lo no deducible se separa en sus cuentas y se ajusta en la conciliación tributaria del IUE.

## Fondo fijo (caja chica)
Sistema de **fondo fijo puro (imprest)**: la cuenta del fondo siempre muestra el monto asignado.

### Configuración (`l10n_bo.petty.cash.fund`)
- Una cuenta por fondo (creadas por `l10n_bo_spa`): `111210 Fondo fijo – Recepción`, `111220 Fondo fijo – Cocina y restaurante`, `111230 Fondo fijo – Mantenimiento`. Diario **FFIJ**.
- Custodio designado, monto fijo, tope por gasto, categorías permitidas, área analítica.

### Ciclo
| Paso | Quién | Asiento |
|---|---|---|
| Creación | Gerente | Debe 1112x0 (fondo) / Haber Banco |
| Gastos del período | Custodio (app/portal móvil, foto del comprobante) | **Ninguno** (vouchers en borrador) |
| Rendición | Custodio | Ninguno; se adjunta arqueo |
| Validación | Contador | Revisa documentos (unicidad y datos fiscales como compras con factura; retención si es sin factura) |
| **Reposición** | Contador / Tesorería | **Un asiento**: Debe gastos (+ 114100 Crédito Fiscal IVA) / Haber 213700-213800-213910 retenciones / Haber **Banco** por el neto repuesto |
| Arqueo con diferencia | Contador | Faltante → 112210 Cuentas por cobrar al personal (o 560700 Faltantes de caja si se asume); sobrante → 430410 Sobrantes de caja |
| Cambio de monto | Gerente | Debe/Haber 1112x0 contra Banco |

**Regla**: efectivo + comprobantes pendientes = monto fijo. El sistema lo calcula en la rendición.

### Por qué no un diario de caja con saldo variable
Odoo permite modelar la caja chica como diario de efectivo con movimientos individuales; es válido, pero el fondo fluctúa y mezcla gastos no validados con la contabilidad. El modelo imprest mantiene la contabilidad limpia hasta que el contador valida.
