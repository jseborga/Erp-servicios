# Part of ERP Servicios Spa. License LGPL-3.
{
    'name': 'Spa - Reportes de gestión',
    'version': '19.0.1.0.0',
    'summary': 'Ocupación por espacio y hora, uso y rentabilidad de los planes, ingresos, socios y mora, '
               'resultado por área y tablero resumen del spa',
    'description': """
Reportes de gestión del spa (solo lectura, con vistas de lista, pivote y gráfico):

* **Resumen**: tablero con los indicadores del día (personas dentro / aforo, reservas de hoy, socios
  activos, en gracia y suspendidos, pagos por validar, ingreso mensual recurrente, ingresos del mes,
  socios nuevos, prospectos y conversión). Cada indicador abre su reporte detallado.
* **Ocupación por espacio**: por espacio, fecha local y hora: aforo, cupos reservados, ingresos
  registrados, personas dentro y % de ocupación (incluye las horas vacías del horario de atención).
* **Uso de los planes**: saldo del plan + traslado, usados, sin usar y % de uso por socio, servicio y mes.
* **Rentabilidad por plan**: ingreso mensual equivalente, costo de servir (consumos × costo del
  producto del servicio), margen y usos por socio-mes.
* **Ingresos del spa**: facturado y devengado por mes, tipo de cobro, plan y categoría; incluye el
  devengo de planes prepagados y las ventas del POS sin factura individual.
* **Socios y mora**: membresías por estado y plan, saldo por cobrar, vencido, días de mora y antigüedad.
* **Rentabilidad por área**: apuntes analíticos del plan «Áreas del negocio» por sección del estado de
  resultados, y la plantilla MIS Builder «Estado de resultados por área» con una columna por área.

Las fechas se calculan en la zona horaria del spa (parámetro ``spa.timezone``) en cada consulta.
""",
    'author': 'ERP Servicios Spa',
    'website': 'https://github.com/jseborga/erp-servicios',
    'category': 'Services/Spa',
    'depends': ['spa_crm', 'spa_pos', 'spa_billing', 'spa_access', 'l10n_bo_spa', 'mis_builder'],
    'data': [
        'security/ir.model.access.csv',
        'security/spa_reports_security.xml',
        'views/spa_report_occupancy_views.xml',
        'views/spa_report_plan_views.xml',
        'views/spa_report_revenue_views.xml',
        'views/spa_report_member_views.xml',
        'views/spa_report_area_views.xml',
        'views/spa_report_dashboard_views.xml',
        'data/mis_report_area_data.xml',
        'views/spa_reports_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
