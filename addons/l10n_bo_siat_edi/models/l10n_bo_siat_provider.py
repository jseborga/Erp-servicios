# Part of ERP Servicios Spa. License LGPL-3.
import hashlib

from odoo import api, fields, models
from odoo.exceptions import UserError

from .l10n_bo_siat_catalog import DEMO_CUF_PREFIX


class L10nBoSiatTransientError(Exception):
    """Error de comunicación con el proveedor (red, tiempo de espera, servicio caído).

    La factura queda "Por registrar / enviar" y la tarea programada reintenta. Un proveedor real
    debe lanzarla para los errores que conviene reintentar; los rechazos del SIN se devuelven como
    resultado con ``state = 'rejected'``.
    """


class L10nBoSiatProvider(models.Model):
    """Proveedor de facturación electrónica SIAT (conector por API).

    Contrato independiente del proveedor. Cada tipo implementa tres métodos que reciben la
    factura (``account.move``) y devuelven un ``dict``:

    * ``_siat_emit_<tipo>(move)`` → ``{'state': 'accepted' | 'rejected' | 'pending',
      'number': str, 'cuf': str, 'emission_date': datetime UTC, 'message': str}``
    * ``_siat_cancel_<tipo>(move, reason_code)`` → ``{'state': 'cancelled' | 'cancel_requested'
      | 'rejected', 'message': str}``
    * ``_siat_status_<tipo>(move)`` → ``{'state': 'accepted' | 'cancelled' | 'rejected' |
      'pending', 'message': str}``

    Errores de comunicación: lanzar :class:`L10nBoSiatTransientError` (se reintenta).

    Para agregar un proveedor real (cuando exista contrato y credenciales) cree un módulo que
    herede este modelo::

        class L10nBoSiatProvider(models.Model):
            _inherit = 'l10n_bo.siat.provider'

            provider_type = fields.Selection(
                selection_add=[('acme', 'ACME (certificado)')], ondelete={'acme': 'set default'})

            def _siat_emit_acme(self, move):
                payload = move._l10n_bo_siat_payload()
                ...  # llamada HTTP con self.endpoint y las credenciales
                return {'state': 'accepted', 'number': ..., 'cuf': ..., 'emission_date': ..., 'message': ...}

    **Hoy solo existe el tipo "demo" (simulador)**: no se comunica con nadie y sus documentos NO
    son válidos ante el SIN.
    """
    _name = 'l10n_bo.siat.provider'
    _description = 'Proveedor de facturación SIAT'
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, index=True, default=lambda self: self.env.company)
    provider_type = fields.Selection(
        [('demo', 'Simulador – NO válido ante el SIN')], string='Tipo de proveedor', required=True, default='demo',
        help='Conector a usar. Solo existe el simulador: genera números y CUF ficticios para capacitación '
             'y pruebas. Un proveedor certificado real se agrega con un módulo adicional cuando exista el contrato.')
    is_simulated = fields.Boolean(string='Simulado', compute='_compute_is_simulated')
    sandbox = fields.Boolean(
        string='Ambiente de pruebas (piloto)', default=True,
        help='Usar el ambiente de pruebas del proveedor / piloto del SIN.')
    emit_on_post = fields.Boolean(
        string='Emitir al validar', default=True,
        help='Si está marcado, la factura se envía al proveedor al validarla. Si no, solo la tarea '
             'programada "SIAT: reintentar envíos" la envía.')
    endpoint = fields.Char(string='URL del servicio', help='Dirección base de la API del proveedor.')
    username = fields.Char(string='Usuario', groups='base.group_system')
    api_key = fields.Char(string='Clave / API key', groups='base.group_system')
    api_secret = fields.Char(string='Secreto', groups='base.group_system')
    branch_code = fields.Integer(string='Código de sucursal', default=0, help='Código de sucursal registrado en el SIN (0 = casa matriz).')
    pos_code = fields.Integer(string='Código de punto de venta', default=0)
    sector_code = fields.Integer(
        string='Documento sector', default=1,
        help='Documento sector del SIN para las facturas (1 = compra-venta). Verificar con el proveedor el '
             'sector adecuado para servicios y restaurante.')
    demo_last_number = fields.Integer(
        string='Último número simulado', default=0, copy=False,
        help='Contador de facturas del simulador.')
    note = fields.Text(string='Notas')

    @api.depends('provider_type')
    def _compute_is_simulated(self):
        for provider in self:
            provider.is_simulated = provider.provider_type == 'demo'

    @api.model
    def _l10n_bo_create_demo(self, company):
        """Simulador para capacitación (uno por compañía)."""
        existing = self.with_context(active_test=False).search(
            [('company_id', '=', company.id), ('provider_type', '=', 'demo')], limit=1)
        if existing:
            return existing
        return self.create({
            'name': self.env._('Simulador SIAT (NO válido ante el SIN)'),
            'provider_type': 'demo',
            'company_id': company.id,
            'note': self.env._(
                'Genera números y CUF ficticios con el prefijo %s. Solo para capacitación y pruebas: '
                'los documentos NO tienen validez ante el SIN.', DEMO_CUF_PREFIX),
        })

    # ------------------------------------------------------------------
    # Contrato (despacho por tipo)
    # ------------------------------------------------------------------
    def _siat_dispatch(self, operation, move, **kwargs):
        self.ensure_one()
        method = getattr(self, '_siat_%s_%s' % (operation, self.provider_type), None)
        if not method:
            raise UserError(self.env._(
                'El proveedor "%(provider)s" (tipo %(type)s) no tiene implementada la operación "%(op)s". '
                'Instale el conector del proveedor o cambie la modalidad de facturación.',
                provider=self.name, type=self.provider_type, op=operation))
        return method(move, **kwargs)

    def _siat_emit(self, move):
        """Emite la factura ``move`` ante el SIN a través del proveedor."""
        return self._siat_dispatch('emit', move)

    def _siat_cancel(self, move, reason_code):
        """Solicita la anulación de ``move`` con el código de motivo de la paramétrica del SIN."""
        return self._siat_dispatch('cancel', move, reason_code=reason_code)

    def _siat_status(self, move):
        """Consulta el estado de ``move`` en el SIN."""
        return self._siat_dispatch('status', move)

    # ------------------------------------------------------------------
    # Simulador (tipo 'demo') — NO válido ante el SIN
    # ------------------------------------------------------------------
    def _siat_demo_cuf(self, move, number):
        """CUF ficticio y determinista: prefijo SIMULADO + 40 hexadecimales derivados de la
        compañía, la factura y el número. Nunca supera la validación de un CUF real."""
        seed = '%s|%s|%s|%s' % (move.company_id.id, move.id, move.name, number)
        return DEMO_CUF_PREFIX + hashlib.sha256(seed.encode()).hexdigest()[:40].upper()

    def _siat_emit_demo(self, move):
        self.ensure_one()
        if move.l10n_bo_siat_cuf and move.l10n_bo_siat_number:
            number = move.l10n_bo_siat_number
        else:
            self.demo_last_number += 1
            number = str(self.demo_last_number)
        return {
            'state': 'accepted',
            'number': number,
            'cuf': self._siat_demo_cuf(move, number),
            'emission_date': fields.Datetime.now(),
            'message': self.env._('SIMULADO: documento generado por el simulador; NO es válido ante el SIN.'),
        }

    def _siat_cancel_demo(self, move, reason_code):
        self.ensure_one()
        return {
            'state': 'cancelled',
            'message': self.env._('SIMULADO: anulación simulada (motivo %s); no se comunicó al SIN.', reason_code),
        }

    def _siat_status_demo(self, move):
        self.ensure_one()
        state = move.l10n_bo_siat_state
        if state == 'cancel_requested':
            state = 'cancelled'
        elif state not in ('accepted', 'cancelled', 'rejected'):
            state = 'pending'
        return {'state': state, 'message': self.env._('SIMULADO: estado simulado.')}
