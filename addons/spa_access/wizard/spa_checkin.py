# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models


class SpaCheckinWizard(models.TransientModel):
    _name = 'spa.checkin.wizard'
    _description = 'Registrar ingreso'

    space_id = fields.Many2one('spa.space', string='Espacio', required=True,
                               default=lambda self: self.env.context.get('default_space_id'))
    token = fields.Char('Credencial (escanee el QR)')
    partner_id = fields.Many2one('res.partner', string='O busque a la persona')
    guests = fields.Integer('Invitados que ingresan', default=0)

    def action_check_in(self):
        self.ensure_one()
        log = self.env['spa.access.log'].do_check_in(
            self.space_id, token=self.token or None, partner=self.partner_id or None, guests=self.guests)
        message = self.env._('%(name)s ingresó a %(space)s. Ocupación: %(n)s de %(cap)s.',
                             name=log.partner_id.name, space=self.space_id.name,
                             n=self.space_id.occupancy, cap=self.space_id.capacity)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._('Ingreso registrado'),
                'message': message,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': self._name,
                    'view_mode': 'form',
                    'target': 'new',
                    'name': self.env._('Registrar ingreso'),
                    'context': {'default_space_id': self.space_id.id},
                },
            },
        }
