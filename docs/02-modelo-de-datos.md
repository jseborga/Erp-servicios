# 02 · Modelo de datos

Convención: modelos propios con prefijo `spa.` / `l10n_bo.`; todos con `company_id`, `active` y `mail.thread` cuando tengan flujo.

## spa_base

### `spa.space` — Espacio
| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char | Piscina, Sauna, Jacuzzi, Cabina de masajes |
| `capacity` | Integer | Aforo máximo simultáneo (piscina 15, jacuzzi 5, sauna 5, cabina 1) |
| `access_mode` | Selection | `slot` (por franja) · `free` (libre con control de aforo) |
| `resource_calendar_id` | M2O `resource.calendar` | Horario de funcionamiento |
| `slot_duration` | Float (horas) | Solo `slot` |
| `slot_buffer` | Float (horas) | Tiempo de limpieza entre franjas |
| `max_stay` | Float (horas) | Solo `free`, opcional |
| `state` | Selection | `active` · `maintenance` · `closed` |
| `analytic_account_id` | M2O | Centro de costo del área |
| `closure_ids` | O2M `spa.space.closure` | Cierres programados (mantenimiento, feriados) |

### `spa.service` — Servicio
| Campo | Tipo | Notas |
|---|---|---|
| `name` | Char | Masaje relajante 60', Acceso piscina… |
| `product_id` | M2O `product.product` | Precio suelto, impuestos, cuenta de ingreso |
| `space_id` | M2O `spa.space` | |
| `requires_staff` | Boolean | Masaje = True |
| `skill_id` | M2O `spa.skill` | Especialidad requerida (masajista, instructor, salvavidas) |
| `duration` | Float | Duración del servicio |
| `seats_per_booking` | Integer | Normalmente 1 |
| `booking_lead_min` / `booking_lead_max` | Float | Anticipación mínima y máxima para reservar |
| `guest_allowed` | Boolean | Si admite invitados |

### `spa.skill` y empleados
- `spa.skill`: catálogo de especialidades.
- `hr.employee` extendido: `spa_skill_ids` (M2M), `resource_calendar_id` (turnos, estándar).

## spa_booking

### `spa.slot` — Franja (generada)
Generada por cron a N días vista para espacios `slot`: `space_id`, `start`, `stop`, `capacity` (copiada), `seats_taken` (computado), `state`.

### `spa.booking` — Reserva
| Campo | Tipo | Notas |
|---|---|---|
| `partner_id` | M2O | Socio o cliente |
| `membership_id` | M2O `spa.membership` | Vacío si es pago suelto |
| `service_id`, `space_id` | M2O | |
| `slot_id` | M2O | Solo modo `slot` |
| `start`, `stop` | Datetime | |
| `employee_id` | M2O `hr.employee` | Si el servicio requiere personal |
| `guest_ids` | O2M `spa.booking.guest` | Invitados de esta reserva |
| `seats` | Integer | 1 + invitados |
| `channel` | Selection | `portal` · `reception` · `whatsapp` · `phone` |
| `state` | Selection | `draft` → `confirmed` → `checked_in` → `done` · `cancelled` · `late_cancel` · `no_show` |
| `consumption_ids` | O2M `spa.consumption` | Consumos de derechos generados |
| `penalty_move_id` | M2O `account.move` | Si se cobra penalidad |

**Regla de disponibilidad** (`spa.availability` servicio abstracto):
```
cupos_libres(servicio, inicio, fin) =
    min( aforo_espacio − ocupados_espacio(inicio, fin),
         personal_libre_con_skill(inicio, fin)  si requires_staff, si no ∞ )
```
Restricción en `confirm()`: bloqueo de fila (`SELECT … FOR UPDATE` sobre el slot o el espacio) para evitar sobreventa concurrente.

## spa_membership

### `spa.plan` — Plan
| Campo | Notas |
|---|---|
| `name` | Básica, Premium, VIP… |
| `period_ids` | O2M `spa.plan.period`: duración (1, 3, 12 meses u otra), precio, producto, descuento |
| `line_ids` | O2M `spa.plan.line` (derechos) |
| `guest_quota` / `guest_period` | Free pass del plan (p. ej. 2 por mes) |
| `guest_fee_product_id` | Tarifa de invitado cuando se agota el cupo |
| `cancel_policy_id` | M2O `spa.cancel.policy` |
| `pos_discount_ids` | O2M: % por categoría de producto del POS |
| `grace_days` | Días de gracia de mora |
| `access_schedule_id` | M2O `resource.calendar`: horario permitido general |

### `spa.plan.line` — Derecho incluido
| Campo | Notas |
|---|---|
| `service_id` | |
| `unlimited` | Boolean |
| `quantity` | Si no es ilimitado |
| `period` | `day` · `week` · `month` · `plan` |
| `freq_limit_qty` / `freq_limit_period` | p. ej. máx. 1 por `week` |
| `allowed_schedule_id` | Horario permitido para este servicio |
| `carryover` | `lose` · `accumulate` · `carry_limited` |
| `carryover_max` | Tope de acumulación/traslado |
| `guest_allowed` / `guest_qty` | Invitados permitidos en este servicio |

