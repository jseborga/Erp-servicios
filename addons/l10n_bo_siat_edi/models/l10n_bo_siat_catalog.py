# Part of ERP Servicios Spa. License LGPL-3.
"""Catálogos de facturación de ventas SIAT y su grado de verificación (oct-2026).

* Tipo de documento de identidad del comprador: paramétrica del SIAT
  ("sincronizarParametricaTipoDocumentoIdentidad"). Los códigos 1 = CI y 5 = NIT se
  comprobaron en la librería abierta go-siat; 2 (CEX), 3 (PAS) y 4 (OD) son los conocidos de la
  paramétrica pero NO se pudieron leer de una fuente oficial: verificar.
* Comprador no identificado: RND 102100000011, art. 25 (citado por fuente secundaria,
  boliviaimpuestos.com): hasta Bs 1.000 se consigna "S/N" (o "sin nombre") y NIT/CI 0; por encima
  la nominatividad es obligatoria. El código 99002 con "Control Tributario" es SOLO para
  procedimientos de control del SIN (RND 102000000017, fuente oficial): no usarlo en ventas
  normales. Los valores por defecto son configurables por compañía.
* Motivos de anulación: paramétrica del SIAT ("sincronizarParametricaMotivoAnulacion"). Se cargan
  como datos editables (modelo l10n_bo.siat.cancel.reason) porque no se pudo leer la lista
  oficial vigente.
* Plazo de anulación: hasta el día 9 del mes siguiente a la emisión (RND 102100000011 art. 38,
  mencionado en la RND 102600000025 de 13-jul-2026, fuente oficial). Configurable.
"""

SIAT_MODES = [
    ('portal_web', 'Portal Web del SIN (Facturación en Línea, registro manual)'),
    ('provider', 'Proveedor certificado (API)'),
    ('none', 'Aún no habilitada (ventas sin datos SIAT)'),
]

SALE_DOCS = [
    ('siat', 'Factura (SIAT)'),
    ('no_invoice', 'Venta sin factura'),
]

SIAT_STATES = [
    ('not_applicable', 'No aplica'),
    ('to_send', 'Por registrar / enviar'),
    ('accepted', 'Aceptada (válida)'),
    ('rejected', 'Rechazada'),
    ('cancel_requested', 'Anulación solicitada'),
    ('cancelled', 'Anulada'),
]

# Estados con documento fiscal ya emitido: no se puede restablecer a borrador.
SIAT_ISSUED_STATES = ('accepted', 'cancel_requested', 'cancelled')

BUYER_DOC_TYPES = [
    ('1', 'CI - Cédula de identidad'),
    ('2', 'CEX - Cédula de identidad de extranjero'),
    ('3', 'PAS - Pasaporte'),
    ('4', 'OD - Otro documento de identidad'),
    ('5', 'NIT - Número de identificación tributaria'),
]
BUYER_DOC_CI = '1'
BUYER_DOC_NIT = '5'

CUF_CHECKS = [
    ('strict', 'Estricta: el CUF debe decodificarse y coincidir con el NIT y el número'),
    ('decodable', 'Si se puede decodificar, debe coincidir con el NIT y el número'),
    ('format', 'Solo formato (hexadecimal y longitud)'),
]

# Zona horaria de Bolivia (sin horario de verano): fecha de emisión del CUF y del Libro de Ventas.
BO_TZ = 'America/La_Paz'

# Prefijo de los CUF del simulador: contiene letras no hexadecimales, por lo que nunca
# pasa la validación de un CUF real ni el decodificador.
DEMO_CUF_PREFIX = 'SIMULADO'
