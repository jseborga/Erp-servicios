# Part of ERP Servicios Spa. License LGPL-3.
"""Utilidades puras (sin ORM) para documentos fiscales de compra de Bolivia.

* Normalización de NIT, número, CUF, número de autorización y código de control.
* Decodificación del CUF (Código Único de Factura) del SIAT.
* Lectura del texto del código QR de las facturas.

Fuentes y grado de verificación (oct-2026):

* QR de facturas SIAT en línea: URL ``.../consulta/QR?nit=..&cuf=..&numero=..&t=..``
  publicada por el SIN en siatinfo.impuestos.gob.bo ("Código Respuesta Rápida (QR)").
  El host de producción puede variar (pilotosiat / siat); por eso se acepta cualquier host.
  La URL NO trae fecha ni monto: la fecha se obtiene del propio CUF y el monto se
  ingresa a mano.
* QR de facturas computarizadas (dosificación): texto separado por ``|`` con 12 campos
  (NIT emisor | número | autorización | fecha dd/mm/aaaa | total | importe base CF |
  código de control | NIT comprador | ICE/IEHD/tasas | no gravado/tasa cero |
  no sujeto a CF | descuentos). Fuente secundaria (boliviaimpuestos.com) con ejemplo.
* CUF: algoritmo de la implementación abierta ``go-siat`` (pkg/utils/cuf.go): cadena
  decimal de 53 dígitos (NIT 13, fecha-hora 17, sucursal 4, modalidad 1, tipo de emisión 1,
  tipo de factura 1, documento sector 2, número 10, punto de venta 4) + dígito
  verificador módulo 11, convertida a hexadecimal, seguida del código de control del
  CUFD. Comprobado decodificando un CUF real del ambiente piloto del SIN incluido en las
  pruebas de esa librería. No se pudo leer la especificación oficial del SIN; validar con
  facturas reales antes de producción (por eso la validación estricta es configurable).
"""
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

CONTROL_CODE_RE = re.compile(r'^[0-9A-F]{1,2}(-[0-9A-F]{1,2}){3,4}$')
HEX_RE = re.compile(r'^[0-9A-F]+$')
AUTH_RE = re.compile(r'^\d{1,20}$')
CUF_MIN_LEN = 30
CUF_MAX_LEN = 100
# Longitud observada del código de control del CUFD (15). Se prueban otras por si varía.
CUFD_CONTROL_LENGTHS = (15,) + tuple(n for n in range(8, 25) if n != 15)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def _alnum(value):
    return re.sub(r'[^0-9A-Za-z]', '', value or '').upper()


def normalize_nit(value):
    """NIT/CI sin espacios, puntos ni guiones; sin ceros a la izquierda si es numérico."""
    value = _alnum(value)
    if value.isdigit():
        value = value.lstrip('0') or '0'
    return value or False


def normalize_number(value):
    value = _alnum(value)
    if value.isdigit():
        value = value.lstrip('0') or '0'
    return value or False


def normalize_cuf(value):
    return _alnum(value) or False


def normalize_auth(value):
    return _alnum(value) or False


def normalize_control_code(value):
    """``7bf348a8`` → ``7B-F3-48-A8``; respeta los guiones si ya los trae."""
    raw = (value or '').strip().upper().replace(' ', '')
    if not raw:
        return False
    if '-' not in raw and HEX_RE.match(raw) and len(raw) in (8, 10):
        raw = '-'.join(raw[i:i + 2] for i in range(0, len(raw), 2))
    return raw


def is_valid_control_code(value):
    return bool(value and CONTROL_CODE_RE.match(value))


def is_valid_auth_number(value):
    return bool(value and AUTH_RE.match(value))


def is_plausible_cuf(value):
    return bool(value and HEX_RE.match(value) and CUF_MIN_LEN <= len(value) <= CUF_MAX_LEN)


# ---------------------------------------------------------------------------
# CUF
# ---------------------------------------------------------------------------
def mod11_digit(digits):
    """Dígito verificador módulo 11 (multiplicadores 2..9 de derecha a izquierda)."""
    total, mult = 0, 2
    for char in reversed(digits):
        total += mult * int(char)
        mult = 2 if mult == 9 else mult + 1
    remainder = total % 11
    return '1' if remainder == 10 else str(remainder)


