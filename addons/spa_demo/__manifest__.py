# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Datos de demostración',
    'version': '19.0.1.0.0',
    'summary': 'Opcional: carga un spa ficticio con seis semanas de operación (socios, reservas, cobros, CRM, '
               'POS, compras, fondo fijo, eventos y clases) para presentaciones y capacitación.',
    'description': """
Spa - Datos de demostración
===========================

**Solo para bases de demostración o capacitación. NO lo instale en la base de producción.**

Al instalarlo (después de ``spa_all``) crea un spa ficticio, «Spa Demo Bolivia», que opera desde
hace unas seis semanas hasta **hoy** (las fechas se calculan desde el día de la instalación, en hora
de La Paz). Todo se registra con los métodos reales del sistema y con el usuario de cada rol, como
si el personal hubiera trabajado esos días: la contabilidad, los saldos de los socios, el CRM y los
reportes quedan consistentes.

Contenido
---------
* Empresa «Spa Demo Bolivia» (NIT ficticio), QR de cobro FICTICIO (dice «no pagar»), cuenta bancaria
  ficticia y facturación SIAT con el **simulador** (las facturas dicen «SIMULADO»: no son válidas
  ante el SIN).
* 25 socios en todos los estados: activos (mensual, trimestral, anual con descuento y anual en
  3 cuotas), en gracia, suspendidos, vencido, cancelado, uno congelado, uno con bajada de plan
  programada, uno que subió de plan y un alta web por pagar.
* Reservas de piscina, jacuzzi y masajes de las últimas seis semanas y de los próximos siete días,
  con ingresos por QR, salidas, cancelaciones a tiempo y tardías y ausencias (no-show); ingresos al
  sauna, invitados con free pass y con tarifa, pases de cortesía (emitidos, canjeados y vencidos).
* CRM: prospectos de Instagram, Facebook, TikTok, WhatsApp, web, referidos, eventos e invitados en
  todo el embudo (incluidos ganados y perdidos) y oportunidades de retención (uso bajo, mora,
  suspensión, ex-socio).
* Cobros: pagos validados y por validar (con foto del comprobante), renovaciones pendientes,
  escalera de cobranza con su bitácora, cuotas, devengo mensual de planes prepagados.
* Restaurante y cafetería: dos sesiones cerradas del POS con unas 40 órdenes (efectivo, QR, cargo a
  la cuenta del socio) y descuentos de socio.
* Compras: 6 facturas de proveedor con datos SIAT (CUF válido / dosificación) y 2 compras sin factura
  con retención (al proveedor y asumida); fondo fijo con una rendición aprobada y otra por aprobar.
* Alquiler de ambientes: un evento realizado (facturado, garantía devuelta) y uno confirmado;
  clases de natación activas con sesiones, paquetes e inscripciones.

Usuarios de la demo (contraseña: ``demo``)
------------------------------------------
* Personal: ``gerente.demo`` (gerente, con Ajustes y Contabilidad), ``recepcion.demo``,
  ``caja.demo``, ``terapeuta.demo``, ``instructor.demo``, ``marketing.demo``, ``compras.demo``,
  ``contador.demo``, ``custodio.demo`` (caja chica) y ``mesero.demo`` (POS).
* Socios en la web (/my/spa): ``ana.demo``, ``bruno.demo``, ``carla.demo`` y ``yolanda.demo``
  (alta web pendiente de pago).

**Seguridad:** son usuarios con una contraseña conocida. Elimínelos o cambie sus contraseñas antes
de usar la base con datos reales (mejor aún: no use una base de demostración en producción).

Desinstalación
--------------
La demo es «historia» contable: desinstalar el módulo **no borra** las operaciones (facturas,
asientos, pagos), porque la contabilidad no se borra. Al desinstalarlo se **archivan los usuarios de
la demo** (ya no pueden ingresar). Para empezar de cero, cree una base nueva sin este módulo.

Notas técnicas
--------------
* Se carga una sola vez y solo en una base sin membresías ni asientos publicados.
* Las operaciones del pasado se ejecutan con la hora simulada (``freezegun``, dependencia de
  Odoo 19). Instálelo desde la línea de comandos o en una base sin otros usuarios conectados.
* Los WhatsApp se generan con el proveedor «enlace wa.me» (no se envía nada) y los correos de
  notificación de la carga quedan cancelados en la cola de salida.
* La carga tarda entre uno y dos minutos (unas 700 operaciones). Las facturas de consumo del POS
  se crean sin PDF: se genera al imprimirlas o enviarlas.
* Verificación: ``scripts/verify_demo.sh <config> <base> [puerto]`` (asientos cuadrados, estados,
  indicadores del tablero e ingreso al portal por HTTP) y ``--test-tags /spa_demo``.
* Las pruebas de los demás módulos suponen una compañía vacía: ejecútelas en una base sin la demo.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_all'],
    'data': [],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'application': False,
    'auto_install': False,
    'installable': True,
    'license': 'LGPL-3',
}
