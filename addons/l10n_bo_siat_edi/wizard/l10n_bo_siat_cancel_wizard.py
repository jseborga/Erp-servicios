# Part of ERP Servicios Spa. License LGPL-3.
from odoo import api, fields, models


class L10nBoSiatCancelWizard(models.TransientModel):
    """Anulación de una factura en el SIAT y reversión contable."""
    _name = 'l10n_bo.siat.cancel.wizard'
    _description = 'Anular factura en el SIAT'

    move_id = fields.Many2one('account.move', string='Factura', required=True, readonly=True, ondelete='cascade')
    siat_number = fields.Char(related='move_id.l10n_bo_siat_number', string='N.º de factura SIAT')
    cuf = fields.Char(related='move_id.l10n_bo_siat_cuf', string='CUF')
    uses_provider = fields.Boolean(compute='_compute_info')
    simulated = fields.Boolean(related='move_id.l10n_bo_siat_simulated')
    deadline = fields.Date(string='Plazo para anular', compute='_compute_info')
    reason_id = fields.Many2one('l10n_bo.siat.cancel.reason', string='Motivo de anulación')
    note = fields.Char(string='Detalle')
    manual_confirmed = fields.Boolean(
        string='Confirmo que ya anulé la factura en el Portal Web del SIN',
        help='La factura se emitió en el Portal Web: anúlela allí primero (con el mismo motivo) y luego confírmelo aquí.')

    @api.model
    def _action_open(self, move):
        wizard = self.create({'move_id': move.id})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Anular en SIAT'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('move_id')
    def _compute_info(self):
        for wizard in self:
            move = wizard.move_id
            wizard.uses_provider = bool(move) and move._l10n_bo_siat_uses_provider()
            wizard.deadline = move._l10n_bo_siat_cancel_deadline() if move else False

    def action_confirm(self):
        self.ensure_one()
        reversal = self.move_id._l10n_bo_siat_cancel(self.reason_id, note=self.note, manual_confirmed=self.manual_confirmed)
        if reversal:
            return reversal._get_records_action(name=self.env._('Reversión por anulación SIAT'))
        return {'type': 'ir.actions.act_window_close'}
