# 11 · Integraciones

## WhatsApp — capa intercambiable (`spa_messaging`)
Odoo CE 19 **no incluye** el módulo `whatsapp` (es Enterprise). Diseño:

```
Evento de negocio (recordatorio, aviso de mora, QR de pago…)
        │
        ▼
spa.message.template  ──►  spa.message.queue  ──►  Proveedor activo
                                                     ├─ wa_link   (enlace wa.me para enviar a mano desde la app normal)
                                                     ├─ meta_cloud (WhatsApp Business Platform, API oficial)
                                                     └─ evolution  (no oficial; solo pruebas / bajo volumen)
```
- Cambiar de proveedor = cambiar configuración; las plantillas y la cola no cambian.
- **Fase 1 (`wa_link`)**: el sistema prepara el mensaje y recepción lo envía con un clic desde la app normal. Cero riesgo de bloqueo; no automatizado.
- **Fase 2 (API oficial)**: mensajes de plantilla aprobados por Meta para avisos; webhook de mensajes entrantes → CRM.
- **Evolution API**: hasta donde sabemos automatiza WhatsApp Web y **no es la API oficial**; implica riesgo de bloqueo del número en envíos automáticos. **No verificado en esta fase**; usar solo en pruebas.

## Pagos QR
- Fase 1: QR del banco de la empresa (estático o generado en la app del banco) + comprobante subido por el socio + validación manual por caja.
- Fase 2: proveedor/banco con **API de generación de QR dinámico y notificación de pago** para conciliación automática. Ejemplo encontrado en la investigación: CUCU (API de facturación SIAT y cobros QR). **Sin evaluar costos ni condiciones**; ver `docs/13`.
- En Odoo: `payment.provider` propio `spa_payment_qr` con estado `pending` → `done` al recibir webhook o validación manual.

## Facturación electrónica SIAT (`l10n_bo_siat_edi`)
Contrato de integración independiente del proveedor:
```python
class SiatProvider(models.AbstractModel):
    _name = 'l10n_bo.siat.provider'
    def emit_invoice(self, move): ...      # → CUF, XML, PDF, estado
    def cancel_invoice(self, move, reason): ...
    def get_status(self, move): ...
    def open_contingency(self, reason_code): ...  # eventos significativos
```
Implementaciones concretas por proveedor. Requisitos que debe cumplir el proveedor elegido: certificación vigente ante el SIN, modalidad electrónica en línea, soporte de contingencias, documento sector adecuado para servicios y restaurante, SLA y costo por factura.

## Lectura de QR de facturas de compra
Cámara del celular (portal del custodio) o lector USB en recepción → parseo de campos → `l10n_bo_purchase`. Formato del QR de facturas SIAT en línea **por verificar** con facturas reales.

## Correo
Servidor SMTP propio o servicio transaccional; plantillas `mail.template` para confirmaciones, recordatorios y avisos.