def encode_cuf(nit, emission, branch, modality, emission_type, invoice_type, sector, number,
               pos, control_code):
    """Genera un CUF (útil para pruebas). ``emission`` es datetime en hora de Bolivia."""
    stamp = emission.strftime('%Y%m%d%H%M%S') + '%03d' % (emission.microsecond // 1000)
    base = '%013d%s%04d%d%d%d%02d%010d%04d' % (
        int(nit), stamp, branch, modality, emission_type, invoice_type, sector, int(number), pos)
    base += mod11_digit(base)
    return '%X' % int(base) + control_code.upper()


def _decode_head(head):
    try:
        digits = str(int(head, 16))
    except ValueError:
        return None
    if len(digits) > 54:
        return None
    digits = digits.zfill(54)
    if mod11_digit(digits[:53]) != digits[53]:
        return None
    try:
        emission = datetime.strptime(digits[13:27], '%Y%m%d%H%M%S').replace(
            microsecond=int(digits[27:30]) * 1000)
    except ValueError:
        return None
    result = {
        'nit': digits[:13].lstrip('0') or '0',
        'emission': emission,
        'date': emission.date(),
        'branch': int(digits[30:34]),
        'modality': int(digits[34]),
        'emission_type': int(digits[35]),
        'invoice_type': int(digits[36]),
        'sector': int(digits[37:39]),
        'number': digits[39:49].lstrip('0') or '0',
        'pos': int(digits[49:53]),
    }
    if (
        result['nit'] == '0'
        or not 2000 <= emission.year <= 2100
        or result['modality'] not in (1, 2, 3)
        or result['emission_type'] not in (1, 2, 3)
        or not 1 <= result['invoice_type'] <= 9
        or result['sector'] == 0
    ):
        return None
    return result


def decode_cuf(cuf, nit=None):
    """Decodifica un CUF. Devuelve un dict (nit, emission, date, branch, modality,
    emission_type, invoice_type, sector, number, pos, control_code) o None si no supera el
    dígito verificador módulo 11 y las comprobaciones de plausibilidad.

    El largo del código de control del CUFD no está documentado aquí: se prueba primero 15
    (observado) y luego otros largos; si se indica ``nit`` se prefiere la lectura cuyo NIT
    coincide.
    """
    cuf = normalize_cuf(cuf)
    if not cuf or not HEX_RE.match(cuf):
        return None
    candidates = []
    for length in CUFD_CONTROL_LENGTHS:
        if length >= len(cuf):
            continue
        decoded = _decode_head(cuf[:-length])
        if decoded:
            decoded['control_code'] = cuf[-length:]
            candidates.append(decoded)
    if not candidates:
        return None
    if nit:
        nit = normalize_nit(nit)
        for decoded in candidates:
            if decoded['nit'] == nit:
                return decoded
    return candidates[0]


# ---------------------------------------------------------------------------
# QR
# ---------------------------------------------------------------------------
def _to_float(value):
    try:
        return float((value or '').strip().replace(',', '.'))
    except ValueError:
        return None


def _parse_legacy_date(value):
    value = (value or '').strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_legacy_qr(text):
    """QR de factura computarizada: ``NIT|número|autorización|fecha|total|base CF|código de
    control|NIT comprador|ICE|no gravado|no sujeto|descuentos``."""
    parts = [p.strip() for p in (text or '').strip().split('|')]
    if len(parts) < 7:
        return None
    nit, number, auth, raw_date, total, base, control = parts[:7]
    if not (nit.isdigit() and number.isdigit() and auth.isdigit()):
        return None
    control = normalize_control_code(control)
    data = {
        'source': 'legacy',
        'doc_type': 'dosificacion' if is_valid_control_code(control) else 'manual',
        'nit': normalize_nit(nit),
        'number': normalize_number(number),
        'auth_number': normalize_auth(auth),
        'control_code': control if is_valid_control_code(control) else False,
        'cuf': False,
        'date': _parse_legacy_date(raw_date),
        'amount_total': _to_float(total),
        'amount_base': _to_float(base),
        'buyer_nit': normalize_nit(parts[7]) if len(parts) > 7 else False,
    }
    extra = ('amount_ice', 'amount_not_taxed', 'amount_not_subject', 'amount_discount')
    for key, value in zip(extra, parts[8:12]):
        data[key] = _to_float(value)
    return data


def parse_siat_url_qr(text):
    """QR de factura SIAT en línea: ``https://<host>/consulta/QR?nit=..&cuf=..&numero=..&t=..``."""
    text = (text or '').strip()
    if 'cuf=' not in text.lower():
        return None
    query = urlparse(text).query or text.split('?', 1)[-1]
    params = {key.lower(): values[0] for key, values in parse_qs(query).items() if values}
    cuf = normalize_cuf(params.get('cuf'))
    if not cuf:
        return None
    nit = normalize_nit(params.get('nit'))
    decoded = decode_cuf(cuf, nit=nit)
    return {
        'source': 'siat',
        'doc_type': 'siat_online',
        'nit': nit or (decoded and decoded['nit']) or False,
        'number': normalize_number(params.get('numero')) or (decoded and decoded['number']) or False,
        'cuf': cuf,
        'auth_number': False,
        'control_code': False,
        'date': decoded['date'] if decoded else None,
        'amount_total': None,  # la URL del SIN no incluye el monto
        'size': params.get('t'),
        'cuf_decoded': bool(decoded),
    }


def parse_invoice_qr(text):
    """Detecta el formato y devuelve un dict con los datos o None."""
    text = (text or '').strip()
    if not text:
        return None
    if '|' in text:
        return parse_legacy_qr(text)
    return parse_siat_url_qr(text)

