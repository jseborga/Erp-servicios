# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaAccessLog(models.Model):
    _inherit = 'spa.access.log'

    courtesy_pass_id = fields.Many2one('spa.courtesy.pass', string='Pase de cortesía', readonly=True,
                                       index='btree_not_null', ondelete='restrict')

    @api.model
    def do_check_in(self, space, token=None, partner=None, guests=0, day_pass=False):
        """El mismo lector de QR de recepción acepta credenciales de socio y pases de cortesía."""
        if token:
            clean = token.strip()
            is_member = self.env['spa.membership'].sudo().search_count([('qr_token', '=', clean)], limit=1)
            if not is_member:
                courtesy = self.env['spa.courtesy.pass']._find_by_token(clean)
                if courtesy:
                    if guests:
                        raise UserError(self.env._('El pase de cortesía es personal: registre a cada '
                                                   'acompañante con su propio pase o entrada.'))
                    return courtesy._redeem(space, method='qr')
        return super().do_check_in(space, token=token, partner=partner, guests=guests, day_pass=day_pass)
