# 06 · CRM

Base: módulo `crm` de Odoo CE 19 + `website_crm`, extendido por `spa_crm`.

## Fuentes configurables
`spa.source` (vinculadas a `utm.source`): Instagram, Facebook, TikTok, WhatsApp, Web, Referido de socio, Invitado de socio, Cortesía, Evento, Paso por recepción… Se agregan sin código.

Métrica principal: **tasa de conversión y tiempo a conversión por fuente**.

## Embudo (etapas `crm.stage`)
1. **Interesado** — consultó, dejó datos.
2. **Visita de prueba / cortesía** — se le emitió un pase.
3. **Propuesta** — se le envió plan y precio.
4. **Socio activo** — compró membresía (etapa ganada).
5. **En riesgo** — socio con mora, uso bajo o próximo a vencer sin renovar.
6. **Ex-socio** — no renovó (recuperable con campañas).

> Nota de diseño: "En riesgo" y "Ex-socio" son estados de un **socio existente**. Se implementan como un segundo equipo/embudo de **retención** (`crm.team` "Retención") para no mezclar métricas de captación con las de retención.

## Entrada automática de prospectos
| Evento | Acción |
|---|---|
| Formulario web | Lead en "Interesado" con fuente UTM |
| Invitado registrado por un socio | Lead en "Visita de prueba", `referred_by_partner_id` = socio |
| Pase de cortesía emitido | Lead en "Visita de prueba" con `courtesy_pass_id` |
| Mensaje entrante de WhatsApp (fase API) | Lead o actividad en lead existente |
| Socio en mora > N días o uso bajo | Oportunidad en embudo de Retención |
| Membresía vencida sin renovar | Pasa a "Ex-socio" |

Deduplicación por teléfono normalizado (+591) y email.

## Cortesías, promociones e invitaciones
- **Pase de cortesía** (`spa.courtesy.pass`): servicios incluidos, vigencia, quién lo emitió, canje con QR.
- **Promociones / códigos**: módulo estándar `loyalty` (cupones, códigos de descuento) aplicable en web y POS.
- **Invitaciones a eventos**: módulo `event` (fase posterior) para open days o clases demo.

## Seguimiento
- Actividades automáticas (llamar, enviar WhatsApp) por etapa con plazos.
- Plantillas de mensaje por etapa.
- Tablero: leads por fuente, conversión, socios referidores top, tasa de canje de cortesías, retención mensual.
