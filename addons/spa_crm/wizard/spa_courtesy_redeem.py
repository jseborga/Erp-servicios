# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError


class SpaCourtesyRedeemWizard(models.TransientModel):
    _name = 'spa.courtesy.redeem.wizard'
    _description = 'Canjear pase de cortesía'

    token = fields.Char('Código del pase (escanee el QR)')
    pass_id = fields.Many2one('spa.courtesy.pass', string='O elija el pase', domain="[('state', '=', 'issued')]")
    space_id = fields.Many2one('spa.space', string='Espacio', required=True, domain="[('state', '=', 'active')]")
    service_id = fields.Many2one('spa.service', string='Servicio',
                                 domain="[('space_id', '=', space_id)]",
                                 help='Opcional: si el espacio tiene varios servicios, elija el que se usa.')

    @api.onchange('pass_id')
    def _onchange_pass_id(self):
        spaces = self.pass_id.service_ids.space_id
        if spaces and self.space_id not in spaces:
            self.space_id = spaces[:1]

    @api.onchange('token')
    def _onchange_token(self):
        """Al escanear el QR, propone el espacio del pase (como al elegirlo de la lista)."""
        if not self.token:
            return
        spaces = self.env['spa.courtesy.pass']._find_by_token(self.token).service_ids.space_id
        if spaces and self.space_id not in spaces:
            self.space_id = spaces[:1]

    def action_redeem(self):
        self.ensure_one()
        courtesy = self.pass_id
        method = 'manual'
        if self.token:
            courtesy = self.env['spa.courtesy.pass']._find_by_token(self.token)
            method = 'qr'
            if not courtesy:
                raise UserError(self.env._('Código de pase no reconocido. Verifique el código o búsquelo por nombre.'))
        if not courtesy:
            raise UserError(self.env._('Escanee el QR del pase o elíjalo de la lista.'))
        log = courtesy._redeem(self.space_id, service=self.service_id or None, method=method)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._('Cortesía canjeada'),
                'message': self.env._('%(name)s ingresó a %(space)s con el pase %(code)s. Le quedan %(left)s visita(s).',
                                      name=log.partner_id.name, space=self.space_id.name, code=courtesy.name,
                                      left=courtesy.visits_left),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
