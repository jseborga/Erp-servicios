# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Alquiler de ambientes y clases',
    'version': '19.0.1.0.0',
    'summary': 'Alquiler de espacios para eventos (exclusivo o parcial) con garantía, y clases recurrentes '
               '(natación, aquagym) con instructor, inscripciones y control de aforo',
    'description': """
Alquiler de ambientes y clases
==============================
* **Alquileres y eventos** (``spa.rental``): cliente, evento, espacio, horario, modo exclusivo
  (bloquea todo el aforo) o parcial (N cupos), líneas de precio, garantía. Al confirmar valida
  la disponibilidad (reservas, ingresos, clases y otros alquileres, horario y cierres) y reserva
  los cupos del espacio: las franjas de los socios se muestran llenas o reducidas y las reservas
  e ingresos se rechazan con «Reservado para evento: …».
* **Factura en borrador** que se valida al cobrar o al terminar el evento (Ley 843 art. 4 inc. b):
  ingreso 410160, área analítica «Eventos, clases y alquileres», IVA + IT.
* **Garantía** como cobro separado a 216200 (garantías recibidas), con devolución o aplicación
  a daños después del evento.
* **Clases recurrentes** (``spa.class.template``): servicio, instructor, días, hora, cupo y
  precio por sesión o paquete. Un proceso diario genera las sesiones (``spa.class.session``)
  sin duplicar; cada sesión reserva su cupo en el espacio y ocupa al instructor.
* **Inscripciones** (``spa.class.enrollment``): con la membresía (descuenta el saldo del plan)
  o con factura por sesión/paquete; asistencia por check-in; la cancelación de una sesión avisa
  a los inscritos y devuelve sesiones o emite la nota de crédito.
* CRM: cada cotización de alquiler crea o vincula una oportunidad (fuente «Evento»).
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_billing', 'spa_access', 'spa_crm', 'portal'],
    'data': [
        'security/spa_rental_security.xml',
        'security/ir.model.access.csv',
        'data/spa_rental_data.xml',
        'data/spa_rental_business_data.xml',
        'wizard/spa_rental_payment_views.xml',
        'wizard/spa_rental_deposit_views.xml',
        'wizard/spa_class_wizard_views.xml',
        'views/spa_rental_views.xml',
        'views/spa_class_views.xml',
        'views/spa_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_rental_menus.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
