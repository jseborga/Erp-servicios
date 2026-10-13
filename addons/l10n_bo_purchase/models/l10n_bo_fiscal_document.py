# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_date

from ..tools import siat

DOC_TYPES = [
    ('siat_online', 'Factura en línea / electrónica (CUF)'),
    ('dosificacion', 'Factura computarizada (dosificación)'),
    ('manual', 'Factura manual'),
    ('none', 'Sin factura'),
]
INVOICE_DOC_TYPES = ('siat_online', 'dosificacion', 'manual')

# Catálogo "Tipo de compra" del Registro de Compras (RND 10-0021-16 y posteriores).
# VERIFICAR con el catálogo oficial vigente del SIN antes de presentar el libro.
PURCHASE_TYPES = [
    ('1', '1 - Mercado interno, destino a actividades gravadas'),
    ('2', '2 - Mercado interno, destino a actividades no gravadas'),
    ('3', '3 - Sujetas a proporcionalidad'),
    ('4', '4 - Destino a exportaciones'),
    ('5', '5 - Mercado interno y exportaciones'),
]

WITHHOLDING_MODES = [
    ('supplier_bears', 'Se retiene al proveedor (recibe el neto)'),
    ('company_bears', 'La empresa asume la retención (grossing-up)'),
    ('no_withholding', 'Sin retención (gasto no deducible)'),
]

PURCHASE_KINDS = [
    ('goods', 'Bienes (IUE 5 % + IT 3 %)'),
    ('services', 'Servicios profesionales u oficios (IUE 12,5 % + IT 3 %)'),
    ('eventual', 'Servicios eventuales, alquileres e intereses (RC-IVA 13 % + IT 3 %)'),
]


