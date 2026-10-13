# Part of ERP Servicios Spa. License LGPL-3.
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'spa')
class TestMessaging(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Message = cls.env['spa.message']
        cls.partner = cls.env['res.partner'].create({'name': 'María López', 'phone': '7123-4567'})

    def test_normalize_phone(self):
        self.assertEqual(self.Message._normalize_phone('7123-4567'), '59171234567')
        self.assertEqual(self.Message._normalize_phone('+591 71234567'), '59171234567')
        self.assertEqual(self.Message._normalize_phone('0059171234567'), '59171234567')
        self.assertFalse(self.Message._normalize_phone('22'))

    def test_queue_wa_link(self):
        message = self.Message.queue('renewal_notice', self.partner,
                                     {'plan': 'Premium', 'vence': '31/10/2026', 'monto': 'Bs 890,00'})
        self.assertEqual(message.state, 'ready')
        self.assertIn('Hola María', message.body)
        self.assertIn('Premium', message.body)
        self.assertTrue(message.wa_url.startswith('https://wa.me/59171234567?text='))
        action = message.action_open_whatsapp()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(message.state, 'sent')

    def test_inactive_template_and_missing_phone(self):
        self.assertFalse(self.Message.queue('booking_confirmed', self.partner, {}))
        nophone = self.env['res.partner'].create({'name': 'Sin celular'})
        self.assertFalse(self.Message.queue('renewal_notice', nophone, {}))

    def test_messages_are_isolated_by_company(self):
        """Celulares y textos (datos personales): cada empresa ve solo sus mensajes."""
        message = self.Message.queue('renewal_notice', self.partner, {})
        self.assertEqual(message.company_id, self.env.company)
        branch = self.env['res.company'].create({'name': 'Spa Sucursal (prueba)'})
        other = self.env['res.users'].create({
            'name': 'Recepción sucursal', 'login': 'spa_msg_branch', 'company_id': branch.id,
            'company_ids': [(6, 0, branch.ids)],
            'group_ids': [(6, 0, [self.env.ref('spa_base.group_spa_reception').id])]})
        self.assertFalse(self.Message.with_user(other).search([('id', '=', message.id)]))
        # El mensaje toma la empresa del registro relacionado.
        record = self.env['spa.space'].create({'name': 'Piscina sucursal', 'company_id': branch.id})
        branch_message = self.Message.queue('renewal_notice', self.partner, {}, record=record)
        self.assertEqual(branch_message.company_id, branch)
        self.assertIn('Spa Sucursal (prueba)', branch_message.body)
        self.assertEqual(self.Message.with_user(other).search([('id', 'in', (message | branch_message).ids)]),
                         branch_message)

    def test_meta_cloud_provider(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('spa_messaging.provider', 'meta_cloud')
        message = self.Message.queue('renewal_notice', self.partner, {})
        self.assertEqual(message.state, 'failed', 'Sin token debe fallar con un mensaje claro')
        params.set_param('spa_messaging.meta_token', 'TOKEN')
        params.set_param('spa_messaging.meta_phone_id', '123')

        class Response:
            status_code = 200
            text = '{}'

        with patch('odoo.addons.spa_messaging.models.spa_message.requests.post', return_value=Response()) as post:
            message.action_retry()
            self.assertEqual(message.state, 'sent')
            self.assertIn('/123/messages', post.call_args[0][0])
