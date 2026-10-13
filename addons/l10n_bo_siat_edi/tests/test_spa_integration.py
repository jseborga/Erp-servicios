# Part of ERP Servicios Spa. License LGPL-3.
"""Integración con el spa: facturas de membresías creadas en el servidor (spa_billing) y
pagadas con "Pagos por validar". Se omiten si spa_billing no está instalado."""
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_bo_purchase.tools import siat

from .common import L10nBoSiatCommon

try:
    from odoo.addons.spa_membership.tests.common import SpaCommon
except ImportError:  # spa_membership no está en la ruta de módulos
    SpaCommon = TransactionCase

REGISTER = 'l10n_bo_siat_edi.mail_activity_siat_register'


@tagged('post_install', '-at_install', 'spa')
class TestSiatSpaIntegration(SpaCommon):

    def setUp(self):
        super().setUp()
        if 'spa.payment.request' not in self.env or self.env.company.country_code != 'BO':
            self.skipTest('Requiere spa_billing instalado y la compañía principal con el plan boliviano.')
        self.company = self.env.company
        self.company.vat = '1020703023'
        self.demo = self.env['l10n_bo.siat.provider']._l10n_bo_create_demo(self.company)

    def _member_invoice(self):
        membership = self._membership(self.plan_premium, activate=False)
        invoice = membership.action_create_invoice()
        return membership, invoice

    def _pay(self, invoice):
        request = self.env['spa.payment.request'].create({
            'partner_id': invoice.partner_id.id, 'membership_id': invoice.spa_membership_id.id,
            'invoice_id': invoice.id, 'amount': invoice.amount_residual, 'method': 'qr', 'reference': 'TRX-SIAT'})
        request.action_validate()
        return request

    def _assert_paid_and_active(self, membership, invoice):
        request = self._pay(invoice)
        self.assertEqual(request.state, 'validated')
        self.assertEqual(invoice.payment_state, 'paid')
        self.assertEqual(membership.state, 'active')

    def test_membership_invoice_portal_web(self):
        self.company.l10n_bo_siat_mode = 'portal_web'
        membership, invoice = self._member_invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_total, 890.0)
        self.assertEqual(invoice.l10n_bo_siat_state, 'to_send')
        self.assertEqual(invoice.l10n_bo_sale_buyer_number, '0')
        register = self.env.ref(REGISTER)
        self.assertTrue(invoice.activity_ids.filtered(lambda a: a.activity_type_id == register))
        self._assert_paid_and_active(membership, invoice)
        # La caja registra después la factura emitida en el Portal Web.
        cuf = siat.encode_cuf('1020703023', L10nBoSiatCommon._local_now(), 0, 3, 1, 1, 1, 501, 0, '67A75AC82F24C74')
        invoice._l10n_bo_siat_register('501', cuf)
        self.assertEqual(invoice.l10n_bo_siat_state, 'accepted')
        row = self.env['l10n_bo.sale.book'].search([('move_id', '=', invoice.id)])
        self.assertAlmostEqual(row.amount_debit, 115.70, places=2)

    def test_membership_invoice_demo_provider(self):
        self.company.write({'l10n_bo_siat_mode': 'provider', 'l10n_bo_siat_provider_id': self.demo.id})
        membership, invoice = self._member_invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.l10n_bo_siat_state, 'accepted')
        self.assertTrue(invoice.l10n_bo_siat_cuf.startswith('SIMULADO'))
        self._assert_paid_and_active(membership, invoice)

    def test_membership_invoice_mode_none(self):
        self.company.l10n_bo_siat_mode = 'none'
        membership, invoice = self._member_invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.l10n_bo_siat_state, 'not_applicable')
        self.assertFalse(invoice.activity_ids)
        self._assert_paid_and_active(membership, invoice)

    def test_membership_invoice_without_company_nit_is_not_blocked(self):
        self.company.write({'l10n_bo_siat_mode': 'provider', 'l10n_bo_siat_provider_id': self.demo.id})
        self.company.vat = False
        membership, invoice = self._member_invoice()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.l10n_bo_siat_state, 'rejected')
        self.assertIn('NIT de la compañía', invoice.l10n_bo_siat_log)
        self._assert_paid_and_active(membership, invoice)

    def test_cancelled_membership_invoice_is_reissued(self):
        self.company.write({'l10n_bo_siat_mode': 'provider', 'l10n_bo_siat_provider_id': self.demo.id})
        membership, invoice = self._member_invoice()
        invoice._l10n_bo_siat_cancel(self.env.ref('l10n_bo_siat_edi.cancel_reason_1'))
        self.assertEqual(invoice.l10n_bo_siat_state, 'cancelled')
        self.assertEqual(invoice.payment_state, 'reversed')
        # La membresía ya no considera abierta la factura anulada y emite una nueva.
        new_invoice = membership.action_create_invoice()
        self.assertNotEqual(new_invoice, invoice)
        self.assertEqual(new_invoice.l10n_bo_siat_state, 'accepted')
        self._assert_paid_and_active(membership, new_invoice)
