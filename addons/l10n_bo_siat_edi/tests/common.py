# Part of ERP Servicios Spa. License LGPL-3.
from contextlib import contextmanager
from datetime import datetime

import pytz

from odoo import Command, fields

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.l10n_bo_purchase.tools import siat

COMPANY_NIT = '1020703023'
OTHER_NIT = '3115970018'


class L10nBoSiatCommon(AccountTestInvoicingCommon):
    """Compañía de prueba con el plan 'bo' (l10n_bo + l10n_bo_spa) y NIT."""

    @classmethod
    @AccountTestInvoicingCommon.setup_chart_template('bo')
    def setUpClass(cls):
        super().setUpClass()
        cls.ct = cls.env['account.chart.template']
        cls.company = cls.env.company
        cls.company.write({'vat': COMPANY_NIT, 'l10n_bo_siat_mode': 'portal_web'})
        cls.sale_taxes = cls.ct.ref('l10n_bo_iva_13_sale') | cls.ct.ref('l10n_bo_it_3_sale')
        cls.customer = cls.env['res.partner'].create({'name': 'Ana Pérez (sin NIT)'})
        cls.customer_nit = cls.env['res.partner'].create({'name': 'Hotel Illimani SRL', 'vat': OTHER_NIT})
        cls.demo = cls.env['l10n_bo.siat.provider']._l10n_bo_create_demo(cls.company)
        cls.reason = cls.env.ref('l10n_bo_siat_edi.cancel_reason_1')
        cls.no_invoice_group = cls.env.ref('l10n_bo_siat_edi.group_l10n_bo_sale_no_invoice')

    @contextmanager
    def assertRaisesText(self, exception, text):
        with self.assertRaises(exception) as capture:
            yield capture
        self.assertIn(text, str(capture.exception))

    @staticmethod
    def _local_now():
        return datetime.now(pytz.timezone('America/La_Paz')).replace(tzinfo=None, microsecond=0)

    @classmethod
    def _cuf(cls, number, nit=COMPANY_NIT, when=None):
        """CUF con dígito verificador válido (modalidad 3, sector 1) para la compañía de prueba."""
        return siat.encode_cuf(nit, when or cls._local_now(), 0, 3, 1, 1, 1, number, 0, '67A75AC82F24C74')

    def _use_demo(self):
        self.company.write({'l10n_bo_siat_mode': 'provider', 'l10n_bo_siat_provider_id': self.demo.id})

    def _invoice(self, price=890.0, partner=None, post=True, discount=0.0, **vals):
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': (partner or self.customer).id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [Command.create({
                'name': 'Membresía Premium – mensual',
                'price_unit': price,
                'quantity': 1,
                'discount': discount,
                'tax_ids': [Command.set(self.sale_taxes.ids)],
            })],
            **vals,
        })
        if post:
            move.action_post()
        return move

    def _register(self, move, number, cuf=None, **extra):
        action = move.action_l10n_bo_siat_open_register()
        wizard = self.env['l10n_bo.siat.register.wizard'].browse(action['res_id'])
        wizard.write({'siat_number': str(number), 'cuf': cuf or self._cuf(number), **extra})
        wizard.action_confirm()
        return wizard

    def _cancel(self, move, manual=True, reason=None):
        action = move.action_l10n_bo_siat_open_cancel()
        wizard = self.env['l10n_bo.siat.cancel.wizard'].browse(action['res_id'])
        wizard.write({'reason_id': (reason or self.reason).id, 'manual_confirmed': manual, 'note': 'NIT mal digitado'})
        wizard.action_confirm()
        return move.reversal_move_ids

    def _activities(self, move, xmlid):
        activity_type = self.env.ref(xmlid)
        return move.activity_ids.filtered(lambda a: a.activity_type_id == activity_type)

    def _book(self, move):
        return self.env['l10n_bo.sale.book'].search([('move_id', '=', move.id)])
