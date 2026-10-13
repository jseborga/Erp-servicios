# Part of ERP Servicios Spa. License LGPL-3.
import logging

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_bo_purchase.tools import siat

from .l10n_bo_siat_catalog import (
    BO_TZ, BUYER_DOC_CI, BUYER_DOC_NIT, BUYER_DOC_TYPES, DEMO_CUF_PREFIX, SALE_DOCS, SIAT_ISSUED_STATES,
    SIAT_MODES, SIAT_STATES,
)

_logger = logging.getLogger(__name__)

GROUP_NO_INVOICE = 'l10n_bo_siat_edi.group_l10n_bo_sale_no_invoice'
ACTIVITY_REGISTER = 'l10n_bo_siat_edi.mail_activity_siat_register'
ACTIVITY_REVIEW = 'l10n_bo_siat_edi.mail_activity_siat_review'

BUYER_FIELDS = (
    'l10n_bo_sale_buyer_doc_type', 'l10n_bo_sale_buyer_number',
    'l10n_bo_sale_buyer_complement', 'l10n_bo_sale_buyer_name',
)
# Datos que no cambian una vez emitido el documento fiscal (solo con anulación).
SIAT_LOCKED_FIELDS = ('l10n_bo_siat_number', 'l10n_bo_siat_cuf', 'l10n_bo_sale_doc') + BUYER_FIELDS


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Documento de venta y comprador
    # ------------------------------------------------------------------
    l10n_bo_sale_doc = fields.Selection(
        SALE_DOCS, string='Documento de venta', compute='_compute_l10n_bo_sale_doc',
        store=True, readonly=False, precompute=True, copy=False, tracking=True,
        help='Factura (SIAT): la venta lleva factura del SIN según la modalidad de la compañía.\n'
             'Venta sin factura: solo usuarios autorizados, con motivo; la venta y sus impuestos (IVA, IT) se '
             'registran igual en contabilidad. Úsela solo en los casos que la norma permita (confirmar con el contador).')
    l10n_bo_sale_buyer_doc_type = fields.Selection(
        BUYER_DOC_TYPES, string='Tipo de documento del comprador', compute='_compute_l10n_bo_sale_buyer',
        store=True, readonly=False, precompute=True, copy=False)
    l10n_bo_sale_buyer_number = fields.Char(
        string='NIT/CI del comprador', compute='_compute_l10n_bo_sale_buyer',
        store=True, readonly=False, precompute=True, copy=False,
        help='Por defecto el NIT/CI del cliente; si no lo tiene, el "consumidor final" de la compañía (0).')
    l10n_bo_sale_buyer_complement = fields.Char(
        string='Complemento', compute='_compute_l10n_bo_sale_buyer',
        store=True, readonly=False, precompute=True, copy=False,
        help='Complemento del CI (solo con tipo de documento CI).')
    l10n_bo_sale_buyer_name = fields.Char(
        string='Razón social del comprador', compute='_compute_l10n_bo_sale_buyer',
        store=True, readonly=False, precompute=True, copy=False)
    l10n_bo_sale_no_invoice_reason = fields.Text(
        string='Motivo de la venta sin factura', copy=False,
        help='Obligatorio. Explique el caso permitido por la norma (confirmado con el contador).')
    l10n_bo_sale_no_invoice_user_id = fields.Many2one(
        'res.users', string='Venta sin factura validada por', readonly=True, copy=False)
    l10n_bo_sale_user_can_no_invoice = fields.Boolean(compute='_compute_l10n_bo_sale_user_can_no_invoice',
                                                      string='Puede registrar ventas sin factura')

    # ------------------------------------------------------------------
    # Datos SIAT
    # ------------------------------------------------------------------
    l10n_bo_siat_state = fields.Selection(
        SIAT_STATES, string='Estado SIAT', readonly=True, copy=False, tracking=True, index=True)
    l10n_bo_siat_mode = fields.Selection(
        SIAT_MODES, string='Modalidad de facturación usada', readonly=True, copy=False,
        help='Modalidad de la compañía al validar el documento.')
    l10n_bo_siat_provider_id = fields.Many2one(
        'l10n_bo.siat.provider', string='Proveedor SIAT', readonly=True, copy=False)
    l10n_bo_siat_simulated = fields.Boolean(
        string='Documento simulado', readonly=True, copy=False,
        help='Emitido por el simulador: NO es válido ante el SIN.')
    l10n_bo_siat_number = fields.Char(string='N.º de factura SIAT', readonly=True, copy=False, tracking=True)
    l10n_bo_siat_cuf = fields.Char(string='CUF de la venta', readonly=True, copy=False, tracking=True,
                                   help='Código Único de Factura asignado en el SIAT.')
    l10n_bo_siat_emission_date = fields.Datetime(string='Fecha y hora de emisión SIAT', readonly=True, copy=False)
    l10n_bo_siat_cancel_reason_id = fields.Many2one(
        'l10n_bo.siat.cancel.reason', string='Motivo de anulación', readonly=True, copy=False)
    l10n_bo_siat_cancel_note = fields.Char(string='Detalle de la anulación', readonly=True, copy=False)
    l10n_bo_siat_cancel_date = fields.Datetime(string='Anulada el', readonly=True, copy=False)
    l10n_bo_siat_cancel_reversal = fields.Boolean(
        string='Reversión por anulación SIAT', readonly=True, copy=False,
        help='Nota de crédito contable creada al anular la factura en el SIAT. No es una nota de crédito-débito fiscal.')
    l10n_bo_siat_attempts = fields.Integer(string='Intentos de envío', readonly=True, copy=False)
    l10n_bo_siat_log = fields.Text(string='Respuestas del proveedor / bitácora SIAT', readonly=True, copy=False)
    l10n_bo_siat_warning = fields.Text(compute='_compute_l10n_bo_siat_warning', string='Aviso SIAT')

    _l10n_bo_siat_cuf_unique = models.UniqueIndex(
        "(company_id, l10n_bo_siat_cuf) WHERE l10n_bo_siat_cuf IS NOT NULL",
        'Ese CUF ya está registrado en otro documento de la compañía: no se puede registrar dos veces la misma factura.',
    )
    _l10n_bo_siat_number_unique = models.UniqueIndex(
        "(company_id, move_type, l10n_bo_siat_number) "
        "WHERE l10n_bo_siat_state = 'accepted' AND l10n_bo_siat_number IS NOT NULL",
        'Ya existe una factura SIAT aceptada con ese número en la compañía.',
    )

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    def _l10n_bo_sale_applies(self):
        self.ensure_one()
        return self.move_type in ('out_invoice', 'out_refund') and self.country_code == 'BO'

    @api.depends('move_type', 'company_id', 'reversed_entry_id')
    def _compute_l10n_bo_sale_doc(self):
        for move in self:
            if not move._l10n_bo_sale_applies():
                move.l10n_bo_sale_doc = False
            elif not move.l10n_bo_sale_doc:
                move.l10n_bo_sale_doc = move.reversed_entry_id.l10n_bo_sale_doc or 'siat'

    def _l10n_bo_sale_buyer_defaults(self):
        """Comprador por defecto: el del documento revertido, el NIT/CI del cliente o el
        "consumidor final" configurado en la compañía."""
        self.ensure_one()
        origin = self.reversed_entry_id
        if origin and origin.l10n_bo_sale_buyer_number:
            return {fname: origin[fname] for fname in BUYER_FIELDS}
        partner = self.partner_id
        commercial = partner.commercial_partner_id
        number = siat.normalize_nit(commercial.vat) if commercial.vat else False
        if number:
            doc_type = partner.l10n_bo_siat_id_type or commercial.l10n_bo_siat_id_type or BUYER_DOC_NIT
            complement = partner.l10n_bo_siat_id_complement or commercial.l10n_bo_siat_id_complement
            return {
                'l10n_bo_sale_buyer_doc_type': doc_type,
                'l10n_bo_sale_buyer_number': number,
                'l10n_bo_sale_buyer_complement': complement if doc_type == BUYER_DOC_CI else False,
                'l10n_bo_sale_buyer_name': commercial.name,
            }
        company = self.company_id
        return {
            'l10n_bo_sale_buyer_doc_type': company.l10n_bo_siat_buyer_doc_type or BUYER_DOC_CI,
            'l10n_bo_sale_buyer_number': company.l10n_bo_siat_buyer_number or '0',
            'l10n_bo_sale_buyer_complement': False,
            'l10n_bo_sale_buyer_name': company.l10n_bo_siat_buyer_name or 'S/N',
        }

    @api.depends('partner_id', 'move_type', 'company_id', 'reversed_entry_id')
    def _compute_l10n_bo_sale_buyer(self):
        for move in self:
            if not move._l10n_bo_sale_applies():
                move.update(dict.fromkeys(BUYER_FIELDS, False))
            elif move.state == 'draft' or not move.l10n_bo_sale_buyer_number:
                move.update(move._l10n_bo_sale_buyer_defaults())

    @api.depends_context('uid')
    def _compute_l10n_bo_sale_user_can_no_invoice(self):
        allowed = self._l10n_bo_sale_user_allowed_no_invoice()
        for move in self:
            move.l10n_bo_sale_user_can_no_invoice = allowed

    @api.model
    def _l10n_bo_sale_user_allowed_no_invoice(self):
        return self.env.su or self.env.user.has_group(GROUP_NO_INVOICE)

    def _l10n_bo_siat_is_anonymous(self, number=None):
        self.ensure_one()
        company = self.company_id
        if number is None:
            number = self.l10n_bo_sale_buyer_number
        number = (number or '').strip()
        return not number or number in ('0', company.l10n_bo_siat_buyer_number or '0')

    def _l10n_bo_siat_anonymous_over_limit(self, number=None):
        self.ensure_one()
        limit = self.company_id.l10n_bo_siat_anonymous_max
        return (
            limit > 0 and self._l10n_bo_siat_is_anonymous(number)
            and self.company_currency_id.compare_amounts(abs(self.amount_total_signed), limit) > 0
        )

    @api.depends('company_id', 'move_type', 'state', 'l10n_bo_sale_doc', 'l10n_bo_siat_state', 'l10n_bo_siat_mode',
                 'l10n_bo_siat_log', 'l10n_bo_siat_attempts', 'l10n_bo_sale_buyer_number', 'amount_total_signed',
                 'l10n_bo_siat_cancel_reversal')
    def _compute_l10n_bo_siat_warning(self):
        for move in self:
            move.l10n_bo_siat_warning = '\n'.join(move._l10n_bo_siat_warnings()) or False

    def _l10n_bo_siat_warnings(self):
        self.ensure_one()
        if not self._l10n_bo_sale_applies() or self.l10n_bo_siat_cancel_reversal:
            return []
        _ = self.env._
        company = self.company_id
        state = self.l10n_bo_siat_state
        messages = []
        if self.l10n_bo_sale_doc == 'no_invoice':
            return [_(
                'Venta sin factura: se registra en contabilidad con sus impuestos (IVA, IT) pero no se emite factura '
                'del SIN. Úsela solo en los casos que la norma permita (confirmar con el contador).')]
        if self.l10n_bo_sale_doc != 'siat':
            return []
        if self.l10n_bo_siat_mode == 'none' and state == 'not_applicable':
            messages.append(_(
                'Venta registrada SIN factura del SIN: la compañía no estaba habilitada para facturar en el SIAT al '
                'validar este documento.'))
        if self.state == 'draft' or state in ('to_send', 'rejected') or company.l10n_bo_siat_mode == 'none':
            messages += company._l10n_bo_siat_config_warnings()
        if state not in SIAT_ISSUED_STATES and self.l10n_bo_siat_mode != 'none' and self._l10n_bo_siat_anonymous_over_limit():
            messages.append(_(
                'La venta supera %s y el comprador no está identificado: el SIN exige NIT/CI y nombre por encima de ese '
                'monto (por verificar con el contador). Complete los datos del comprador.',
                company.currency_id.format(company.l10n_bo_siat_anonymous_max)))
        if state == 'to_send' and self.l10n_bo_siat_mode == 'portal_web':
            messages.append(_(
                'Pendiente: emita la factura en el Portal Web del SIN (Facturación en Línea) con los mismos datos del '
                'comprador y montos, y registre aquí el número y el CUF con el botón "Registrar datos SIAT". Si ya la '
                'emitió, regístrela antes de modificar o cancelar este documento.'))
        elif state == 'to_send' and self.l10n_bo_siat_mode == 'provider':
            messages.append(_(
                'Pendiente de envío al proveedor SIAT (intentos fallidos: %s). Se reintenta automáticamente; '
                'también puede usar "Enviar al SIAT". Vea la bitácora en la pestaña SIAT.', self.l10n_bo_siat_attempts))
        elif state == 'rejected':
            messages.append(_(
                'Rechazada: corrija los datos indicados en la bitácora (pestaña SIAT) y vuelva a enviar con '
                '"Enviar al SIAT" (o registre los datos SIAT si la emitió en el Portal Web).'))
        elif state == 'cancel_requested':
            messages.append(_('Anulación solicitada al proveedor: se confirma automáticamente al consultar su estado.'))
        return messages

    # ------------------------------------------------------------------
    # Reglas de restablecer a borrador / solicitud de anulación (ganchos de account)
    # ------------------------------------------------------------------
    def _need_cancel_request(self):
        if self.l10n_bo_siat_state in ('accepted', 'cancel_requested'):
            return True
        return super()._need_cancel_request()

    @api.depends('country_code', 'l10n_bo_siat_state')
    def _compute_need_cancel_request(self):
        return super()._compute_need_cancel_request()

    @api.depends('restrict_mode_hash_table', 'state', 'inalterable_hash', 'l10n_bo_siat_state')
    def _compute_show_reset_to_draft_button(self):
        res = super()._compute_show_reset_to_draft_button()
        for move in self.filtered(lambda m: m.l10n_bo_siat_state in SIAT_ISSUED_STATES):
            move.show_reset_to_draft_button = False
        return res

    def button_request_cancel(self):
        self.ensure_one()
        if self.l10n_bo_siat_state in ('accepted', 'cancel_requested'):
            return self.action_l10n_bo_siat_open_cancel()
        return super().button_request_cancel()

    def button_draft(self):
        issued = self.filtered(lambda m: m.l10n_bo_siat_state in SIAT_ISSUED_STATES)
        if issued:
            raise UserError(self.env._(
                'No se puede restablecer a borrador %s: la factura ya fue emitida en el SIAT. Si tiene un error, '
                'use "Anular en SIAT" (genera la nota de crédito contable) y emita una nueva factura.',
                ', '.join(issued.mapped('display_name'))))
        res = super().button_draft()
        sales = self.filtered(lambda m: m.l10n_bo_siat_state)
        if sales:
            sales.sudo().activity_unlink([ACTIVITY_REGISTER, ACTIVITY_REVIEW])
            sales.write({'l10n_bo_siat_state': False, 'l10n_bo_siat_attempts': 0, 'l10n_bo_siat_mode': False})
        return res

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model
    def _l10n_bo_siat_normalize_vals(self, vals):
        for fname in ('l10n_bo_sale_buyer_number', 'l10n_bo_sale_buyer_complement'):
            if vals.get(fname):
                vals[fname] = vals[fname].strip().upper()
        if vals.get('l10n_bo_sale_buyer_name'):
            vals['l10n_bo_sale_buyer_name'] = vals['l10n_bo_sale_buyer_name'].strip()
        if vals.get('l10n_bo_siat_number'):
            vals['l10n_bo_siat_number'] = siat.normalize_number(vals['l10n_bo_siat_number'])
        if vals.get('l10n_bo_siat_cuf'):
            vals['l10n_bo_siat_cuf'] = siat.normalize_cuf(vals['l10n_bo_siat_cuf'])
        return vals

    def _l10n_bo_sale_check_no_invoice_access(self):
        if not self._l10n_bo_sale_user_allowed_no_invoice():
            raise UserError(self.env._(
                'Solo los usuarios del grupo "Ventas sin factura (autorizado)" pueden registrar una venta sin factura. '
                'Emita la factura o pida a un usuario autorizado que registre la venta.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._l10n_bo_siat_normalize_vals(vals)
            if vals.get('l10n_bo_sale_doc') == 'no_invoice':
                self._l10n_bo_sale_check_no_invoice_access()
        return super().create(vals_list)

    def write(self, vals):
        self._l10n_bo_siat_normalize_vals(vals)
        if vals.get('l10n_bo_sale_doc') == 'no_invoice':
            self._l10n_bo_sale_check_no_invoice_access()
        if not self.env.context.get('l10n_bo_siat_force_write') and any(f in vals for f in SIAT_LOCKED_FIELDS):
            for move in self:
                changed = [f for f in SIAT_LOCKED_FIELDS if f in vals and (move[f] or False) != (vals[f] or False)]
                if not changed:
                    continue
                if move.l10n_bo_siat_state in SIAT_ISSUED_STATES:
                    raise UserError(self.env._(
                        'No se pueden modificar los datos SIAT de %s porque la factura ya fue emitida. Si hay un error, '
                        'anúlela con "Anular en SIAT" y emita una nueva.', move.display_name))
                if 'l10n_bo_sale_doc' in changed and move.state == 'posted':
                    raise UserError(self.env._(
                        'Para cambiar entre factura y venta sin factura en %s, restablézcalo a borrador.', move.display_name))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Validación (publicación)
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        for move in self:
            if move._l10n_bo_sale_applies() and move.l10n_bo_sale_doc == 'no_invoice':
                move._l10n_bo_sale_check_no_invoice()
        posted = super()._post(soft=soft)
        posted.filtered(lambda m: m.state == 'posted' and m._l10n_bo_sale_applies())._l10n_bo_siat_after_post()
        return posted

    def _l10n_bo_sale_check_no_invoice(self):
        """Venta sin factura: usuario autorizado, motivo y monto máximo. Solo se aplica a ventas
        marcadas a mano como "sin factura" (los procesos automáticos nunca la usan)."""
        self.ensure_one()
        _ = self.env._
        self._l10n_bo_sale_check_no_invoice_access()
        if self.move_type != 'out_invoice':
            return
        if not (self.l10n_bo_sale_no_invoice_reason or '').strip():
            raise UserError(_(
                'Indique el motivo de la venta sin factura de %s (pestaña SIAT). Es obligatorio para el control.',
                self.display_name))
        company = self.company_id
        limit = company.l10n_bo_sale_no_invoice_max
        amount = abs(self.amount_total_signed)
        if limit > 0 and company.currency_id.compare_amounts(amount, limit) > 0:
            raise UserError(_(
                'La venta sin factura %(doc)s por %(amount)s supera el máximo permitido de %(limit)s por documento. '
                'Emita la factura o pida al administrador que revise el límite en Ajustes > Facturación SIAT.',
                doc=self.display_name, amount=company.currency_id.format(amount),
                limit=company.currency_id.format(limit)))

    def _l10n_bo_siat_after_post(self):
        """Estado SIAT al validar. Nunca bloquea: los datos faltantes quedan como pendientes."""
        to_emit = self.env['account.move']
        for move in self:
            if move.l10n_bo_siat_state in SIAT_ISSUED_STATES:
                continue
            company = move.company_id
            mode = company.l10n_bo_siat_mode
            vals = {'l10n_bo_siat_mode': mode, 'l10n_bo_siat_attempts': 0}
            if move.l10n_bo_sale_doc == 'no_invoice':
                vals.update({'l10n_bo_siat_state': 'not_applicable', 'l10n_bo_sale_no_invoice_user_id': self.env.user.id})
            elif move.l10n_bo_siat_cancel_reversal or move.l10n_bo_sale_doc != 'siat' or mode == 'none':
                vals['l10n_bo_siat_state'] = 'not_applicable'
            else:
                vals['l10n_bo_siat_state'] = 'to_send'
                if mode == 'provider':
                    vals['l10n_bo_siat_provider_id'] = company.l10n_bo_siat_provider_id.id
            move.write(vals)
            if move.l10n_bo_siat_state != 'to_send':
                continue
            if mode == 'portal_web':
                move._l10n_bo_siat_schedule_activity('register')
            elif not move.l10n_bo_siat_provider_id:
                move._l10n_bo_siat_add_log(self.env._('No hay proveedor SIAT configurado en la compañía.'))
                move._l10n_bo_siat_schedule_activity('review', self.env._(
                    'Configure el proveedor SIAT en Ajustes > Facturación SIAT y use "Enviar al SIAT".'))
            elif move.l10n_bo_siat_provider_id.emit_on_post:
                to_emit |= move
        to_emit._l10n_bo_siat_send()

    # ------------------------------------------------------------------
    # Actividades y bitácora
    # ------------------------------------------------------------------
    def _l10n_bo_siat_schedule_activity(self, kind, note=None):
        _ = self.env._
        xmlid = ACTIVITY_REGISTER if kind == 'register' else ACTIVITY_REVIEW
        activity_type = self.env.ref(xmlid, raise_if_not_found=False)
        for move in self:
            if activity_type and move.sudo().activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            user = move.company_id._l10n_bo_siat_activity_user(move)
            if kind == 'register':
                summary = _('Registrar factura SIAT')
                note = note or _(
                    'Emita la factura en el Portal Web del SIN para %(buyer)s (%(doc)s %(number)s) por %(amount)s y '
                    'registre el número y el CUF con "Registrar datos SIAT".',
                    buyer=move.l10n_bo_sale_buyer_name or '-',
                    doc=dict(BUYER_DOC_TYPES).get(move.l10n_bo_sale_buyer_doc_type, '').split(' - ')[0],
                    number=move.l10n_bo_sale_buyer_number or '-',
                    amount=move.currency_id.format(move.amount_total))
            else:
                summary = _('Revisar emisión SIAT')
            values = {'summary': summary, 'note': note or ''}
            if user:
                values['user_id'] = user.id
            try:
                with self.env.cr.savepoint():
                    move.sudo().activity_schedule(xmlid, **values)
            except Exception:  # noqa: BLE001 — una actividad nunca debe impedir validar la venta
                _logger.exception('No se pudo crear la actividad SIAT para %s', move.display_name)

    def _l10n_bo_siat_done_activities(self, feedback=None):
        self.sudo().activity_feedback([ACTIVITY_REGISTER, ACTIVITY_REVIEW], feedback=feedback)

    def _l10n_bo_siat_add_log(self, message):
        stamp = fields.Datetime.context_timestamp(self.with_context(tz=BO_TZ), fields.Datetime.now())
        line = '[%s] %s' % (stamp.strftime('%Y-%m-%d %H:%M'), message)
        for move in self:
            move.l10n_bo_siat_log = line + ('\n' + move.l10n_bo_siat_log if move.l10n_bo_siat_log else '')

    # ------------------------------------------------------------------
    # Validación de datos
    # ------------------------------------------------------------------
    def _l10n_bo_siat_buyer_errors(self, values=None):
        """Errores de los datos del comprador (lista de textos). ``values`` reemplaza los datos
        del documento (asistente de registro)."""
        self.ensure_one()
        _ = self.env._
        values = values or {}
        buyer = {fname: values.get(fname, self[fname]) or False for fname in BUYER_FIELDS}
        errors = []
        doc_type = buyer['l10n_bo_sale_buyer_doc_type']
        number = (buyer['l10n_bo_sale_buyer_number'] or '').strip()
        if not doc_type:
            errors.append(_('Falta el tipo de documento del comprador.'))
        if not number:
            errors.append(_('Falta el NIT/CI del comprador (use 0 para el consumidor final).'))
        elif doc_type == BUYER_DOC_NIT and not number.isdigit():
            errors.append(_('El NIT del comprador "%s" debe tener solo dígitos.', number))
        if not (buyer['l10n_bo_sale_buyer_name'] or '').strip():
            errors.append(_('Falta la razón social o nombre del comprador (use S/N para el consumidor final).'))
        if buyer['l10n_bo_sale_buyer_complement'] and doc_type != BUYER_DOC_CI:
            errors.append(_('El complemento solo se admite cuando el documento del comprador es CI.'))
        if self._l10n_bo_siat_anonymous_over_limit(number):
            errors.append(_(
                'El importe supera %s: identifique al comprador (NIT/CI y nombre).',
                self.company_id.currency_id.format(self.company_id.l10n_bo_siat_anonymous_max)))
        return errors

    @api.model
    def _l10n_bo_siat_local_to_utc(self, local_dt):
        return pytz.timezone(BO_TZ).localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)

    def _l10n_bo_siat_manual_errors(self, number, cuf):
        """Errores del número y CUF registrados a mano. Devuelve (errores, CUF decodificado o None)."""
        self.ensure_one()
        _ = self.env._
        company = self.company_id
        nit = company._l10n_bo_siat_nit()
        errors = []
        decoded = None
        if not nit:
            errors.append(_('Falta el NIT de la compañía (Ajustes > Compañías): es necesario para validar el CUF.'))
        if not number:
            errors.append(_('Falta el número de factura SIAT.'))
        elif not number.isdigit():
            errors.append(_('El número de factura "%s" debe tener solo dígitos.', number))
        if not cuf:
            errors.append(_('Falta el CUF.'))
        elif cuf.startswith(DEMO_CUF_PREFIX):
            errors.append(_('Un CUF SIMULADO no puede registrarse como factura del SIN.'))
        elif not siat.is_plausible_cuf(cuf):
            errors.append(_('El CUF "%(cuf)s" no es válido: debe ser hexadecimal (0-9, A-F) de %(min)s a %(max)s caracteres.',
                            cuf=cuf, min=siat.CUF_MIN_LEN, max=siat.CUF_MAX_LEN))
        else:
            decoded = siat.decode_cuf(cuf, nit=nit)
            check = company.l10n_bo_siat_cuf_check or 'decodable'
            if check == 'strict' and not decoded:
                errors.append(_(
                    'El CUF "%s" no supera el dígito verificador (módulo 11). Revise que esté completo y bien copiado '
                    '(puede pegar el enlace del QR de la factura). Si es una factura real rechazada por el sistema, el '
                    'contador puede cambiar la validación del CUF en Ajustes.', cuf))
            elif decoded and check != 'format':
                if nit and decoded['nit'] != nit:
                    errors.append(_(
                        'El CUF corresponde al NIT %(cuf_nit)s y no al NIT de la compañía %(nit)s: ¿es una factura de '
                        'otra empresa?', cuf_nit=decoded['nit'], nit=nit))
                if number and number.isdigit() and decoded['number'] != number:
                    errors.append(_('El CUF corresponde a la factura n.º %(cuf_number)s y no a la n.º %(number)s indicada.',
                                    cuf_number=decoded['number'], number=number))
        if cuf:
            other = self.sudo().search([('company_id', '=', company.id), ('l10n_bo_siat_cuf', '=', cuf),
                                        ('id', '!=', self.id)], limit=1)
            if other:
                errors.append(_('Ese CUF ya está registrado en %s: no se puede registrar dos veces la misma factura.',
                                other.display_name))
        if number and number.isdigit():
            other = self.sudo().search([
                ('company_id', '=', company.id), ('move_type', '=', self.move_type),
                ('l10n_bo_siat_number', '=', number), ('l10n_bo_siat_state', '=', 'accepted'), ('id', '!=', self.id),
            ], limit=1)
            if other:
                errors.append(_('La factura SIAT n.º %(number)s ya está registrada en %(doc)s.',
                                number=number, doc=other.display_name))
        return errors, decoded

    # ------------------------------------------------------------------
    # Registro manual (Portal Web del SIN)
    # ------------------------------------------------------------------
    def _l10n_bo_siat_check_pending(self):
        self.ensure_one()
        if self.state != 'posted' or not self._l10n_bo_sale_applies() or self.l10n_bo_sale_doc != 'siat':
            raise UserError(self.env._('%s no es una factura de venta validada con documento SIAT.', self.display_name))
        if self.l10n_bo_siat_state not in ('to_send', 'rejected'):
            raise UserError(self.env._(
                '%(doc)s no está pendiente de registro (estado SIAT: %(state)s).', doc=self.display_name,
                state=dict(SIAT_STATES).get(self.l10n_bo_siat_state, '-')))

    def _l10n_bo_siat_register(self, number, cuf, emission_date=None, buyer_vals=None):
        """Registra el número y el CUF de una factura emitida en el Portal Web del SIN."""
        self.ensure_one()
        self._l10n_bo_siat_check_pending()
        if buyer_vals:
            self.write(buyer_vals)
        number = siat.normalize_number(number)
        cuf = siat.normalize_cuf(cuf)
        errors, decoded = self._l10n_bo_siat_manual_errors(number, cuf)
        if errors:
            raise UserError(self.env._(
                'No se pueden registrar los datos SIAT de %(doc)s:\n%(errors)s',
                doc=self.display_name, errors='\n'.join('• %s' % e for e in errors)))
        if not emission_date and decoded:
            emission_date = self._l10n_bo_siat_local_to_utc(decoded['emission'])
        self.write({
            'l10n_bo_siat_number': number,
            'l10n_bo_siat_cuf': cuf,
            'l10n_bo_siat_emission_date': emission_date or fields.Datetime.now(),
            'l10n_bo_siat_state': 'accepted',
            'l10n_bo_siat_simulated': False,
        })
        note = self.env._('Registrada a mano (Portal Web del SIN) por %(user)s: n.º %(number)s, CUF %(cuf)s%(check)s.',
                          user=self.env.user.name, number=number, cuf=cuf,
                          check='' if decoded else self.env._(' (CUF no decodificable: validado solo el formato)'))
        self._l10n_bo_siat_add_log(note)
        self._l10n_bo_siat_done_activities(feedback=note)
        self.message_post(body=note)
        return True

    def action_l10n_bo_siat_open_register(self):
        self.ensure_one()
        self._l10n_bo_siat_check_pending()
        return self.env['l10n_bo.siat.register.wizard']._action_open(self)

    # ------------------------------------------------------------------
    # Emisión por proveedor
    # ------------------------------------------------------------------
    def _l10n_bo_siat_payload(self):
        """Datos de la factura para un conector real (documentados; el simulador no los usa)."""
        self.ensure_one()
        company = self.company_id
        currency = self.currency_id
        lines = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            lines.append({
                'product_code': line.product_id.default_code or str(line.product_id.id or ''),
                'description': line.name or line.product_id.display_name,
                'quantity': line.quantity,
                'uom': line.product_uom_id.name,
                'price_unit': line.price_unit,
                'discount_amount': currency.round(line.price_unit * line.quantity * line.discount / 100.0),
                'subtotal': line.price_total,
            })
        return {
            'issuer_nit': company._l10n_bo_siat_nit(),
            'issuer_name': company.name,
            'document': 'invoice' if self.move_type == 'out_invoice' else 'credit_debit_note',
            'reference_cuf': self.reversed_entry_id.l10n_bo_siat_cuf or False,
            'reference_number': self.reversed_entry_id.l10n_bo_siat_number or False,
            'buyer': {
                'doc_type': self.l10n_bo_sale_buyer_doc_type,
                'number': self.l10n_bo_sale_buyer_number,
                'complement': self.l10n_bo_sale_buyer_complement or False,
                'name': self.l10n_bo_sale_buyer_name,
                'email': self.partner_id.email or False,
                'customer_code': str(self.commercial_partner_id.id),
            },
            'currency': currency.name,
            'amount_total': self.amount_total,
            'lines': lines,
            'odoo_reference': self.name,
            'user': self.env.user.login,
        }

    def _l10n_bo_siat_send(self):
        """Envía al proveedor las facturas pendientes. Nunca lanza errores: deja el estado y la bitácora."""
        _ = self.env._
        for move in self:
            if move.state != 'posted' or move.l10n_bo_sale_doc != 'siat' or \
                    move.l10n_bo_siat_state not in ('to_send', 'rejected'):
                continue
            company = move.company_id
            provider = move.l10n_bo_siat_provider_id or company.l10n_bo_siat_provider_id
            if not provider:
                move._l10n_bo_siat_add_log(_('No hay proveedor SIAT configurado en la compañía.'))
                move._l10n_bo_siat_schedule_activity('review')
                continue
            errors = move._l10n_bo_siat_buyer_errors()
            if not company._l10n_bo_siat_nit():
                errors.insert(0, _('Falta el NIT de la compañía.'))
            if errors:
                move.write({'l10n_bo_siat_state': 'rejected', 'l10n_bo_siat_provider_id': provider.id})
                move._l10n_bo_siat_add_log(_('No enviada (validación previa): %s', ' '.join(errors)))
                move._l10n_bo_siat_schedule_activity('review', _(
                    'Corrija los datos del comprador en la pestaña SIAT y use "Enviar al SIAT": %s', ' '.join(errors)))
                continue
            try:
                with self.env.cr.savepoint():
                    result = provider.sudo()._siat_emit(move)
            except Exception as error:  # noqa: BLE001 — comunicación: se reintenta
                _logger.warning('Emisión SIAT fallida para %s: %s', move.display_name, error)
                result = {'state': 'error', 'message': str(error)}
            move._l10n_bo_siat_apply_emit_result(provider, result or {})

    def _l10n_bo_siat_apply_emit_result(self, provider, result):
        self.ensure_one()
        _ = self.env._
        state = result.get('state')
        message = result.get('message') or ''
        if state == 'accepted':
            number = siat.normalize_number(result.get('number'))
            cuf = siat.normalize_cuf(result.get('cuf'))
            duplicate = cuf and self.sudo().search(
                [('company_id', '=', self.company_id.id), ('l10n_bo_siat_cuf', '=', cuf), ('id', '!=', self.id)], limit=1)
            if not (number and cuf) or duplicate:
                state = 'error'
                message = _('Respuesta del proveedor incompleta o con un CUF ya registrado (%(cuf)s). %(msg)s',
                            cuf=cuf or '-', msg=message)
            else:
                self.write({
                    'l10n_bo_siat_state': 'accepted',
                    'l10n_bo_siat_number': number,
                    'l10n_bo_siat_cuf': cuf,
                    'l10n_bo_siat_emission_date': result.get('emission_date') or fields.Datetime.now(),
                    'l10n_bo_siat_provider_id': provider.id,
                    'l10n_bo_siat_simulated': provider.is_simulated,
                })
                note = _('Factura emitida por %(provider)s: n.º %(number)s, CUF %(cuf)s. %(msg)s',
                         provider=provider.name, number=number, cuf=cuf, msg=message)
                self._l10n_bo_siat_add_log(note)
                self._l10n_bo_siat_done_activities(feedback=note)
                self.message_post(body=note)
                return
        if state == 'rejected':
            self.write({'l10n_bo_siat_state': 'rejected', 'l10n_bo_siat_provider_id': provider.id})
            self._l10n_bo_siat_add_log(_('Rechazada por el SIN / proveedor: %s', message))
            self._l10n_bo_siat_schedule_activity('review', _('Factura rechazada: %s', message))
            self.message_post(body=_('Factura rechazada en el SIAT: %s', message))
            return
        # Pendiente o error de comunicación: queda por enviar y se reintenta.
        attempts = self.l10n_bo_siat_attempts + 1
        self.write({'l10n_bo_siat_state': 'to_send', 'l10n_bo_siat_attempts': attempts,
                    'l10n_bo_siat_provider_id': provider.id})
        self._l10n_bo_siat_add_log(_('Intento %(n)s sin respuesta válida: %(msg)s', n=attempts, msg=message or '-'))
        if attempts >= max(self.company_id.l10n_bo_siat_retry_limit, 1):
            self._l10n_bo_siat_schedule_activity('review', _(
                'La factura no pudo enviarse al SIAT tras %(n)s intentos. Último mensaje: %(msg)s',
                n=attempts, msg=message or '-'))

    def action_l10n_bo_siat_send(self):
        for move in self:
            if move.l10n_bo_siat_state not in ('to_send', 'rejected'):
                raise UserError(self.env._('%s no está pendiente de envío al SIAT.', move.display_name))
        self._l10n_bo_siat_send()
        return True

    @api.model
    def _cron_l10n_bo_siat_process(self, limit=200):
        """Reintenta las emisiones pendientes y consulta las anulaciones solicitadas."""
        in_cron = bool(self.env.context.get('cron_id'))
        pending = self.search([
            ('state', '=', 'posted'), ('l10n_bo_siat_state', '=', 'to_send'), ('l10n_bo_siat_mode', '=', 'provider'),
        ], order='id', limit=limit)
        pending = pending.filtered(lambda m: m.l10n_bo_siat_attempts < max(m.company_id.l10n_bo_siat_retry_limit, 1))
        for move in pending:
            move._l10n_bo_siat_send()
            if in_cron:
                self.env['ir.cron']._commit_progress(1)
        for move in self.search([('l10n_bo_siat_state', '=', 'cancel_requested')], order='id', limit=limit):
            move._l10n_bo_siat_check_cancel_status()
            if in_cron:
                self.env['ir.cron']._commit_progress(1)
        return True

    # ------------------------------------------------------------------
    # Anulación
    # ------------------------------------------------------------------
    def _l10n_bo_siat_cancel_deadline(self):
        """Último día para anular (día configurado del mes siguiente a la emisión) o None."""
        self.ensure_one()
        day = self.company_id.l10n_bo_siat_cancel_day
        if day <= 0:
            return None
        if self.l10n_bo_siat_emission_date:
            emitted = fields.Datetime.context_timestamp(
                self.with_context(tz=BO_TZ), self.l10n_bo_siat_emission_date).date()
        else:
            emitted = self.invoice_date or self.date
        # relativedelta(day=n) se ajusta al último día del mes si n lo excede.
        return emitted.replace(day=1) + relativedelta(months=1, day=day)

    def _l10n_bo_siat_check_cancellable(self):
        self.ensure_one()
        _ = self.env._
        if not self._l10n_bo_sale_applies() or self.state != 'posted':
            raise UserError(_('%s no es una factura de venta validada.', self.display_name))
        if self.l10n_bo_siat_state not in ('accepted', 'cancel_requested'):
            raise UserError(_('Solo se anulan en el SIAT las facturas aceptadas (estado actual de %(doc)s: %(state)s).',
                              doc=self.display_name, state=dict(SIAT_STATES).get(self.l10n_bo_siat_state, '-')))
        deadline = self._l10n_bo_siat_cancel_deadline()
        today = fields.Date.context_today(self.with_context(tz=BO_TZ))
        if self.l10n_bo_siat_state == 'accepted' and deadline and today > deadline:
            raise UserError(_(
                'El plazo para anular %(doc)s venció el %(deadline)s (día %(day)s del mes siguiente a la emisión). '
                'Corresponde una nota de crédito-débito o el procedimiento de anulación fuera de plazo ante el SIN '
                '(RND 102600000025). Consulte con el contador.',
                doc=self.display_name, deadline=deadline.strftime('%d/%m/%Y'), day=self.company_id.l10n_bo_siat_cancel_day))

    def _l10n_bo_siat_uses_provider(self):
        self.ensure_one()
        return self.l10n_bo_siat_mode == 'provider' and bool(self.l10n_bo_siat_provider_id)

    def _l10n_bo_siat_cancel(self, reason, note=False, manual_confirmed=False):
        """Anula la factura en el SIAT (proveedor o confirmación manual del Portal Web) y la revierte
        en contabilidad con la nota de crédito estándar. Devuelve la reversión (o un recordset vacío)."""
        self.ensure_one()
        _ = self.env._
        self._l10n_bo_siat_check_cancellable()
        if not reason:
            raise UserError(_('Indique el motivo de anulación.'))
        values = {'l10n_bo_siat_cancel_reason_id': reason.id, 'l10n_bo_siat_cancel_note': note or False}
        if not self._l10n_bo_siat_uses_provider():
            if not manual_confirmed:
                raise UserError(_(
                    'Primero anule la factura n.º %s en el Portal Web del SIN y luego confirme la anulación en este '
                    'asistente.', self.l10n_bo_siat_number))
            self.write(values)
            self._l10n_bo_siat_add_log(_('Anulación registrada a mano (Portal Web del SIN) por %(user)s. Motivo: %(reason)s.',
                                         user=self.env.user.name, reason=reason.display_name))
            return self._l10n_bo_siat_finalize_cancel()
        provider = self.l10n_bo_siat_provider_id
        try:
            with self.env.cr.savepoint():
                result = provider.sudo()._siat_cancel(self, reason.code) or {}
        except Exception as error:  # noqa: BLE001
            _logger.warning('Anulación SIAT fallida para %s: %s', self.display_name, error)
            raise UserError(_(
                'No se pudo comunicar con el proveedor SIAT para anular %(doc)s: %(error)s. Intente más tarde.',
                doc=self.display_name, error=error)) from error
        message = result.get('message') or ''
        self.write(values)
        if result.get('state') == 'cancelled':
            self._l10n_bo_siat_add_log(_('Anulación aceptada por %(provider)s. Motivo: %(reason)s. %(msg)s',
                                         provider=provider.name, reason=reason.display_name, msg=message))
            return self._l10n_bo_siat_finalize_cancel()
        if result.get('state') == 'cancel_requested':
            self.write({'l10n_bo_siat_state': 'cancel_requested'})
            self._l10n_bo_siat_add_log(_('Anulación solicitada a %(provider)s: %(msg)s', provider=provider.name, msg=message))
            return self.env['account.move']
        raise UserError(_('El SIN / proveedor rechazó la anulación de %(doc)s: %(msg)s', doc=self.display_name, msg=message or '-'))

    def _l10n_bo_siat_check_cancel_status(self):
        self.ensure_one()
        provider = self.l10n_bo_siat_provider_id
        if self.l10n_bo_siat_state != 'cancel_requested' or not provider:
            return
        try:
            with self.env.cr.savepoint():
                result = provider.sudo()._siat_status(self) or {}
        except Exception as error:  # noqa: BLE001
            self._l10n_bo_siat_add_log(self.env._('Consulta de estado fallida: %s', error))
            return
        if result.get('state') == 'cancelled':
            self._l10n_bo_siat_add_log(self.env._('Anulación confirmada por el proveedor. %s', result.get('message') or ''))
            self._l10n_bo_siat_finalize_cancel()
        elif result.get('state') in ('accepted', 'rejected'):
            self.write({'l10n_bo_siat_state': 'accepted'})
            self._l10n_bo_siat_add_log(self.env._('La anulación no fue aceptada: %s', result.get('message') or '-'))
            self._l10n_bo_siat_schedule_activity('review', self.env._('La anulación en el SIAT no fue aceptada.'))

    def _l10n_bo_siat_finalize_cancel(self):
        """Marca la factura como anulada y la revierte con una nota de crédito conciliada (estándar)."""
        self.ensure_one()
        _ = self.env._
        self.write({'l10n_bo_siat_state': 'cancelled', 'l10n_bo_siat_cancel_date': fields.Datetime.now()})
        self._l10n_bo_siat_done_activities(feedback=_('Factura anulada en el SIAT.'))
        today = fields.Date.context_today(self.with_context(tz=BO_TZ))
        reason = self.l10n_bo_siat_cancel_reason_id.display_name or '-'
        reversal = self._reverse_moves([{
            'ref': _('Anulación SIAT de %(doc)s (factura n.º %(number)s): %(reason)s',
                     doc=self.name, number=self.l10n_bo_siat_number, reason=reason),
            'date': today,
            'invoice_date': today,
            'invoice_date_due': today,
            'journal_id': self.journal_id.id,
            'invoice_user_id': self.invoice_user_id.id,
            'invoice_origin': self.invoice_origin,
            'auto_post': 'no',
            'l10n_bo_siat_cancel_reversal': True,
        }], cancel=True)
        self.message_post(body=_(
            'Factura n.º %(number)s anulada en el SIAT (motivo: %(reason)s). Reversión contable: %(reversal)s.',
            number=self.l10n_bo_siat_number, reason=reason, reversal=reversal.display_name))
        reversal.message_post(body=_(
            'Reversión contable por anulación SIAT de %s. No es una nota de crédito-débito fiscal.', self.display_name))
        return reversal

    def action_l10n_bo_siat_open_cancel(self):
        self.ensure_one()
        self._l10n_bo_siat_check_cancellable()
        return self.env['l10n_bo.siat.cancel.wizard']._action_open(self)
