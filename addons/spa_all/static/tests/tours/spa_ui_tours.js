/* Part of ERP Servicios Spa. License LGPL-3. */
// Recorridos de humo de la interfaz por rol (se ejecutan desde spa_all/tests/test_ui_tours.py).
// Usan los xmlid de los menús (no los textos) para no depender del idioma del usuario.
// Cualquier error de JavaScript o del servidor durante el recorrido hace fallar la prueba.
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

const tours = registry.category("web_tour.tours");

function openApp(xmlid) {
    return [
        stepUtils.showAppsMenuItem(),
        { trigger: `.o_app[data-menu-xmlid='${xmlid}']`, run: "click" },
    ];
}

/** Abre un ítem del menú superior: sección (desplegable) y luego el ítem. */
function openMenu(sectionXmlid, itemXmlid) {
    return [
        { trigger: `.o_menu_sections [data-menu-xmlid='${sectionXmlid}']`, run: "click" },
        { trigger: `.o-dropdown--menu [data-menu-xmlid='${itemXmlid}']`, run: "click" },
    ];
}

const noErrorDialog = {
    content: "sin diálogos de error",
    trigger: "body:not(:has(.o_error_dialog))",
};

tours.add("spa_ui_reception", {
    url: "/odoo",
    steps: () => [
        ...openApp("spa_base.spa_menu_root"),
        ...openMenu("spa_base.spa_menu_operations", "spa_access.spa_menu_live"),
        { content: "aforo en vivo: tarjeta de cada espacio", trigger: ".o_kanban_record:contains('Piscina')" },
        {
            content: "registrar ingreso desde la tarjeta",
            trigger: ".o_kanban_record:contains('Piscina') button:contains('Registrar ingreso')",
            run: "click",
        },
        { content: "asistente de ingreso", trigger: ".modal .o_form_view div[name='space_id']" },
        { trigger: ".modal .modal-footer button:contains('Cerrar')", run: "click" },
        { trigger: "body:not(:has(.modal))" },
        // Ingreso de una socia a la sauna (acceso libre): notificación y el asistente se reabre
        // para el siguiente (acción anidada «next», que antes rompía el cliente web).
        {
            trigger: ".o_kanban_record:contains('Sauna') button:contains('Registrar ingreso')",
            run: "click",
        },
        { trigger: ".modal div[name='partner_id'] input", run: "edit Ana Rojas" },
        { trigger: ".o-autocomplete--dropdown-menu .dropdown-item:contains('Ana Rojas')", run: "click" },
        { trigger: ".modal .modal-footer button[name='action_check_in']", run: "click" },
        { content: "ingreso registrado", trigger: ".o_notification:contains('Ana Rojas')" },
        { content: "asistente listo para el siguiente", trigger: ".modal .o_form_view div[name='space_id']" },
        // Pase diario de un visitante: abre el cobro del pase.
        { trigger: ".modal div[name='partner_id'] input", run: "edit Turista UI" },
        { trigger: ".o-autocomplete--dropdown-menu .dropdown-item:contains('Turista UI')", run: "click" },
        // Sin membresía vigente el asistente marca solo «Pase diario».
        { content: "pase diario propuesto", trigger: ".modal div[name='day_pass'] input:checked" },
        { content: "aviso de pase diario", trigger: ".modal .alert-info:contains('Pase diario')" },
        { trigger: ".modal .modal-footer button[name='action_check_in']", run: "click" },
        { content: "cobro del pase diario", trigger: ".modal .o_form_view div[name='method']" },
        { trigger: ".modal .modal-footer button:contains('Descartar')", run: "click" },
        { trigger: "body:not(:has(.modal))" },
        ...openMenu("spa_base.spa_menu_operations", "spa_booking.spa_menu_booking_quick"),
        { content: "reserva rápida", trigger: ".modal .o_form_view div[name='service_id']" },
        { trigger: ".modal .modal-footer button:contains('Cerrar')", run: "click" },
        { trigger: "body:not(:has(.modal))" },
        ...openMenu("spa_base.spa_menu_operations", "spa_booking.spa_menu_booking"),
        { content: "agenda", trigger: ".o_calendar_view, .o_list_view" },
        ...openMenu("spa_base.spa_menu_members", "spa_membership.spa_menu_membership"),
        { content: "membresías", trigger: ".o_list_view .o_data_row:contains('Ana Rojas') td.o_data_cell", run: "click" },
        { content: "ficha de la membresía", trigger: ".o_form_view .o_notebook" },
        noErrorDialog,
    ],
});

