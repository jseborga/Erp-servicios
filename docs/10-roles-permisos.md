# 10 · Roles y permisos

Cada rol es un grupo (`res.groups`). Una persona puede tener varios. Los grupos estándar de Odoo (CRM, Facturación, Punto de venta, Compras) se asignan como grupos implicados. Tabla según lo **implementado** (al 13-oct-2026); las pruebas de `spa_all` verifican cada fila con usuarios reales por rol.

| Rol | Grupo técnico | Implica | Puede | No puede |
|---|---|---|---|---|
| Socio | `base.group_portal` | — | Ver su plan, saldo, reservas, invitados y deudas; reservar y cancelar según la política; pagar con comprobante | Ver datos de otros |
| Recepción / Atención | `spa_base.group_spa_reception` | Usuario interno, gestión de contactos, CRM (sus prospectos) | Alta de socios, generar el cobro, registrar pagos (quedan por validar), reservas, check-in, pase diario, cortesías, invitados, mensajes WhatsApp | Validar pagos, configurar planes, contabilidad, analítica |
| Terapeuta / Instructor | `spa_base.group_spa_therapist` | Usuario interno | Ver **su** agenda y clases, marcar atendida / no se presentó, ver invitados de sus reservas | Datos financieros |
| Caja | `spa_base.group_spa_cashier` | Recepción, Facturación, Punto de venta (usuario) | Todo lo de recepción; **validar o rechazar** pagos QR/transferencia; cobrar en el POS; registrar datos SIAT (Portal Web) | Asientos manuales, configuración |
| Marketing / CRM | `spa_base.group_spa_marketing` | Recepción, CRM gerente | Embudos de Captación y Retención, cortesías, reportes de conversión por fuente y uso de los planes | Crear ofertas de pago o fuentes (lo hace el gerente), contabilidad |
| Comprador | `l10n_bo_purchase.group_spa_buyer` | Compras (usuario) | Órdenes, recepciones, facturas de proveedor con datos fiscales | Aprobar sobre el monto configurado en la compañía |
| Contador | `l10n_bo_purchase.group_spa_accountant` | Facturación y contabilidad (usuario) | Asientos, Libros de Compras y Ventas, aprobar rendiciones de fondo fijo, montos de fondos, reportes OCA | Configurar planes |
| Custodio de fondo fijo | `l10n_bo_petty_cash.group_petty_cash_custodian` | Usuario interno | Registrar vales de **su** fondo y rendir | Ver otros fondos, aprobar, reponer |
| Ventas sin factura | `l10n_bo_siat_edi.group_l10n_bo_sale_no_invoice` | Facturación | Marcar una venta «sin factura» (con tope y motivo; IVA e IT se registran igual) | — |
| Mesero | `point_of_sale.group_pos_user` (grupo estándar) | — | Comandas del restaurante, asignar socio | — |
| Gerente | `spa_base.group_spa_manager` | Caja, Marketing, Terapeuta, CRM gerente, POS gerente, Compras gerente, Contador | Configuración del spa, aprobaciones, tableros, cambio de plan, congelamiento, alquileres | Ajustes técnicos de Odoo (no es administrador del sistema; decisión abierta en `docs/13`) |

**No implementado:** grupo propio de cocina (CE 19 no trae pantalla de cocina; se imprime la comanda) y límite de aprobación de compras **por usuario** (hoy el monto es por compañía).

## Reglas de registro (`ir.rule`)
- Socio (portal): solo `partner_id = user.partner_id` en reservas, membresías, consumos.
- Terapeuta: reservas con `employee_id.user_id = user`.
- Custodio: fondos donde es custodio y sus vouchers.
- Comprador: aprobación limitada por el monto configurado en la compañía (no por usuario).
- Recepción: emisión de cortesías limitada por cantidad mensual configurable.

## Auditoría
- `mail.thread` en membresías, reservas, fondos y ajustes de saldo (quién cambió qué).
- Ajustes manuales de saldo (`spa.consumption` reason `manual_adjust`) requieren motivo y solo los hace Gerente.
