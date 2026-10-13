# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Cobros y mora',
    'version': '19.0.1.0.0',
    'summary': 'Cobros de planes (factura al cobrar), pagos QR por validar, renovación, escalera de cobranza, '
               'cuotas, cambio de plan, cargos, devengo diferido y resultado por área',
    'description': """
Cobros del spa
==============

* **Cobro pendiente → factura al cobrar.** El alta, la renovación, el cambio de plan y el servicio suelto
  nacen en borrador («cobro pendiente», sin documento fiscal) y se emiten cuando caja valida el pago (o,
  en el servicio suelto, al prestarlo si aún no se pagó): en servicios, el hecho imponible del IVA es la
  prestación o el cobro, lo que ocurra primero (Ley 843 art. 4 inc. b). Los cargos del mes (invitados,
  penalidades) se emiten al cerrar el mes. Las renovaciones impagas de membresías vencidas o canceladas
  se anulan solas: nunca generan factura.
* **Pagos por validar** (QR, transferencia, efectivo) con comprobante; caja valida y se registra el pago.
* **Escalera de cobranza** configurable (avisos por WhatsApp y suspensión, una vez por período) además de
  los días de gracia del plan.
* **Planes en cuotas** (6 decimales: cuotas iguales al centavo), aviso y suspensión por cuota vencida y
  reactivación al pagar.
* **Cambio de plan**: subir rige hoy con la diferencia prorrateada; bajar rige desde el próximo período.
* **Devengo** mensual de planes prepagados (215100 → ingresos) con área analítica; se detiene si la
  membresía se cancela o la factura se revierte.
* Caja no valida asientos manuales (solo contador o gerente).
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_booking', 'spa_access', 'spa_messaging', 'account', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_billing_security.xml',
        'data/spa_billing_data.xml',
        'data/spa_dunning_data.xml',
        'views/spa_payment_request_views.xml',
        'views/spa_payment_offer_views.xml',
        'views/spa_membership_views.xml',
        'views/spa_plan_views.xml',
        'views/spa_booking_views.xml',
        'views/spa_access_log_views.xml',
        'views/spa_deferral_views.xml',
        'views/spa_dunning_views.xml',
        'wizard/spa_plan_change_views.xml',
        'views/res_config_settings_views.xml',
        'views/spa_billing_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
