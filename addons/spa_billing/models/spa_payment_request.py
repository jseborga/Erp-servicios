# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError

from .account_move import PENDING_KINDS


class SpaPaymentRequest(models.Model):
    """Pago informado por el socio o por recepción, pendiente de validación en caja."""
    _name = 'spa.payment.request'
    _description = 'Pago por validar'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char('Número', readonly=True, copy=False, default='/')
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True, tracking=True)
    membership_id = fields.Many2one('spa.membership', string='Membresía', check_company=True)
    invoice_id = fields.Many2one('account.move', string='Factura', required=True, check_company=True,
                                 domain="[('partner_id', '=', partner_id), ('move_type', '=', 'out_invoice'), "
                                        "('payment_state', 'not in', ('paid', 'reversed')), '|', ('state', '=', 'posted'), "
                                        "'&', ('state', '=', 'draft'), ('spa_invoice_kind', 'in', %s)]" % (list(PENDING_KINDS),),
                                 help='Factura emitida o cobro pendiente del spa (se emite la factura al validar el pago).')
    # Sin compute_sudo: sudo() descarta del contexto los «default_*» que usa el cálculo (lee con sudo adentro).
    invoice_label = fields.Char('Cobro', compute='_compute_invoice_label',
                                help='Factura emitida o cobro pendiente (número de la membresía o la reserva).')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, string='Compañía')
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary('Monto pagado', required=True, tracking=True)
    method = fields.Selection([
        ('qr', 'QR'),
        ('transfer', 'Transferencia / depósito'),
        ('cash', 'Efectivo'),
        ('card', 'Tarjeta'),
    ], string='Medio de pago', required=True, default='qr', tracking=True)
    reference = fields.Char('Referencia / Nº de transacción')
    receipt = fields.Binary('Comprobante', attachment=True)
    receipt_filename = fields.Char('Nombre del comprobante')
    receipt_is_image = fields.Boolean('Comprobante en imagen', compute='_compute_receipt_is_image',
                                      help='Para mostrar a caja la vista previa del comprobante.')
    channel = fields.Selection([('portal', 'Web del socio'), ('reception', 'Recepción'), ('whatsapp', 'WhatsApp')],
                               default='reception', required=True, string='Canal')
    state = fields.Selection([
        ('pending', 'Por validar'),
        ('validated', 'Validado'),
        ('rejected', 'Rechazado'),
    ], default='pending', required=True, tracking=True, index=True, string='Estado')
    payment_id = fields.Many2one('account.payment', string='Pago contable', readonly=True, copy=False)
    validated_by_id = fields.Many2one('res.users', string='Validado por', readonly=True, copy=False)
    validated_date = fields.Datetime('Validado el', readonly=True, copy=False)
    reject_reason = fields.Char('Motivo de rechazo')

    @api.depends('receipt_filename')
    def _compute_receipt_is_image(self):
        for request in self:
            name = (request.receipt_filename or '').lower()
            request.receipt_is_image = name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'))

    @api.depends('invoice_id.name', 'invoice_id.state', 'invoice_id.invoice_origin')
    def _compute_invoice_label(self):
        default_id = self.env.context.get('default_invoice_id')
        for request in self:
            invoice = request.sudo().invoice_id  # recepción no lee facturas
            if not invoice and not request.id and isinstance(default_id, int):
                # Pago nuevo abierto desde una membresía o un pase diario: recepción no ve el campo
                # Factura; se muestra el cobro del contexto para que sepa qué está cobrando.
                invoice = self.env['account.move'].sudo().browse(default_id).exists()
            request.invoice_label = invoice._spa_document_label() if invoice else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('spa.payment.request') or '/'
        requests = super().create(vals_list)
        for request in requests:
            if request.amount <= 0:
                raise UserError(self.env._('El monto pagado debe ser mayor que cero.'))
        return requests

    def action_validate(self):
        if not self.env.user.has_group('spa_base.group_spa_cashier'):
            raise UserError(self.env._('Solo caja puede validar pagos.'))
        for request in self:
            if request.state != 'pending':
                raise UserError(self.env._('El pago %s ya fue procesado.', request.name))
            invoice = request.invoice_id
            if invoice.state == 'cancel':
                raise UserError(self.env._(
                    'El cobro %s fue anulado (membresía vencida o cancelada, o reserva cancelada). Rechace este pago '
                    'o regístrelo en un cobro vigente.', invoice.sudo()._spa_document_label()))
            if invoice.payment_state in ('paid', 'reversed'):
                raise UserError(self.env._('La factura %s ya está pagada.', invoice.name))
            if invoice.state == 'draft':
                if not invoice.sudo()._spa_is_pending_charge():
                    raise UserError(self.env._('La factura %s está en borrador: el contador debe validarla antes.',
                                               invoice.display_name))
                if invoice.currency_id.compare_amounts(request.amount, invoice.amount_residual) > 0:
                    raise UserError(self.env._('El monto (%(amount)s) supera el saldo de la factura (%(due)s).',
                                               amount=invoice.currency_id.format(request.amount),
                                               due=invoice.currency_id.format(invoice.amount_residual)))
                # Hecho imponible: se cobra el precio (total o parcial) → se emite la factura hoy.
                invoice.sudo()._spa_post_pending()
            if invoice.currency_id.compare_amounts(request.amount, invoice.amount_residual) > 0:
                raise UserError(self.env._('El monto (%(amount)s) supera el saldo de la factura (%(due)s).',
                                           amount=invoice.currency_id.format(request.amount),
                                           due=invoice.currency_id.format(invoice.amount_residual)))
            journal = request.company_id._spa_journal(request.method)
            if not journal:
                raise UserError(self.env._('Configure el diario de cobro en Ajustes del spa.'))
            wizard = self.env['account.payment.register'].sudo().with_context(
                active_model='account.move', active_ids=invoice.ids).create({
                    'journal_id': journal.id,
                    'amount': request.amount,
                    'payment_date': self.env['spa.tools'].local_today(),
                    'communication': ' '.join(filter(None, [invoice.name, request.reference])),
                    'payment_difference_handling': 'open',
                })
            payments = wizard._create_payments()
            request.write({
                'state': 'validated',
                'payment_id': payments[:1].id,
                'validated_by_id': self.env.user.id,
                'validated_date': fields.Datetime.now(),
            })
            # Pago de la primera cuota: activa la membresía sin esperar el total.
            invoice._spa_apply_period(partial=True)
            # Pago de una cuota atrasada: reactiva la membresía suspendida por esa cuota.
            invoice._spa_after_payment()
            request.message_post(body=self.env._('Pago validado y registrado en %s.', journal.name))
        return True

    def action_reject(self):
        for request in self:
            if request.state != 'pending':
                raise UserError(self.env._('El pago %s ya fue procesado.', request.name))
            if not request.reject_reason:
                raise UserError(self.env._('Indique el motivo del rechazo.'))
            request.state = 'rejected'
            self.env['spa.message'].queue('payment_rejected', request.partner_id, {
                'monto': request.currency_id.format(request.amount), 'motivo': request.reject_reason,
            }, record=request)
        return True
