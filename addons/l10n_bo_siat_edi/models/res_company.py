# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.l10n_bo_purchase.tools import siat

from .l10n_bo_siat_catalog import BUYER_DOC_TYPES, CUF_CHECKS, SIAT_MODES


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_bo_siat_mode = fields.Selection(
        SIAT_MODES, string='Modalidad de facturación', default='portal_web', required=True,
        help='Portal Web del SIN: la caja emite la factura en el sistema gratuito "Facturación en Línea – '
             'Portal Web" del SIN y registra en Odoo el número y el CUF.\n'
             'Proveedor certificado: Odoo envía la factura al proveedor al validarla (hoy solo existe el '
             'simulador, NO válido ante el SIN).\n'
             'Aún no habilitada: las ventas se registran en contabilidad sin datos SIAT.')
    l10n_bo_siat_provider_id = fields.Many2one(
        'l10n_bo.siat.provider', string='Proveedor SIAT', check_company=True,
        help='Conector usado en la modalidad "Proveedor certificado".')
    l10n_bo_siat_user_id = fields.Many2one(
        'res.users', string='Responsable de registrar facturas SIAT',
        domain="[('share', '=', False), ('company_ids', 'in', id)]",
        help='Recibe las actividades "Registrar factura SIAT" y "Revisar emisión SIAT". Si se deja vacío, '
             'se asigna a quien validó la factura (o, en procesos automáticos, al primer usuario de facturación).')
    l10n_bo_siat_cuf_check = fields.Selection(
        CUF_CHECKS, string='Validación del CUF de ventas', default='decodable', required=True,
        help='Cómo se valida el CUF registrado a mano (modalidad Portal Web). El decodificador se verificó con '
             'una implementación abierta y un CUF del ambiente piloto del SIN; si una factura real es '
             'rechazada, use "Solo formato" y reporte el caso.')
    l10n_bo_siat_buyer_doc_type = fields.Selection(
        BUYER_DOC_TYPES, string='Consumidor final: tipo de documento', default='1',
        help='Tipo de documento del comprador que no da sus datos. POR VERIFICAR con el SIN / proveedor.')
    l10n_bo_siat_buyer_number = fields.Char(
        string='Consumidor final: número', default='0',
        help='Número de documento del comprador no identificado. Según la RND 102100000011 art. 25 (fuente '
             'secundaria) se consigna 0 hasta el monto máximo sin nombre. POR VERIFICAR. No use 99002: es solo '
             'para control tributario del SIN.')
    l10n_bo_siat_buyer_name = fields.Char(
        string='Consumidor final: razón social', default='S/N',
        help='"S/N" o "Sin nombre" según la RND 102100000011 art. 25 (fuente secundaria). POR VERIFICAR.')
    l10n_bo_siat_anonymous_max = fields.Monetary(
        string='Monto máximo sin identificar al comprador', default=1000.0, currency_field='currency_id',
        help='Por encima de este monto el comprador debe identificarse (NIT/CI y nombre). Bs 1.000 según la '
             'RND 102100000011 art. 25 (fuente secundaria): POR VERIFICAR. 0 = sin control.')
    l10n_bo_siat_cancel_day = fields.Integer(
        string='Día límite de anulación (mes siguiente)', default=9,
        help='Las facturas pueden anularse hasta este día del mes siguiente a su emisión (RND 102100000011 '
             'art. 38). Después se sigue el procedimiento de la RND 102600000025 ante el SIN. 0 = sin control.')
    l10n_bo_siat_retry_limit = fields.Integer(
        string='Reintentos automáticos de envío', default=5,
        help='Cantidad de intentos fallidos tras los cuales la tarea programada deja de reintentar y asigna una '
             'actividad "Revisar emisión SIAT".')
    l10n_bo_sale_no_invoice_max = fields.Monetary(
        string='Monto máximo por venta sin factura', default=0.0, currency_field='currency_id',
        help='Importe total máximo (Bs) de una venta sin factura. 0 = sin límite.')
    l10n_bo_siat_warning = fields.Text(string='Aviso de facturación SIAT', compute='_compute_l10n_bo_siat_warning')

    @api.depends('l10n_bo_siat_mode', 'vat', 'l10n_bo_siat_provider_id')
    def _compute_l10n_bo_siat_warning(self):
        for company in self:
            company.l10n_bo_siat_warning = '\n'.join(company._l10n_bo_siat_config_warnings()) or False

    def _l10n_bo_siat_config_warnings(self):
        """Avisos de configuración (lista de textos), mostrados en Ajustes y en las facturas."""
        self.ensure_one()
        _ = self.env._
        warnings = []
        mode = self.l10n_bo_siat_mode
        if mode == 'none':
            warnings.append(_(
                'Facturación SIAT no habilitada: las ventas se registran en contabilidad (con IVA e IT) pero sin '
                'factura del SIN. Cuando la compañía esté habilitada, elija la modalidad en Contabilidad > '
                'Configuración > Ajustes > Facturación SIAT (Bolivia).'))
        elif not self._l10n_bo_siat_nit():
            warnings.append(_(
                'Falta el NIT de la compañía: no se podrán registrar ni emitir facturas SIAT. Complételo en '
                'Ajustes > Compañías.'))
        if mode == 'provider':
            if not self.l10n_bo_siat_provider_id:
                warnings.append(_('Modalidad "Proveedor certificado" sin proveedor SIAT configurado.'))
            elif self.l10n_bo_siat_provider_id.is_simulated:
                warnings.append(_(
                    'El proveedor configurado es el SIMULADOR: las facturas NO son válidas ante el SIN. Úselo solo '
                    'para capacitación y pruebas.'))
        return warnings

    def _l10n_bo_siat_nit(self):
        self.ensure_one()
        nit = siat.normalize_nit(self.vat or self.partner_id.vat)
        return nit if nit and nit.isdigit() and nit != '0' else False

    @api.constrains('l10n_bo_siat_mode', 'l10n_bo_siat_provider_id')
    def _check_l10n_bo_siat_provider(self):
        for company in self:
            provider = company.l10n_bo_siat_provider_id
            if provider and provider.company_id != company:
                raise ValidationError(self.env._(
                    'El proveedor SIAT "%(provider)s" pertenece a otra compañía (%(company)s).',
                    provider=provider.name, company=provider.company_id.name))

    def _l10n_bo_siat_check_mode_requirements(self):
        """Requisitos al ELEGIR una modalidad (desde Ajustes). No se aplica al crear compañías para no
        bloquear instalaciones ni pruebas; la falta de NIT se avisa en las facturas."""
        for company in self:
            mode = company.l10n_bo_siat_mode
            if mode in ('portal_web', 'provider') and not company._l10n_bo_siat_nit():
                raise ValidationError(self.env._(
                    'Para la modalidad "%(mode)s" la compañía %(company)s necesita su NIT (solo dígitos). '
                    'Complételo en Ajustes > Compañías y vuelva a guardar.',
                    mode=dict(SIAT_MODES)[mode], company=company.name))
            if mode == 'provider' and not company.l10n_bo_siat_provider_id:
                raise ValidationError(self.env._(
                    'Elija el proveedor SIAT para la modalidad "Proveedor certificado" (por ejemplo el simulador, '
                    'solo para pruebas).'))

    def _l10n_bo_siat_activity_user(self, move=None):
        """Usuario que recibe las actividades de facturación SIAT."""
        self.ensure_one()

        def eligible(user):
            return (
                user and user.active and not user.share and not user._is_superuser()
                and self in user.company_ids and user.has_group('account.group_account_invoice')
            )

        candidates = [self.l10n_bo_siat_user_id, self.env.user]
        if move:
            candidates.insert(1, move.invoice_user_id)
        for user in candidates:
            if eligible(user):
                return user
        group = self.env.ref('account.group_account_invoice')
        users = self.env['res.users'].sudo().search(
            [('all_group_ids', 'in', group.ids), ('share', '=', False), ('company_ids', 'in', self.ids)], order='id')
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        return next((u for u in users if eligible(u)), admin if admin and admin.active else self.env['res.users'])