tours.add("spa_ui_cashier", {
    url: "/odoo",
    steps: () => [
        ...openApp("spa_base.spa_menu_root"),
        ...openMenu("spa_base.spa_menu_operations", "spa_billing.spa_menu_payment_request"),
        { content: "pagos por validar", trigger: ".o_list_view .o_data_row:contains('Bruno Salinas') td.o_data_cell", run: "click" },
        { content: "botón validar", trigger: ".o_form_view .o_form_statusbar button[name='action_validate']" },
        noErrorDialog,
    ],
});

tours.add("spa_ui_manager", {
    url: "/odoo",
    steps: () => [
        ...openApp("spa_base.spa_menu_root"),
        ...openMenu("spa_base.spa_menu_reporting", "spa_reports.spa_menu_report_dashboard"),
        { content: "resumen del spa", trigger: ".o_form_view button[name='action_view_inside']" },
        ...openMenu("spa_base.spa_menu_reporting", "spa_reports.spa_menu_report_area_mis"),
        { content: "estado de resultados por área (MIS)", trigger: ".oe_mis_builder_content table" },
        ...openMenu("spa_base.spa_menu_reporting", "spa_reports.spa_menu_report_area_analytic"),
        { content: "apuntes analíticos por área", trigger: ".o_pivot_view, .o_graph_view, .o_list_view" },
        ...openMenu("spa_base.spa_menu_config", "spa_membership.spa_menu_plan"),
        { trigger: ".o_data_row:contains('Premium') td.o_data_cell, .o_kanban_record:contains('Premium')", run: "click" },
        { content: "ficha del plan", trigger: ".o_form_view .o_notebook" },
        noErrorDialog,
    ],
});

tours.add("spa_ui_marketing", {
    url: "/odoo",
    steps: () => [
        ...openApp("spa_base.spa_menu_root"),
        ...openMenu("spa_crm.spa_menu_crm", "spa_crm.spa_menu_acquisition"),
        { content: "embudo de captación", trigger: ".o_kanban_renderer .o_kanban_group" },
        ...openMenu("spa_crm.spa_menu_crm", "spa_crm.spa_menu_courtesy_pass"),
        { content: "pases de cortesía", trigger: ".o_list_view, .o_kanban_view" },
        ...openMenu("spa_crm.spa_menu_crm", "spa_crm.spa_menu_conversion"),
        { content: "conversión por fuente", trigger: ".o_pivot_view, .o_graph_view" },
        noErrorDialog,
    ],
});

tours.add("spa_ui_accountant", {
    url: "/odoo/action-l10n_bo_purchase.l10n_bo_purchase_book_action",
    steps: () => [
        { content: "libro de compras", trigger: ".o_list_view, .o_pivot_view" },
        { trigger: ".o_main_navbar" },
        noErrorDialog,
    ],
});

tours.add("spa_ui_portal", {
    url: "/my/spa",
    steps: () => [
        { content: "mi membresía", trigger: ".o_spa_portal" },
        { trigger: ".o_spa_nav a[href='/my/spa/book']", run: "click", expectUnloadPage: true },
        { content: "reservar: franjas del día", trigger: "form.o_spa_book_form" },
        { trigger: ".o_spa_nav a[href='/my/spa/guests']", run: "click", expectUnloadPage: true },
        { content: "invitados", trigger: ".o_spa_nav a.active[href='/my/spa/guests']" },
        { trigger: ".o_spa_nav a[href='/my/spa/classes']", run: "click", expectUnloadPage: true },
        { content: "clases con el menú del socio", trigger: ".o_spa_classes .o_spa_nav a.active[href='/my/spa/classes']" },
    ],
});
