# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError

PAYMENT_METHODS = [
    ('cash', 'Efectivo'),
    ('qr', 'QR'),
    ('transfer', 'Transferencia / depósito'),
    ('card', 'Tarjeta'),
]


class SpaRentalPaymentWizard(models.TransientModel):
    """Caja registra el cobro de un alquiler, de su garantía o de una clase.

    El cobro de la factura la valida primero (hecho imponible: percepción del precio).
    La garantía se registra como un cobro aparte a la cuenta de garantías recibidas (216200).
    """
    _name = 'spa.rental.payment.wizard'
    _description = 'Registrar cobro de alquiler o clase'

    kind = fields.Selection([('invoice', 'Factura'), ('deposit', 'Garantía')], required=True, default='invoice')
    rental_id = fields.Many2one('spa.rental', string='Alquiler')
    enrollment_id = fields.Many2one('spa.class.enrollment', string='Inscripción')
    invoice_id = fields.Many2one('account.move', string='Factura')
    partner_id = fields.Many2one('res.partner', string='Cliente', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary('Monto', required=True)
    method = fields.Selection(PAYMENT_METHODS, string='Medio de pago', required=True, default='cash')
    reference = fields.Char('Referencia / Nº de transacción')

    @api.model
    def _spa_open(self, invoice=None, rental=None, enrollment=None, kind='invoice', amount=None):
        record = rental or enrollment
        invoice = invoice.sudo() if invoice else invoice
        if amount is None:
            amount = invoice.amount_residual if invoice and invoice.state == 'posted' else \
                (invoice.amount_total if invoice else 0.0)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Registrar cobro de garantía') if kind == 'deposit' else self.env._('Registrar cobro'),
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_kind': kind,
                'default_rental_id': rental.id if rental else False,
                'default_enrollment_id': enrollment.id if enrollment else False,
                'default_invoice_id': invoice.id if invoice else False,
                'default_partner_id': record.partner_id.id,
                'default_company_id': record.company_id.id,
                'default_amount': amount,
            },
        }

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('spa_base.group_spa_cashier'):
            raise UserError(self.env._('Solo caja registra cobros.'))
        if self.amount <= 0:
            raise UserError(self.env._('El monto debe ser mayor que cero.'))
        record = self.rental_id or self.enrollment_id
        if self.kind == 'deposit':
            if not self.rental_id:
                raise UserError(self.env._('La garantía se cobra desde el alquiler.'))
            self.rental_id._spa_receive_deposit(self.amount, self.method, self.reference)
            return True
        if not self.invoice_id:
            raise UserError(self.env._('No hay factura por cobrar.'))
        self.invoice_id._spa_register_payment(self.amount, self.method, self.reference)
        invoice = self.invoice_id.sudo()
        if record:
            record.message_post(body=self.env._('Cobro de %(amount)s registrado (%(method)s). Factura %(inv)s: %(state)s.',
                                                amount=self.currency_id.format(self.amount),
                                                method=dict(PAYMENT_METHODS)[self.method], inv=invoice.name,
                                                state=dict(invoice._fields['payment_state']._description_selection(
                                                    self.env))[invoice.payment_state]))
        return True
