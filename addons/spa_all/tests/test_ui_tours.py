# Part of ERP Servicios Spa. License LGPL-3.
"""Pruebas de humo de la interfaz (navegador) por rol.

Recorren con Chrome headless las pantallas principales de cada rol: aforo en vivo y asistentes de
recepción, pagos por validar, reportes del gerente (incluido el estado de resultados MIS por área),
embudos de marketing, Libro de Compras y la web del socio. Fallan ante cualquier error de JavaScript,
de permisos o del servidor.

Necesitan Chrome/Chromium: Odoo lo busca en el PATH o en la variable ``ODOO_BROWSER_BIN``, p. ej.::

    ODOO_BROWSER_BIN=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \\
        odoo -d spa -u spa_all --test-tags /spa_all:TestSpaUiTours --stop-after-init

Sin navegador, Odoo las omite (skip). Etiqueta propia: ``spa_ui``.

``TestSpaUiActions`` verifica sin navegador (siempre se ejecuta) lo que esos recorridos encontraron:
acciones que el cliente web no podía abrir y etiquetas que aparecían en inglés.
"""
from datetime import date

from odoo.tests import Form, HttpCase, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.spa_portal.controllers.main import day_label

from .common import PNG_B64, SpaE2EMixin


@tagged('post_install', '-at_install', 'spa', 'spa_ui')
class TestSpaUiActions(SpaE2EMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()
        cls.space_sauna.write({'open_hour': 0.0, 'close_hour': 24.0})
        cls.ana = cls._partner('Ana Rojas', '+591 70000101', 'ana.rojas@socios.example.com')
        cls.m_ana = cls._enroll(cls.ana, cls.plan_premium)
        cls.visitor = cls._partner('Turista UI', '+591 70000999')

    def _check_in(self, partner):
        wizard = Form(self.env['spa.checkin.wizard'].with_user(self.reception).with_context(
            default_space_id=self.space_sauna.id))
        wizard.partner_id = partner
        return wizard.save().action_check_in()

    def test_checkin_next_actions_have_views(self):
        """El cliente web exige «views» en la acción anidada (antes: «Cannot read properties of undefined»)."""
        action = self._check_in(self.ana)
        following = action['params']['next']
        self.assertEqual(following['res_model'], 'spa.checkin.wizard')
        self.assertEqual(following['views'], [(False, 'form')])
        action = self._check_in(self.visitor)  # sin membresía: pase diario y su cobro
        following = action['params']['next']
        self.assertEqual(following['res_model'], 'spa.payment.request')
        self.assertEqual(following['views'], [(False, 'form')])
        # Recepción no ve la factura: el cobro se muestra igual en el pago nuevo.
        request = Form(self.env['spa.payment.request'].with_user(self.reception).with_context(**following['context']))
        self.assertTrue(request.invoice_label)

    def test_manager_report_actions(self):
        # «Apuntes analíticos por área»: el gerente (solo lectura del reporte) puede abrirlo.
        action = self.env.ref('spa_reports.spa_report_area_analytic_server_action').with_user(self.manager).run()
        self.assertEqual(action['res_model'], 'account.analytic.line')
        # «Estado de resultados por área»: el widget de MIS toma la instancia del contexto.
        window = self.env.ref('spa_reports.mis_instance_area_pl_action')
        context = safe_eval(window.context)
        self.assertEqual(context['active_model'], 'mis.report.instance')
        self.assertEqual(context['active_id'], self.env.ref('spa_reports.mis_instance_area_pl').id)
        # Resumen: migas de pan legibles.
        dashboard = self.env['spa.report.dashboard'].with_user(self.manager).create({})
        self.assertEqual(dashboard.display_name, 'Resumen del spa')

    def test_payment_receipt_preview_and_new_record_names(self):
        request = self._register_payment(self.m_ana, method='qr', user=self.reception)
        request.write({'receipt': PNG_B64, 'receipt_filename': 'comprobante.PNG'})
        self.assertTrue(request.receipt_is_image)
        request.receipt_filename = 'comprobante.pdf'
        self.assertFalse(request.receipt_is_image)
        # Registros aún sin número: sin el «/» provisional en las migas de pan.
        courtesy = self.env['spa.courtesy.pass'].with_user(self.marketing).new({'name': '/', 'guest_name': 'Jorge Arce'})
        self.assertEqual(courtesy.display_name, 'Jorge Arce')

    def test_spanish_labels(self):
        """Ningún campo de nuestros modelos con la etiqueta inglesa que Odoo genera del nombre técnico."""
        english = {}
        for name, model in self.env.registry.items():
            if not name.startswith(('spa.', 'l10n_bo.')) or model._abstract:
                continue
            for field_name in ('state', 'active', 'company_id', 'phone', 'email', 'channel'):
                field = model._fields.get(field_name)
                if field and field.string in ('State', 'Active', 'Company', 'Phone', 'Email', 'Channel'):
                    english.setdefault(name, []).append(field_name)
        self.assertFalse(english, 'Etiquetas en inglés: %s' % english)
        self.env['res.lang']._activate_lang('es_BO')
        env_es = self.env(context=dict(self.env.context, lang='es_BO'))
        self.assertEqual(day_label(env_es, date(2026, 10, 15)), 'Jueves 15 de octubre')


@tagged('post_install', '-at_install', 'spa_ui')
class TestSpaUiTours(SpaE2EMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._e2e_setup()
        cls.ana = cls._partner('Ana Rojas', '+591 70000101', 'ana.rojas@socios.example.com')
        cls._enroll(cls.ana, cls.plan_premium)
        # Bruno informó un pago por QR que caja aún no valida.
        bruno = cls._partner('Bruno Salinas', '+591 70000102', 'bruno.salinas@socios.example.com')
        membership = cls.env['spa.membership'].with_user(cls.reception).create({
            'partner_id': bruno.id, 'plan_id': cls.plan_basic.id, 'period_id': cls._period(cls.plan_basic, 1).id})
        membership.with_user(cls.reception).action_create_invoice()
        cls._register_payment(membership, method='qr', reference='QR-UI-0001', user=cls.reception)
        cls.lucia = cls._portal_member('e2e_lucia', 'Lucía Fernández', phone='+591 72000002')
        cls._enroll(cls.lucia.partner_id, cls.plan_premium)
        # La sauna atiende todo el día en esta prueba: el recorrido registra ingresos a cualquier hora.
        cls.space_sauna.write({'open_hour': 0.0, 'close_hour': 24.0})
        cls._partner('Turista UI', '+591 70000999')
        cls.env['crm.lead'].with_user(cls.marketing).create({
            'name': 'Consulta por Instagram: Sofía Vargas', 'contact_name': 'Sofía Vargas',
            'phone': '+591 71234567', 'source_id': cls.env.ref('spa_crm.utm_source_instagram').id})

    def _tour(self, name, user, url='/odoo'):
        self.start_tour(url, name, login=user.login, timeout=180)

    def test_reception(self):
        self._tour('spa_ui_reception', self.reception)

    def test_cashier(self):
        self._tour('spa_ui_cashier', self.cashier)

    def test_manager(self):
        self._tour('spa_ui_manager', self.manager)

    def test_marketing(self):
        self._tour('spa_ui_marketing', self.marketing)

    def test_accountant(self):
        self._tour('spa_ui_accountant', self.accountant,
                   url='/odoo/action-l10n_bo_purchase.l10n_bo_purchase_book_action')

    def test_portal_member(self):
        self._tour('spa_ui_portal', self.lucia, url='/my/spa')
