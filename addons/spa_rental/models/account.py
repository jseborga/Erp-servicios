# Part of ERP Servicios Spa. License LGPL-3.
"""Facturación de alquileres y clases.

Regla fiscal (Ley 843, art. 4 inc. b): en la prestación de servicios el hecho imponible nace
al terminar el servicio o al percibir el precio, total o parcialmente, lo que ocurra primero.
Por eso las facturas de alquileres y clases se crean en BORRADOR y se validan solo al cobrar
o al terminar el evento o la clase; nunca antes.
"""
from odoo import Command, api, fields, models
from odoo.exceptions import UserError

RENTAL_MOVE_KINDS = [
    ('invoice', 'Factura del alquiler'),
    ('damage', 'Cargo por daños (garantía aplicada)'),
    ('deposit_apply', 'Aplicación de la garantía'),
]


class AccountMove(models.Model):
    _inherit = 'account.move'

    spa_invoice_kind = fields.Selection(selection_add=[
        ('rental', 'Alquiler de ambientes y eventos'),
        ('class', 'Clases y actividades'),
    ], ondelete={'rental': 'set null', 'class': 'set null'})
    spa_rental_id = fields.Many2one('spa.rental', string='Alquiler', index='btree_not_null', copy=False)
    spa_rental_move_kind = fields.Selection(RENTAL_MOVE_KINDS, string='Movimiento del alquiler', copy=False)

    @api.model
    def _spa_rental_line_vals(self, product, quantity=1.0, price=None, name=None, discount=0.0, analytic=None,
                              company=None):
        """Línea de factura con IVA + IT de la localización y el área analítica indicada."""
        company = company or self.env.company
        vals = {
            'product_id': product.id,
            'name': name or product.display_name,
            'quantity': quantity,
            'price_unit': product.lst_price if price is None else price,
            'discount': discount,
            'tax_ids': [Command.set(company._spa_sale_taxes().ids or product.taxes_id.ids)],
        }
        if analytic:
            vals['analytic_distribution'] = {str(analytic.id): 100}
        return vals

    def _spa_post_on_taxable_event(self):
        """Valida las facturas en borrador con la fecha (local) del hecho imponible."""
        drafts = self.sudo().filtered(lambda m: m.state == 'draft' and m.invoice_line_ids)
        if drafts:
            drafts.write({'invoice_date': self.env['spa.tools'].local_today()})
            drafts.action_post()
        return drafts

    def _spa_register_payment(self, amount, method, reference=None, date=None):
        """Valida la factura (si está en borrador) y registra el cobro en el diario del medio de pago."""
        self.ensure_one()
        invoice = self.sudo()
        if invoice.state == 'cancel':
            raise UserError(self.env._('La factura %s está anulada.', invoice.display_name))
        invoice._spa_post_on_taxable_event()
        if invoice.payment_state in ('paid', 'in_payment', 'reversed'):
            raise UserError(self.env._('La factura %s ya está pagada.', invoice.name))
        if invoice.currency_id.compare_amounts(amount, invoice.amount_residual) > 0:
            raise UserError(self.env._('El monto (%(amount)s) supera el saldo de la factura (%(due)s).',
                                       amount=invoice.currency_id.format(amount),
                                       due=invoice.currency_id.format(invoice.amount_residual)))
        journal = invoice.company_id._spa_journal(method)
        if not journal:
            raise UserError(self.env._('Configure el diario de cobro en Ajustes del spa.'))
        wizard = self.env['account.payment.register'].sudo().with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': journal.id,
                'amount': amount,
                'payment_date': date or self.env['spa.tools'].local_today(),
                'communication': ' '.join(filter(None, [invoice.name, reference])),
                'payment_difference_handling': 'open',
            })
        return wizard._create_payments()

    def _spa_credit_note(self, amount, name, date=None):
        """Nota de crédito en borrador por ``amount`` (IVA incluido) contra esta factura validada.

        Caja la valida y devuelve el dinero o lo deja como saldo a favor del cliente.
        """
        self.ensure_one()
        invoice = self.sudo()
        line = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')[:1]
        vals = {
            'product_id': line.product_id.id,
            'name': name,
            'quantity': 1.0,
            'price_unit': amount,
            'tax_ids': [Command.set(line.tax_ids.ids)],
        }
        if line.analytic_distribution:
            vals['analytic_distribution'] = line.analytic_distribution
        return self.env['account.move'].sudo().create({
            'move_type': 'out_refund',
            'partner_id': invoice.partner_id.id,
            'company_id': invoice.company_id.id,
            'invoice_date': date or self.env['spa.tools'].local_today(),
            'invoice_origin': invoice.name,
            'reversed_entry_id': invoice.id,
            'ref': name,
            'spa_invoice_kind': invoice.spa_invoice_kind,
            'spa_rental_id': invoice.spa_rental_id.id,
            'invoice_line_ids': [Command.create(vals)],
        })


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    spa_rental_id = fields.Many2one('spa.rental', string='Alquiler (garantía)', index='btree_not_null', copy=False)
    spa_deposit_kind = fields.Selection([('receive', 'Garantía recibida'), ('refund', 'Garantía devuelta')],
                                        string='Garantía', copy=False)


class SpaConsumption(models.Model):
    _inherit = 'spa.consumption'

    class_enrollment_id = fields.Many2one('spa.class.enrollment', string='Inscripción a clase',
                                          index='btree_not_null', ondelete='set null')
