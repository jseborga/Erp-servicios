# Part of ERP Servicios Spa. License LGPL-3.
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MENU_PRODUCTS = (
    'product_coffee', 'product_cappuccino', 'product_juice', 'product_saltena',
    'product_salad', 'product_trout', 'product_pique_macho', 'product_water',
)

# Mesas del salón: (número, posición horizontal, posición vertical)
RESTAURANT_TABLES = [
    (number, 100 + 170 * ((number - 1) % 4), 100 + 170 * ((number - 1) // 4))
    for number in range(1, 9)
]


class PosConfig(models.Model):
    _inherit = 'pos.config'

    spa_analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Área analítica', check_company=True,
        help='Las ventas de este punto de venta (asiento de cierre y facturas) se registran en esta área '
             'para medir la rentabilidad del restaurante y de la cafetería.')
    spa_member_pricing = fields.Boolean(
        'Precios de socio', default=True,
        help='Agrega las listas de precios de los planes del spa a este punto de venta y verifica al cobrar '
             'que solo se apliquen a socios vigentes del plan correspondiente.')

    def write(self, vals):
        res = super().write(vals)
        if vals.get('spa_member_pricing'):
            self._spa_sync_member_pricelists()
        return res

    def _spa_analytic_distribution(self):
        self.ensure_one()
        if not self.spa_analytic_account_id:
            return {}
        return {str(self.spa_analytic_account_id.id): 100.0}

    # ------------------------------------------------------------------
    # Listas de precios de socios
    # ------------------------------------------------------------------
    def _spa_sync_member_pricelists(self):
        """Hace disponibles en el POS la lista pública y las listas de los planes (solo agrega)."""
        public = self.env.ref('spa_membership.pricelist_public', raise_if_not_found=False)
        Plan = self.env['spa.plan'].sudo()
        for config in self.sudo().filtered('spa_member_pricing'):
            company = config.company_id

            def usable(pricelist, company=company, config=config):
                return pricelist.active and pricelist.company_id in (company, company.browse()) \
                    and pricelist.currency_id == config.currency_id  # sin compañía o de la misma

            pricelists = Plan.search([('company_id', '=', company.id), ('pricelist_id', '!=', False)]) \
                .pricelist_id.filtered(usable)
            if public and usable(public):
                pricelists |= public
            vals = {}
            if not config.use_pricelist:
                vals['use_pricelist'] = True
            missing = pricelists - config.available_pricelist_ids
            if config.pricelist_id and config.pricelist_id not in config.available_pricelist_ids:
                missing |= config.pricelist_id
            if missing:
                vals['available_pricelist_ids'] = [fields.Command.link(p.id) for p in missing]
            if not config.pricelist_id and public and usable(public):
                vals['pricelist_id'] = public.id
            if vals:
                config.write(vals)

    # ------------------------------------------------------------------
    # Configuración inicial: Restaurante y Cafetería
    # ------------------------------------------------------------------
    @api.model
    def _spa_ref_name(self, name, company):
        main = self.env.ref('base.main_company', raise_if_not_found=False)
        return f'spa_pos.{name}' if main and company == main else f'spa_pos.{name}_{company.id}'

    @api.model
    def _spa_ref(self, name, company):
        return self.env.ref(self._spa_ref_name(name, company), raise_if_not_found=False)

    @api.model
    def _spa_set_ref(self, name, company, record):
        self.env['ir.model.data']._update_xmlids([{
            'xml_id': self._spa_ref_name(name, company),
            'record': record,
            'noupdate': True,
        }])

    @api.model
    def _spa_get_config(self, kind, company=None):
        """Punto de venta del spa: ``kind`` = 'restaurant' o 'cafe'."""
        return self._spa_ref(f'pos_config_{kind}', company or self.env.company) or self.browse()

    @api.model
    def _spa_setup_all_companies(self):
        for company in self.env['res.company'].sudo().search([('chart_template', '=', 'bo')]):
            self._spa_setup_company(company)

    @api.model
    def _spa_setup_company(self, company):
        """Crea (si faltan) los puntos de venta, métodos de pago y mesas del spa. Idempotente."""
        self = self.sudo().with_company(company)
        if company.chart_template != 'bo':
            _logger.info('spa_pos: %s no usa el plan boliviano; no se crean puntos de venta.', company.name)
            return self.browse()
        self._spa_setup_menu_taxes(company)
        bank_method = self._spa_ensure_bank_method(company)
        member_method = self._spa_ensure_member_method(company)
        Analytic = self.env['account.analytic.account']
        configs = self.browse()
        for kind, name, cash_code, area in (
            ('restaurant', self.env._('Restaurante'), 'CRES', 'l10n_bo_spa.analytic_area_restaurante'),
            ('cafe', self.env._('Cafetería'), 'CCAF', 'l10n_bo_spa.analytic_area_cafeteria'),
        ):
            config = self._spa_get_config(kind, company)
            if not config:
                cash_method = self._spa_ensure_cash_method(kind, name, cash_code, company)
                vals = {
                    'name': name,
                    'company_id': company.id,
                    'payment_method_ids': [fields.Command.set((cash_method | bank_method | member_method).ids)],
                    'spa_analytic_account_id': (self.env.ref(area, raise_if_not_found=False) or Analytic).id,
                    'spa_member_pricing': True,
                }
                vals.update(self._spa_kind_values(kind, company))
                config = self.create(vals)
                self._spa_set_ref(f'pos_config_{kind}', company, config)
                _logger.info('spa_pos: punto de venta "%s" creado para %s.', name, company.name)
            configs |= config
        configs._spa_sync_member_pricelists()
        return configs

    @api.model
    def _spa_kind_values(self, kind, company):
        cafe_categ = self.env.ref('spa_pos.pos_category_cafe', raise_if_not_found=False)
        if kind == 'restaurant':
            floor = self.env['restaurant.floor'].create({
                'name': self.env._('Salón principal'),
                'background_color': '#f5f3ef',
                'table_ids': [fields.Command.create({
                    'table_number': number,
                    'seats': 4,
                    'shape': 'square',
                    'position_h': pos_h,
                    'position_v': pos_v,
                    'width': 110,
                    'height': 110,
                }) for number, pos_h, pos_v in RESTAURANT_TABLES],
            })
            self._spa_set_ref('floor_main', company, floor)
            return {
                'module_pos_restaurant': True,
                'floor_ids': [fields.Command.set(floor.ids)],
                'iface_splitbill': True,
                'iface_printbill': True,
                'default_screen': 'tables',
            }
        return {
            'module_pos_restaurant': False,
            'limit_categories': bool(cafe_categ),
            'iface_available_categ_ids': [fields.Command.set(cafe_categ.ids)] if cafe_categ else [],
        }

    @api.model
    def _spa_setup_menu_taxes(self, company):
        """IVA 13 % (incluido) + IT 3 % de la compañía en la carta de ejemplo."""
        taxes = company._spa_sale_taxes()
        if not taxes:
            return
        for name in MENU_PRODUCTS:
            product = self.env.ref(f'spa_pos.{name}', raise_if_not_found=False)
            if not product:
                continue
            missing = taxes - product.taxes_id
            if missing:
                product.taxes_id = [fields.Command.link(tax.id) for tax in missing]

    @api.model
    def _spa_ensure_cash_method(self, kind, name, code, company):
        Journal = self.env['account.journal']
        journal = Journal.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
        code_taken = bool(journal)
        if journal and (journal.type != 'cash' or journal.pos_payment_method_ids):
            journal = Journal  # código ocupado por otro uso: Odoo asigna uno libre
        if not journal:
            journal = Journal.create({
                'name': self.env._('Caja %s', name),
                'type': 'cash',
                'company_id': company.id,
                **({} if code_taken else {'code': code}),
            })
        method = self.env['pos.payment.method'].create({
            'name': self.env._('Efectivo'),
            'journal_id': journal.id,
            'company_id': company.id,
            'sequence': 1,
        })
        self._spa_set_ref(f'pm_cash_{kind}', company, method)
        return method

    @api.model
    def _spa_ensure_bank_method(self, company):
        method = self._spa_ref('pm_qr', company)
        if method:
            return method
        journal = company.spa_payment_journal_id or self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': self.env._('Banco'), 'code': 'BNKQ', 'type': 'bank', 'company_id': company.id})
        chart = self.env['account.chart.template'].with_company(company)
        outstanding = (chart.ref('l10n_bo_spa_1115', raise_if_not_found=False)
                       or chart.ref('account_journal_payment_debit_account_id', raise_if_not_found=False)
                       or company.transfer_account_id)
        method = self.env['pos.payment.method'].create({
            'name': self.env._('QR / Transferencia'),
            'journal_id': journal.id,
            'outstanding_account_id': outstanding.id,
            'company_id': company.id,
            'sequence': 2,
        })
        self._spa_set_ref('pm_qr', company, method)
        return method

    @api.model
    def _spa_ensure_member_method(self, company):
        method = self._spa_ref('pm_member_account', company)
        if method:
            return method
        method = self.env['pos.payment.method'].create({
            'name': self.env._('Cuenta del socio'),
            'journal_id': False,
            'split_transactions': True,
            'spa_member_account': True,
            'company_id': company.id,
            'sequence': 3,
        })
        self._spa_set_ref('pm_member_account', company, method)
        return method