### `spa.membership` — Membresía de un socio
`partner_id`, `plan_id`, `period_id`, `date_start`, `date_end`, `state` (`draft` · `active` · `grace` · `suspended` · `expired` · `cancelled`), `sale_order_id`, `invoice_ids`, `payment_plan_id` (si es en cuotas), `qr_token` (credencial), `entitlement_ids`.

### `spa.entitlement` — Saldo por período
Una fila por (membresía, línea de plan, período): `granted`, `carried_in`, `used` (computado), `remaining` (computado), `period_start`, `period_end`.

### `spa.consumption` — Libro de consumos (inmutable)
`entitlement_id`, `booking_id`, `qty` (+ consumo / − devolución), `reason` (`booking`, `checkin`, `late_cancel`, `no_show`, `manual_adjust`), `user_id`, `date`. **Nunca se edita ni borra**; las correcciones son asientos inversos. Es la fuente de las métricas de uso.

### `spa.cancel.policy`
`free_cancel_hours`, `late_cancel_action` (`none` · `lose_session` · `fee`), `late_cancel_fee_product_id`, `no_show_action`, `no_show_fee_product_id`, `max_cancellations_per_month`.

### Invitados
- `spa.guest` (persona invitada → se crea/vincula `res.partner` y **lead CRM**).
- `spa.booking.guest`: `booking_id`, `guest_id`, `charge_type` (`free_pass` · `fee`), `sale_line_id`.

## spa_billing
- `spa.payment.offer`: nombre, vigencia (`date_from`/`date_to`), planes y períodos aplicables, tipo (`installments` · `discount`), nº de cuotas, % descuento, condiciones.
- `spa.payment.plan`: cuotas generadas para una membresía (`due_date`, `amount`, `invoice_id`, `state`).
- `spa.dunning.step`: escalera de avisos (días respecto al vencimiento, canal, plantilla, acción: `notify` · `suspend`).

## spa_crm
- `crm.lead` extendido: `spa_source_id`, `referred_by_partner_id`, `origin_type` (`web`, `guest`, `courtesy`, `promo`, `walk_in`), `courtesy_pass_id`.
- `spa.source`: fuentes configurables (Instagram, Facebook, WhatsApp, Web, Referido…), con `utm.source` asociado.
- `spa.courtesy.pass`: pase de cortesía (servicios incluidos, vigencia, emitido por, lead asociado, canjeado sí/no).

## spa_access
- `spa.access.log`: `partner_id`, `space_id`, `booking_id`, `check_in`, `check_out`, `method` (`qr` · `manual`), `user_id`.
- `spa.space.occupancy` (computado en vivo): ocupación actual por espacio de modo `free`.

## l10n_bo_purchase (extensión de `account.move`, facturas de proveedor)
| Campo | Notas |
|---|---|
| `l10n_bo_doc_type` | `siat_online` (CUF) · `dosificacion` (autorización + código de control) · `manual` · `none` (sin factura) |
| `l10n_bo_supplier_nit` | NIT del emisor (relacionado con el partner, editable si difiere) |
| `l10n_bo_invoice_number` | Número de factura |
| `l10n_bo_cuf` | Solo `siat_online` |
| `l10n_bo_auth_number` | Solo `dosificacion`/`manual`; en `siat_online` se exporta "1" al Libro de Compras |
| `l10n_bo_control_code` | Solo `dosificacion` |
| `l10n_bo_purchase_type` | Tipo de compra para el Libro de Compras (catálogo SIN — **a verificar**) |
| `l10n_bo_withholding_mode` | Sin factura: `supplier_bears` · `company_bears` (grossing-up) · `none` |

Restricción única (índice parcial en PostgreSQL, solo `move_type in ('in_invoice','in_refund')` y `state != 'cancel'`):
```
UNIQUE (company_id, l10n_bo_supplier_nit, l10n_bo_invoice_number,
        COALESCE(l10n_bo_cuf, l10n_bo_auth_number))
```

## l10n_bo_petty_cash
- `l10n_bo.petty.cash.fund`: nombre, custodio (`hr.employee`/`res.users`), cuenta contable (subcuenta de 1112), diario, monto fijo, tope por gasto, área analítica, estado.
- `l10n_bo.petty.cash.voucher`: gasto en borrador con foto, tipo de documento (reusa campos de `l10n_bo_purchase`), proveedor, monto, cuenta de gasto, analítica.
- `l10n_bo.petty.cash.report` (rendición): vouchers, total, arqueo (efectivo contado), diferencias, `move_id` de reposición, estado (`draft` · `submitted` · `approved` · `reimbursed`).
