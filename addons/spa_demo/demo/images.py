# Part of ERP Servicios Spa. License LGPL-3.
"""Imágenes de la demo: QR de cobro ficticio y fotos de comprobantes, generadas al instalar."""
import base64
import io
import logging
import struct
import zlib

_logger = logging.getLogger(__name__)

QR_TEXT = 'SPA DEMO BOLIVIA - QR FICTICIO DE DEMOSTRACION - NO REALIZAR PAGOS'


def _tiny_png(width=8, height=8, rgb=(200, 200, 200)):
    """PNG mínimo de un color (sin dependencias), por si Pillow no está disponible."""
    raw = b''.join(b'\x00' + bytes(rgb) * width for _row in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def _canvas(width, height, lines, title_color=(176, 0, 32)):
    from PIL import Image, ImageDraw  # noqa: PLC0415 - Pillow es dependencia de Odoo

    image = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(120, 120, 120), width=2)
    y = 12
    for index, line in enumerate(lines):
        draw.text((14, y), line, fill=title_color if index == 0 else (40, 40, 40))
        y += 20
    return image, draw


def payment_qr_png(env):
    """QR de cobro de la empresa demo: escaneable, dice que es ficticio. Devuelve bytes PNG."""
    try:
        qr = env['ir.actions.report'].barcode('QR', QR_TEXT, width=300, height=300)
        from PIL import Image  # noqa: PLC0415

        image, _draw = _canvas(320, 380, ['QR FICTICIO - SOLO DEMOSTRACION', 'No realice pagos a este codigo'])
        image.paste(Image.open(io.BytesIO(qr)).convert('RGB'), (10, 70))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()
    except Exception as error:  # noqa: BLE001 - la imagen es decorativa: nunca bloquea la demo
        _logger.info('spa_demo: QR generado sin Pillow (%s)', error)
        return _tiny_png(64, 64, (230, 230, 230))


def receipt_png(amount_text, reference, bank='Banco Demo (ficticio)'):
    """Foto de comprobante bancario ficticio. Devuelve los bytes en base64 (campo Binary)."""
    try:
        image, _draw = _canvas(360, 170, [
            'COMPROBANTE DE PAGO - DEMOSTRACION',
            bank,
            'Monto: %s' % amount_text,
            'Referencia: %s' % reference,
            'Documento ficticio: no es un pago real',
        ])
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        data = buffer.getvalue()
    except Exception:  # noqa: BLE001
        data = _tiny_png(32, 20, (240, 240, 220))
    return base64.b64encode(data)
