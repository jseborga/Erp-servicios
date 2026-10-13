# 13 · Vacíos y verificaciones

Registro honesto de qué está verificado y qué no. **Actualizar este archivo al resolver cada punto.**

## ✅ Verificado (al 13-oct-2026)
| Hecho | Cómo se verificó |
|---|---|
| Los 17 módulos propios + 8 OCA se instalan juntos en una base nueva (es_BO, BO, BOB) mediante el script de arranque de Docker | Ejecución real del script `docker/entrypoint-spa.sh` contra Odoo 19.0 + PostgreSQL 16 |
| 315 pruebas automáticas en verde, incluidas: un mes de negocio de punta a punta con usuarios por rol, 19 regresiones de defectos corregidos y recorridos en navegador (Chromium) | `--test-tags` de los 16 módulos sobre esa base |
| 817 pantallas recorridas en navegador por 10 roles + web del socio (celular y escritorio): sin errores de consola, sin peticiones fallidas, sin textos en inglés propios, sin desborde horizontal en celular | Playwright + Chromium, capturas revisadas |
| Datos de demostración consistentes: todos los asientos cuadran, balance de comprobación en cero, saldos usados ≤ otorgados | Pruebas de `spa_demo` y script de verificación |
| `membership`, `appointment`, `sale_subscription`, `whatsapp`, `account_accountant`, `account_reports`, `hr_payroll`, `pos_preparation_display` **no** existen en Odoo CE 19 | Listado de `addons/` en la rama `19.0` |
| `l10n_bo` 19: grossing-up con signos invertidos, IVA de compras calculado sin incluir, diferencias de caja a ajuste por inflación | Facturas de prueba; corregido en `l10n_bo_spa` (`docs/09` §4) |
| Redondeo por línea necesario con precios IVA incluido (si no, el POS deja Bs 0,01 abiertos) | Pruebas de `spa_pos`; aplicado en `l10n_bo_spa` |
| Ley 843 art. 4 inc. b: en servicios el hecho imponible es al terminar la prestación o al percibir el precio (lo primero); la factura se emite en ese momento | Texto de la ley (lexivox.org). El sistema emite la factura al cobrar o al prestar el servicio |
| SIN: servicio eventual de persona no registrada → RC-IVA 13 % + IT 3 % | *Retenciones – Preguntas frecuentes*, impuestos.gob.bo |
| QR de facturas en línea: enlace `…/consulta/QR?nit=&cuf=&numero=&t=` | Página oficial del SIN (siatinfo) |
| Estructura del CUF (NIT, fecha-hora, sucursal, modalidad, tipo, sector, número, punto de venta, dígito verificador, hex + código de control) | Biblioteca abierta go-siat; el codificador reproduce un CUF piloto real |
| Odoo 19: Python 3.10–3.14, PostgreSQL ≥ 13; imagen `odoo:19.0` (`latest` = Odoo 20) | `odoo/release.py`; `docker-library/official-images` |
| Dependencias Python (freezegun, qrcode, renderpm, xlsxwriter, xlrd) incluidas en el paquete oficial de Odoo 19 | `debian/control` de Odoo 19 |

## ⚠️ Por verificar — técnico
1. **`docker build` de la imagen** en el servidor: el entorno de desarrollo no tenía acceso a Docker Hub. El flujo de arranque sí se probó con el mismo script.
2. **Facturación SIAT por API**: solo existe el simulador («SIMULADO», nunca válido). Programar el conector del proveedor elegido; emitir desde el proceso programado (no al validar) para no perder el CUF si la transacción falla.
3. **WhatsApp API oficial (Meta)**: código listo, nunca probado contra Meta.
4. **Pruebas automáticas**: asumen una base nueva. Sobre una base con datos reales o de demostración, algunas fallan por conteos globales: ejecútelas en una base de prueba.
5. Formato del QR de facturas computarizadas antiguas (fuente secundaria con un ejemplo).
6. Pantalla de cocina: CE 19 no la trae; se usa impresión de comandas.
7. Revisión en un navegador real de la pantalla del POS con el distintivo del socio (se probó la llamada al servidor y una captura del piso y la pantalla de pago).

## ⚠️ Por verificar — fiscal / legal (contador boliviano)
1. Cuándo aplica cada retención de servicios: 15,5 % (IUE + IT, profesiones u oficios) o 16 % (RC-IVA + IT, servicios eventuales).
2. Deducibilidad de retenciones asumidas (grossing-up).
3. Casos en que se permite **vender sin factura** (el sistema lo restringe a un grupo autorizado, con tope y motivo, y registra IVA e IT igual).
4. Planes en cuotas: la factura completa se emite con el primer pago. ¿Corresponde facturar solo lo cobrado?
5. Alquileres: anticipo parcial emite la factura completa; ¿la penalidad por daños lleva IVA e IT?
6. Consumidor final sin datos: «S/N», número 0 (fuente secundaria). Tipos de documento del comprador 2, 3 y 4 sin confirmar.
7. Motivos de anulación (códigos 1–4) y plazo (día 9 del mes siguiente, citado en una RND de julio de 2026).
8. Formato vigente del Registro de Compras y Ventas (RCV); catálogos de tipo de compra.
9. Reembolso parcial de un plan prepagado: hoy reduce proporcionalmente el devengo pendiente.
10. Aportes sociales del empleador y planilla (CE no tiene nómina).
11. Ajuste por inflación / reexpresión de estados financieros.
12. Porcentajes reales de reparto analítico (gastos compartidos y membresías por área): los incluidos son ejemplos.
13. IVA de compras en 114100 (cambio respecto a `l10n_bo`, que usa 213500 para ambos).

## ⚠️ Decisiones abiertas (negocio)
1. Proveedor de facturación SIAT por API (costo, contingencias).
2. Proveedor o banco con QR que notifique el pago (hoy caja valida el comprobante).
3. Número y proveedor para la API oficial de WhatsApp.
4. Si el Gerente debe ser administrador completo de Odoo (hoy no: gestiona el spa, compras y fondos, pero no los Ajustes técnicos).
5. Reservas futuras de un socio suspendido: hoy se bloquea el ingreso, no se cancelan las reservas.
6. Lista de espera: retiene el cupo pero no al terapeuta.

## No construido (por ahora)
- Códigos promocionales en la web, «café diario incluido», marca de sobre-aforo al bajar el aforo, grupos específicos de mesero/cocina, límite de aprobación de compras por usuario.

## ❌ Descartado por diseño
- Cuentas bancarias o cajas no registradas en la contabilidad para compras sin factura: es contabilidad paralela y defraudación tributaria. Se reemplaza por retenciones o gastos no deducibles registrados.
- Facturas por renovaciones impagas: nunca se emiten (cobro pendiente en borrador hasta el pago).
