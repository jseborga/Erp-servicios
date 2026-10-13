# Part of ERP Servicios Spa. License LGPL-3.
from . import models
from . import tools
from . import wizard


def _l10n_bo_purchase_post_init(env):
    """Activa la validación en las compañías con plan boliviano y deja fuera del Libro de
    Compras las facturas ya registradas antes del módulo (sin datos fiscales)."""
    env['res.company'].search([('chart_template', '=', 'bo')]).write({'l10n_bo_purchase_check': True})
    env.cr.execute("""
        UPDATE account_move
           SET l10n_bo_doc_type = NULL, l10n_bo_purchase_type = NULL
         WHERE state != 'draft'
           AND l10n_bo_invoice_number IS NULL
           AND l10n_bo_cuf IS NULL
           AND l10n_bo_auth_number IS NULL
    """)
