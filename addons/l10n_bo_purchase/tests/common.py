# Part of ERP Servicios Spa. License LGPL-3.
from contextlib import contextmanager
from datetime import datetime

from odoo import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_bo_purchase.tools import siat


class L10nBoPurchaseCommon(AccountTestInvoicingCommon):
    """Compañía de prueba con el plan 'bo' (l10n_bo + l10n_bo_spa)."""

    @classmethod
    @AccountTestInvoicingCommon.setup_chart_template('bo')
    def setUpClass(cls):
        super().setUpClass()
        cls.ct = cls.env['account.chart.template']
        cls.company = cls.env.company
        cls.company.l10n_bo_purchase_check = True
        cls.env.user.group_ids |= cls.env.ref('l10n_bo_purchase.group_spa_accountant')
        cls.supplier = cls.env['res.partner'].create({'name': 'Distribuidora Andina SRL', 'vat': '1020703023'})
        cls.supplier_b = cls.env['res.partner'].create({'name': 'Ferretería Illimani', 'vat': '3115970018'})
        cls.person = cls.env['res.partner'].create({'name': 'Juan Mamani (sin NIT)'})

    @contextmanager
    def assertRaisesText(self, exception, text):
        """Como assertRaises (revierte al punto de guardado) y verifica el texto del mensaje."""
        with self.assertRaises(exception) as capture:
            yield capture
        self.assertIn(text, str(capture.exception))

    @classmethod
    def _ref(cls, xmlid):
        return cls.ct.ref(xmlid)

    @staticmethod
    def _cuf(nit, number, when=None):
        return siat.encode_cuf(nit, when or datetime(2026, 10, 10, 9, 30, 0, 250000),
                               0, 1, 1, 1, 1, number, 0, '67A75AC82F24C74')

    def _bill(self, partner=None, doc_type='siat_online', number=None, cuf=None, auth=None, control=None,
              price=1130.0, taxes=('l10n_bo_iva_13_purchase',), account='l10n_bo_spa_53017', **extra):
        partner = partner or self.supplier
        tax_ids = self.env['account.tax']
        for xmlid in taxes:
            tax_ids |= self._ref(xmlid)
        vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': '2026-10-10',
            'l10n_bo_doc_type': doc_type,
            'invoice_line_ids': [Command.create({
                'name': 'Compra de prueba',
                'account_id': self._ref(account).id,
                'price_unit': price,
                'quantity': 1,
                'tax_ids': [Command.set(tax_ids.ids)],
            })],
        }
        if number:
            vals['l10n_bo_invoice_number'] = str(number)
        if doc_type == 'siat_online' and number and cuf is None:
            cuf = self._cuf(partner.vat, number)
        if cuf:
            vals['l10n_bo_cuf'] = cuf
        if auth:
            vals['l10n_bo_auth_number'] = auth
        if control:
            vals['l10n_bo_control_code'] = control
        vals.update(extra)
        return self.env['account.move'].create(vals)

    @staticmethod
    def _balances(move):
        result = {}
        for line in move.line_ids:
            code = line.account_id.code
            result[code] = round(result.get(code, 0.0) + line.balance, 2)
        return result
