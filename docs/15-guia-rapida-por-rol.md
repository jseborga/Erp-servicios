# 15 · Guía rápida por rol

Cómo se usa el sistema en el día a día. Los nombres de menú son los que aparecen en Odoo (español de Bolivia). Para practicar, use un servidor con los datos de demostración (`spa_demo`, usuarios `*.demo`, clave `demo`).

## Recepción (`recepcion.demo`)
| Tarea | Dónde |
|---|---|
| Ver cuántas personas hay en cada espacio | Spa → Operación → **Aforo en vivo** |
| Registrar el ingreso de un socio (QR o búsqueda) | Spa → Operación → **Registrar ingreso**. En piscina, sauna y jacuzzi (acceso libre) descuenta el saldo y controla el aforo; en masajes exige una reserva |
| Vender una entrada a quien no es socio | **Registrar ingreso** con «Pase diario»: se factura y se abre el registro del pago |
| Reservar un servicio para un socio | Spa → Operación → **Reserva rápida** (muestra por qué una franja no está disponible). Si está llena: **Lista de espera** |
| Canjear un pase de cortesía | Spa → Operación → **Canjear cortesía** |
| Alta presencial de un socio | Spa → Socios → **Membresías** → Nuevo → «Generar cobro del período» → «Registrar pago» (caja lo valida) |
| Registrar un invitado | Desde la reserva (pestaña invitados) o Spa → Socios → **Invitados** |
| Enviar los avisos de WhatsApp | Spa → Operación → **Mensajes WhatsApp** → «Abrir WhatsApp» (envía desde la app del celular de recepción) |
| Seguimiento de sus prospectos | CRM → Ventas → **Captación (spa)**. Pases de cortesía: Spa → CRM → **Pases de cortesía** |

## Caja (`caja.demo`)
| Tarea | Dónde |
|---|---|
| Validar pagos con QR o transferencia (comprobante del socio) | Spa → Operación → **Pagos por validar** → revisar la imagen → «Validar» o «Rechazar» con motivo |
| Cobrar en efectivo | El pago registrado por recepción aparece en **Pagos por validar** |
| Restaurante y cafetería | Punto de venta → Restaurante / Cafetería. Al elegir al socio se aplica su descuento; «Cuenta del socio» carga el consumo a su cuenta (con límite según el plan) |
| Facturas SIAT pendientes (modalidad Portal Web) | Facturación → Bolivia SIAT → Facturas SIAT: emita la factura en el Portal Web del SIN y registre número y CUF con «Registrar datos SIAT» |

> La factura de una membresía o de un servicio suelto **se emite al cobrar** (o al prestar el servicio): antes es un «cobro pendiente» sin valor fiscal (Ley 843 art. 4 inc. b).

## Terapeuta / instructor (`terapeuta.demo`, `instructor.demo`)
- Spa → Operación → **Agenda**: solo sus reservas y clases. Marcar «Atendida» o «No se presentó».

## Socio (web, `ana.demo`)
- `/spa`: planes y precios; elegir plan y duración → pagar con QR y subir el comprobante.
- `/my/spa`: credencial QR, saldo del mes, próximas reservas (con cancelación según la política del plan), deudas.
- `/my/spa/book`: reservar; `/my/spa/guests`: invitados; `/my/spa/classes`: clases; `/my/spa/pay`: pagar.

## Marketing (`marketing.demo`)
- Spa → CRM → **Captación** y **Retención** (socios en riesgo: gracia, suspensión, poco uso, por vencer).
- Spa → CRM → **Pases de cortesía**: emitir (se envía por WhatsApp con QR).
- Spa → CRM → **Conversión por fuente** y **Uso de los planes**.
- Las ofertas de pago (descuentos y cuotas con vigencia) las crea el gerente; marketing las ve.

## Gerente / dueño (`gerente.demo`)
- Spa → Reportes → **Resumen**: personas dentro, reservas de hoy, socios por estado, ingreso mensual recurrente, mora, prospectos.
- **Rentabilidad por área** y **Estado de resultados por área**: ingresos y costos por piscina, sauna/jacuzzi, spa, restaurante, cafetería y eventos.
- Spa → Configuración: planes (servicios incluidos, saldos, invitados, días de gracia, crédito en restaurante, reparto por área), espacios (aforo, modo, horario), **Escalera de cobranza**, políticas de cancelación, **Ofertas de pago**, fuentes de prospectos, plantillas de mensajes.
- Membresías: **Cambiar de plan** (sube hoy con diferencia prorrateada; baja desde el próximo período) y **Congelar**.
- Alquileres y eventos: confirmar (bloquea el espacio), garantía, factura.
- Compras: aprobar órdenes sobre el monto configurado en la compañía (aprobación en dos pasos de Compras).

## Compras (`compras.demo`) y Contador (`contador.demo`)
| Tarea | Dónde |
|---|---|
| Orden de compra y recepción | Compras |
| Factura de proveedor con datos fiscales | Facturación → Proveedores → Facturas: tipo de documento, NIT, número, CUF (o autorización y código de control). «Leer QR» llena los datos. Una factura repetida se bloquea |
| Compra sin factura | Tipo «Sin factura» + «Aplicar retenciones» (8 %, 15,5 % o 16 %; retenida al proveedor o asumida) |
| Libro de Compras / Libro de Ventas | Facturación → Reportes → Impuestos y finanzas → **Libro de Compras (SIN)** / **Libro de Ventas (SIN)**; también Facturación → Bolivia SIAT → Libro de Ventas |
| Aprobar rendiciones de fondo fijo | Fondo fijo → **Rendiciones** → Aprobar (crea las facturas, los pagos y la reposición) |
| Estados financieros | Facturación → Reportes → **Informes de contabilidad OCA** (Balance de Sumas y Saldos, Libro mayor, Libro diario) y → **MIS** → Informes MIS |
| Devengo de planes prepagados | Automático cada mes (diario DIFE). El gerente lo controla en Spa → Reportes → **Devengo de membresías**; el contador ve los asientos del diario DIFE |

## Custodio del fondo fijo (`custodio.demo`)
- Fondo fijo → **Comprobantes**: registrar cada gasto con foto (y QR si tiene factura).
- Fondo fijo → **Rendiciones**: contar el efectivo y enviar a aprobación.

## Procesos automáticos (no requieren acción)
| Proceso | Frecuencia |
|---|---|
| Estados de membresía (gracia, suspensión, vencimiento) y saldos del mes | Diario |
| Escalera de cobranza (avisos −5, 0, +3, suspensión +5, último aviso +15) y seguimiento de cuotas | Diario |
| Devengo mensual de planes prepagados y emisión de cargos del mes anterior | Diario |
| Recordatorio de reservas (24 h antes), no-show y cierre de reservas | Diario / periódico |
| Lista de espera (aviso al liberarse un cupo) | Cada 10 minutos |
| Riesgo de baja y oportunidades de retención | Diario |
| Sesiones de clases para las próximas semanas | Diario |
| Reintento de emisión SIAT (modalidad proveedor) | Cada 30 minutos |
