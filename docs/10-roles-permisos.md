# 10 · Roles y permisos

Cada rol es un grupo (`res.groups`) en la categoría "Spa". Una persona puede tener varios. Los grupos estándar de Odoo (Ventas, Contabilidad, POS, Compras) se asignan como grupos implicados.

| Rol | Grupo técnico | Implica | Puede | No puede |
|---|---|---|---|---|
| Socio | `base.group_portal` | — | Ver su plan, saldo, reservas, invitados, pagos; reservar; pagar | Ver datos de otros |
| Recepción / Atención | `spa.group_reception` | Ventas: usuario (propios docs), CRM usuario | Alta de socios, reservas, check-in, registrar pagos por validar, emitir cortesías (con tope), leads | Validar pagos, modificar planes, contabilidad |
| Terapeuta | `spa.group_therapist` | Empleado | Ver su agenda, marcar atendido/no-show | Ver datos financieros |
| Mesero | `spa.group_waiter` | POS usuario | Abrir/gestionar comandas, asignar socio | Cobrar (configurable), anular |
| Cocina | `spa.group_kitchen` | — | Ver comandas pendientes | Todo lo demás |
| Cajero | `spa.group_cashier` | POS usuario, Contabilidad: facturación | Cobrar, abrir/cerrar caja, **validar pagos QR/transferencia** | Asientos manuales |
| Comprador | `spa.group_buyer` | Compras usuario | Solicitudes, órdenes, recepciones | Aprobar sobre su umbral, pagar |
| Custodio de fondo fijo | `spa.group_petty_cash_custodian` | — | Registrar gastos de **su** fondo, rendir | Ver otros fondos, reponer |
| Marketing / CRM | `spa.group_marketing` | CRM gerente | Fuentes, campañas, promociones, embudos | Precios de planes |
| Contador | `spa.group_accountant` | Contabilidad: asesor | Asientos, validar rendiciones y documentos fiscales, impuestos, cierres | Configurar planes |
| Gerente / Administrador | `spa.group_manager` | Todos los anteriores + Ajustes | Configuración, aprobaciones, tableros, ajustes manuales de saldo | — |

## Reglas de registro (`ir.rule`)
- Socio (portal): solo `partner_id = user.partner_id` en reservas, membresías, consumos.
- Terapeuta: reservas con `employee_id.user_id = user`.
- Custodio: fondos donde es custodio y sus vouchers.
- Comprador: aprobación limitada por monto (campo en el usuario o grupo de nivel).
- Recepción: emisión de cortesías limitada por cantidad mensual configurable.

## Auditoría
- `mail.thread` en membresías, reservas, fondos y ajustes de saldo (quién cambió qué).
- Ajustes manuales de saldo (`spa.consumption` reason `manual_adjust`) requieren motivo y solo los hace Gerente.
