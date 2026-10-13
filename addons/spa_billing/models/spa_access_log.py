# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class SpaAccessLog(models.Model):
    _inherit = 'spa.access.log'

    invoice_id = fields.Many2one('account.move', string='Factura (pase diario)', readonly=True, copy=False)

    def _after_day_pass(self):
        """Cobra el pase diario: producto del servicio × personas, área del espacio.

        La entrada se presta al ingresar (y se cobra en puerta), así que la factura se emite
        de inmediato (Ley 843 art. 4 inc. b). El pago lo registra recepción como pago por
        validar (efectivo, QR o tarjeta) y caja lo valida.
        """
        res = super()._after_day_pass()
        Membership = self.env['spa.membership']
        today = self.env['spa.tools'].local_today()
        for log in self.filtered(lambda l: l.day_pass and not l.invoice_id):
            service = log.service_id or log.space_id._free_mode_service()
            line = Membership._spa_line_vals(
                service.product_id, quantity=log.people,
                name=self.env._('Pase diario %(space)s – %(name)s (%(people)s persona/s)',
                                space=log.space_id.name, name=log.partner_id.name, people=log.people),
                analytic=log.space_id.analytic_account_id)
            invoice = self.env['account.move'].sudo().create({
                'move_type': 'out_invoice',
                'partner_id': log.partner_id.id,
                'invoice_date': today,
                'invoice_date_due': today,
                'invoice_origin': self.env._('Pase diario %s', log.space_id.name),
                'spa_invoice_kind': 'single',
                'invoice_line_ids': [(0, 0, line)],
                'company_id': log.company_id.id,
            })
            invoice.action_post()
            log.invoice_id = invoice
        return res


class SpaCheckinWizard(models.TransientModel):
    _inherit = 'spa.checkin.wizard'

    def action_check_in(self):
        """Tras un pase diario: confirma el ingreso y abre el registro del pago (efectivo por defecto)."""
        action = super().action_check_in()
        if not self.day_pass or not isinstance(action, dict) or 'params' not in action:
            return action
        log = self.env['spa.access.log'].search([
            ('space_id', '=', self.space_id.id), ('day_pass', '=', True), ('invoice_id', '!=', False),
            ('create_uid', '=', self.env.uid)], order='id desc', limit=1)
        invoice = log.invoice_id.sudo()
        if not invoice or invoice.amount_residual <= 0:
            return action
        action['params']['next'] = {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cobrar pase diario'),
            'res_model': 'spa.payment.request',
            'view_mode': 'form',
            'views': [(False, 'form')],  # acción anidada: el cliente web exige «views»
            'target': 'new',
            'context': {
                'default_partner_id': log.partner_id.id,
                'default_invoice_id': invoice.id,
                'default_amount': invoice.amount_residual,
                'default_method': 'cash',
                'default_channel': 'reception',
            },
        }
        return action
