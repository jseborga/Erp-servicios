# Part of ERP Servicios Spa. License LGPL-3.
import re

from odoo import api, models

# Dígitos que se comparan: el celular boliviano tiene 8 (7xxxxxxx / 6xxxxxxx) y el
# código de país (591) o los prefijos 00/+ se ignoran.
PHONE_MATCH_DIGITS = 8
PHONE_MIN_DIGITS = 7


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _spa_phone_digits(self, phone):
        """Últimos 8 dígitos de un celular, o '' si no parece un número válido."""
        digits = re.sub(r'\D', '', phone or '')
        return digits[-PHONE_MATCH_DIGITS:] if len(digits) >= PHONE_MIN_DIGITS else ''

    @api.model
    def _spa_find_by_phone(self, phone):
        """Contacto con el mismo celular aunque esté escrito distinto.

        «+591 700-11122», «70011122» y «00591 70011122» son el mismo número: se comparan
        los últimos 8 dígitos. Devuelve el contacto más antiguo (el original) o un
        recordset vacío. Respeta los permisos del entorno (use ``sudo()`` si hace falta).
        """
        key = self._spa_phone_digits(phone)
        if not key:
            return self.browse()
        self.flush_model(['phone'])
        self.env.cr.execute("""
            SELECT id FROM res_partner
             WHERE phone IS NOT NULL AND active
               AND right(regexp_replace(phone, '[^0-9]', '', 'g'), %s) = %s
             ORDER BY id
        """, [PHONE_MATCH_DIGITS, key])
        ids = [row[0] for row in self.env.cr.fetchall()]
        if not ids:
            return self.browse()
        # search() aplica reglas de registro y multiempresa del usuario.
        return self.search([('id', 'in', ids)], order='id', limit=1)
