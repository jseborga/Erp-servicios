/* Part of ERP Servicios Spa. License LGPL-3. */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * Menú del socio (pastillas desplazables en el celular): muestra la sección actual.
 * Sin esto, en pantallas angostas «Clases» o «Pagar» quedaban fuera de la vista
 * aunque fueran la página abierta.
 */
export class SpaMemberNav extends Interaction {
    static selector = ".o_spa_nav";

    start() {
        const active = this.el.querySelector(".nav-link.active");
        if (active && this.el.scrollWidth > this.el.clientWidth) {
            // scrollLeft (no scrollIntoView) para no mover la página verticalmente.
            this.el.scrollLeft = active.offsetLeft - (this.el.clientWidth - active.offsetWidth) / 2;
        }
    }
}

registry.category("public.interactions").add("spa_portal.member_nav", SpaMemberNav);