class L10nBoFiscalDocumentMixin(models.AbstractModel):
    """Datos del documento fiscal de una compra (factura de proveedor o comprobante de
    fondo fijo). Las dependencias de los campos calculados las declara cada modelo
    concreto (account.move, l10n_bo.petty.cash.voucher)."""
    _name = 'l10n_bo.fiscal.document.mixin'
    _description = 'Documento fiscal de compra (Bolivia)'

    l10n_bo_doc_type = fields.Selection(
        DOC_TYPES, string='Tipo de documento fiscal',
        compute='_compute_l10n_bo_doc_type', store=True, readonly=False, precompute=True, copy=False,
        help='Factura en línea/electrónica: NIT, número y CUF.\n'
             'Computarizada (dosificación): NIT, número, n.º de autorización y código de control.\n'
             'Manual: NIT, número y n.º de autorización.\n'
             'Sin factura: no da crédito fiscal; corresponde retener o registrar como gasto no deducible.')
    l10n_bo_supplier_nit = fields.Char(
        string='NIT del proveedor', compute='_compute_l10n_bo_supplier_nit',
        store=True, readonly=False, precompute=True, copy=False,
        help='NIT del emisor tal como figura en la factura. Por defecto, el NIT del proveedor.')
    l10n_bo_invoice_number = fields.Char(string='Número de factura', copy=False)
    l10n_bo_cuf = fields.Char(
        string='CUF', copy=False,
        help='Código Único de Factura (hexadecimal) de las facturas en línea o electrónicas.')
    l10n_bo_auth_number = fields.Char(
        string='N.º de autorización', copy=False,
        help='Número de autorización de la dosificación (facturas computarizadas o manuales).')
    l10n_bo_control_code = fields.Char(
        string='Código de control', copy=False, help='Formato 7B-F3-48-A8 (facturas computarizadas).')
    l10n_bo_purchase_type = fields.Selection(
        PURCHASE_TYPES, string='Tipo de compra (Libro de Compras)',
        compute='_compute_l10n_bo_purchase_type', store=True, readonly=False, precompute=True, copy=False,
        help='Destino del crédito fiscal para el Registro de Compras. '
             'Catálogo tomado de la normativa del SIN: verifique el catálogo oficial vigente.')
    l10n_bo_withholding_mode = fields.Selection(
        WITHHOLDING_MODES, string='Tratamiento sin factura',
        help='Compras sin factura: retener al proveedor, asumir la retención o registrar el '
             'gasto como no deducible (560500).')
    l10n_bo_purchase_kind = fields.Selection(
        PURCHASE_KINDS, string='Tipo de compra para retención',
        help='Define la retención: bienes 8 %, servicios profesionales 15,5 %, '
             'servicios eventuales/alquileres 16 %.')
    l10n_bo_has_invoice = fields.Boolean(compute='_compute_l10n_bo_has_invoice', string='Con factura')
    l10n_bo_doc_key = fields.Char(
        string='CUF / autorización (clave)', compute='_compute_l10n_bo_doc_key', store=True,
        help='CUF (facturas en línea) o número de autorización (dosificación y manual). '
             'Forma parte de la clave única NIT + número + CUF/autorización.')

    # ------------------------------------------------------------------
    # Cálculos (las dependencias se declaran en los modelos concretos)
    # ------------------------------------------------------------------
    def _l10n_bo_applies(self):
        """¿Corresponde manejar datos fiscales de compra en este registro?"""
        self.ensure_one()
        return True

    def _l10n_bo_default_doc_type(self):
        self.ensure_one()
        return self.company_id.l10n_bo_default_doc_type or 'siat_online'

    def _compute_l10n_bo_doc_type(self):
        for rec in self:
            if not rec._l10n_bo_applies():
                rec.l10n_bo_doc_type = False
            else:
                rec.l10n_bo_doc_type = rec.l10n_bo_doc_type or rec._l10n_bo_default_doc_type()

    def _compute_l10n_bo_supplier_nit(self):
        for rec in self:
            partner = rec.partner_id.commercial_partner_id
            if rec._l10n_bo_applies() and partner.vat:
                rec.l10n_bo_supplier_nit = siat.normalize_nit(partner.vat)
            elif rec._l10n_bo_applies() and partner:
                rec.l10n_bo_supplier_nit = False  # proveedor sin NIT: no arrastrar el NIT anterior
            else:
                rec.l10n_bo_supplier_nit = rec.l10n_bo_supplier_nit or False

    def _compute_l10n_bo_purchase_type(self):
        for rec in self:
            if rec._l10n_bo_applies() and rec.l10n_bo_doc_type in INVOICE_DOC_TYPES:
                rec.l10n_bo_purchase_type = rec.l10n_bo_purchase_type or rec.company_id.l10n_bo_default_purchase_type or '1'
            else:
                rec.l10n_bo_purchase_type = False

    @api.depends('l10n_bo_doc_type', 'l10n_bo_cuf', 'l10n_bo_auth_number')
    def _compute_l10n_bo_doc_key(self):
        for rec in self:
            rec.l10n_bo_doc_key = rec._l10n_bo_doc_key_value()

    @api.depends('l10n_bo_doc_type')
    def _compute_l10n_bo_has_invoice(self):
        for rec in self:
            rec.l10n_bo_has_invoice = rec.l10n_bo_doc_type in INVOICE_DOC_TYPES

    # ------------------------------------------------------------------
    # Normalización
    # ------------------------------------------------------------------
    @api.model
    def _l10n_bo_normalize_vals(self, vals):
        normalizers = {
            'l10n_bo_supplier_nit': siat.normalize_nit,
            'l10n_bo_invoice_number': siat.normalize_number,
            'l10n_bo_cuf': siat.normalize_cuf,
            'l10n_bo_auth_number': siat.normalize_auth,
            'l10n_bo_control_code': siat.normalize_control_code,
        }
        for fname, normalize in normalizers.items():
            if fname in vals and vals[fname]:
                vals[fname] = normalize(vals[fname])
        return vals

    # ------------------------------------------------------------------
    # Clave de unicidad y duplicados
    # ------------------------------------------------------------------
    def _l10n_bo_doc_key_value(self):
        """CUF para facturas en línea; n.º de autorización para dosificación y manual."""
        self.ensure_one()
        if self.l10n_bo_doc_type == 'siat_online':
            return self.l10n_bo_cuf or False
        if self.l10n_bo_doc_type in ('dosificacion', 'manual'):
            return self.l10n_bo_auth_number or False
        return False

    def _l10n_bo_doc_label(self):
        self.ensure_one()
        key = 'CUF' if self.l10n_bo_doc_type == 'siat_online' else 'autorización'
        return self.env._(
            'NIT %(nit)s, factura n.º %(number)s, %(key)s %(value)s',
            nit=self.l10n_bo_supplier_nit, number=self.l10n_bo_invoice_number,
            key=key, value=self._l10n_bo_doc_key_value())

    def _l10n_bo_duplicate_bill_domain(self):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('state', '=', 'posted'),
            ('l10n_bo_supplier_nit', '=', self.l10n_bo_supplier_nit),
            ('l10n_bo_invoice_number', '=', self.l10n_bo_invoice_number),
            ('l10n_bo_doc_key', '=', self._l10n_bo_doc_key_value()),
        ]

    def _l10n_bo_find_duplicates(self):
        """Lista de textos que describen documentos ya registrados con la misma clave
        (empresa + NIT + número + CUF/autorización). Otros módulos (fondo fijo) la extienden."""
        self.ensure_one()
        if (
            self.l10n_bo_doc_type not in INVOICE_DOC_TYPES
            or not (self.l10n_bo_supplier_nit and self.l10n_bo_invoice_number and self._l10n_bo_doc_key_value())
        ):
            return []
        domain = self._l10n_bo_duplicate_bill_domain()
        if self._name == 'account.move' and self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        bills = self.env['account.move'].sudo().search(domain, limit=5)
        return [
            self.env._(
                'Factura de proveedor %(name)s de %(partner)s del %(date)s',
                name=bill.name, partner=bill.partner_id.display_name,
                date=format_date(self.env, bill.invoice_date))
            for bill in bills
        ]

    def _l10n_bo_raise_if_duplicate(self):
        for rec in self:
            duplicates = rec._l10n_bo_find_duplicates()
            if duplicates:
                raise ValidationError(self.env._(
                    'El documento %(doc)s ya está registrado:\n%(dups)s\n\n'
                    'No se puede registrar dos veces la misma factura. Si es un error de digitación, '
                    'corrija el NIT, el número o el CUF/autorización; si la factura ya se registró, '
                    'use el documento existente.',
                    doc=rec._l10n_bo_doc_label(), dups='\n'.join('• %s' % d for d in duplicates)))

    # ------------------------------------------------------------------
    # Validación de datos del documento
    # ------------------------------------------------------------------
    def _l10n_bo_document_errors(self):
        """Errores de forma del documento fiscal (lista de textos)."""
        self.ensure_one()
        errors = []
        doc_type = self.l10n_bo_doc_type
        _ = self.env._
        if not doc_type:
            return [_('Indique el tipo de documento fiscal.')]
        if doc_type == 'none':
            if not self.l10n_bo_withholding_mode:
                errors.append(_('Compra sin factura: indique si se retiene al proveedor, si la empresa asume la retención o si es un gasto no deducible sin retención.'))
            elif self.l10n_bo_withholding_mode in ('supplier_bears', 'company_bears') and not self._l10n_bo_has_purchase_kind():
                errors.append(_('Compra sin factura con retención: indique el tipo de compra (bienes, servicios profesionales o servicios eventuales/alquileres).'))
            return errors

        nit, number = self.l10n_bo_supplier_nit, self.l10n_bo_invoice_number
        if not nit:
            errors.append(_('Falta el NIT del proveedor.'))
        elif not nit.isdigit():
            errors.append(_('El NIT del proveedor "%s" debe tener solo dígitos.', nit))
        if not number:
            errors.append(_('Falta el número de factura.'))
        elif not number.isdigit():
            errors.append(_('El número de factura "%s" debe tener solo dígitos.', number))

        if doc_type == 'siat_online':
            errors += self._l10n_bo_cuf_errors()
        else:
            auth = self.l10n_bo_auth_number
            if not auth:
                errors.append(_('Falta el número de autorización de la factura.'))
            elif not siat.is_valid_auth_number(auth):
                errors.append(_('El número de autorización "%s" debe tener solo dígitos (hasta 20).', auth))
            if doc_type == 'dosificacion':
                code = self.l10n_bo_control_code
                if not code:
                    errors.append(_('Falta el código de control de la factura computarizada.'))
                elif not siat.is_valid_control_code(code):
                    errors.append(_('El código de control "%s" no tiene el formato esperado (por ejemplo 7B-F3-48-A8).', code))
        return errors

    def _l10n_bo_cuf_errors(self):
        self.ensure_one()
        _ = self.env._
        cuf = self.l10n_bo_cuf
        if not cuf:
            return [_('Falta el CUF de la factura en línea / electrónica.')]
        if not siat.is_plausible_cuf(cuf):
            return [_('El CUF "%(cuf)s" no es válido: debe ser hexadecimal (0-9, A-F) de %(min)s a %(max)s caracteres.',
                      cuf=cuf, min=siat.CUF_MIN_LEN, max=siat.CUF_MAX_LEN)]
        if (self.company_id.l10n_bo_cuf_check or 'strict') != 'strict':
            return []
        decoded = siat.decode_cuf(cuf, nit=self.l10n_bo_supplier_nit)
        if not decoded:
            return [_('El CUF "%s" no supera el dígito verificador (módulo 11). Revise que esté completo y bien copiado '
                      '(use el lector de QR). Si es una factura real que el sistema rechaza, el contador puede cambiar la '
                      'validación del CUF a "solo formato" en Ajustes.', cuf)]
        errors = []
        if self.l10n_bo_supplier_nit and decoded['nit'] != self.l10n_bo_supplier_nit:
            errors.append(_('El CUF corresponde al NIT %(cuf_nit)s y no al NIT %(nit)s indicado.',
                            cuf_nit=decoded['nit'], nit=self.l10n_bo_supplier_nit))
        if self.l10n_bo_invoice_number and decoded['number'] != self.l10n_bo_invoice_number:
            errors.append(_('El CUF corresponde a la factura n.º %(cuf_number)s y no a la n.º %(number)s indicada.',
                            cuf_number=decoded['number'], number=self.l10n_bo_invoice_number))
        return errors

    def _l10n_bo_has_purchase_kind(self):
        self.ensure_one()
        return bool(self.l10n_bo_purchase_kind)

    # ------------------------------------------------------------------
    # Impuestos y cuentas por compañía
    # ------------------------------------------------------------------
    @api.model
    def _l10n_bo_chart_ref(self, company, xmlid):
        return self.env['account.chart.template'].with_company(company).ref(xmlid, raise_if_not_found=False)

    @api.model
    def _l10n_bo_tax_groups(self, company, keys):
        groups = self.env['account.tax.group']
        for key in keys:
            groups |= self._l10n_bo_chart_ref(company, key) or self.env['account.tax.group']
        return groups

    @api.model
    def _l10n_bo_vat_tax_groups(self, company):
        """Grupos de impuesto que generan crédito fiscal IVA (l10n_bo)."""
        return self._l10n_bo_tax_groups(company, ('tax_group_iva_13', 'tax_group_iva_mixed'))

    @api.model
    def _l10n_bo_withholding_tax_groups(self, company):
        return self._l10n_bo_tax_groups(company, (
            'tax_group_whh_goods', 'tax_group_whh_services',  # l10n_bo (grossing-up)
            'tax_group_whh_retained', 'tax_group_whh_rciva',  # l10n_bo_spa
        ))

    @api.model
    def _l10n_bo_is_vat_credit_tax(self, taxes, company):
        groups = self._l10n_bo_vat_tax_groups(company)
        return taxes.flatten_taxes_hierarchy().filtered(lambda t: t.tax_group_id in groups and t.amount)

    @api.model
    def _l10n_bo_is_withholding_tax(self, taxes, company):
        groups = self._l10n_bo_withholding_tax_groups(company)
        return taxes.filtered(lambda t: t.tax_group_id in groups or t.flatten_taxes_hierarchy().tax_group_id & groups)

    @api.model
    def _l10n_bo_withholding_tax(self, company, mode, kind):
        """Impuesto (grupo) a aplicar para una compra sin factura con retención."""
        if mode not in ('supplier_bears', 'company_bears') or not kind:
            return self.env['account.tax']
        return company._l10n_bo_get_withholding_tax(mode, kind)

    @api.model
    def _l10n_bo_purchase_vat_tax(self, company):
        """IVA de compras por defecto (crédito fiscal 13 %)."""
        tax = company.account_purchase_tax_id
        if tax and self._l10n_bo_is_vat_credit_tax(tax, company):
            return tax
        return self._l10n_bo_chart_ref(company, 'l10n_bo_iva_13_purchase') or self.env['account.tax']

    # ------------------------------------------------------------------
    # Lector QR
    # ------------------------------------------------------------------
    def _l10n_bo_qr_values(self, data):
        """Valores del documento a partir de los datos leídos del QR."""
        vals = {'l10n_bo_doc_type': data.get('doc_type')}
        for key, fname in (
            ('nit', 'l10n_bo_supplier_nit'), ('number', 'l10n_bo_invoice_number'), ('cuf', 'l10n_bo_cuf'),
            ('auth_number', 'l10n_bo_auth_number'), ('control_code', 'l10n_bo_control_code'),
        ):
            vals[fname] = data.get(key) or False
        return vals

    def _l10n_bo_partner_from_nit(self, nit):
        if not nit:
            return self.env['res.partner']
        partners = self.env['res.partner'].search([('vat', 'ilike', nit)], limit=20)
        return partners.filtered(lambda p: siat.normalize_nit(p.vat) == nit).commercial_partner_id[:1]

    def _l10n_bo_apply_qr_data(self, data):
        """Escribe en el documento los datos leídos del QR. Los modelos concretos completan
        fecha y monto."""
        self.ensure_one()
        self.write(self._l10n_bo_qr_values(data))
