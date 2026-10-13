# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.spa_membership.tests.common import SpaCommon


@tagged('post_install', '-at_install', 'spa')
class TestSpaCrm(SpaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env['crm.lead']
        cls.Pass = cls.env['spa.courtesy.pass']
        cls.Guest = cls.env['spa.guest']
        cls.Membership = cls.env['spa.membership']
        cls.Log = cls.env['spa.access.log']
        cls.team_acq = cls.env.ref('spa_crm.team_acquisition')
        cls.team_ret = cls.env.ref('spa_crm.team_retention')
        cls.sauna_space = cls.env.ref('spa_base.space_sauna')
        # Las pruebas corren a cualquier hora: el sauna atiende todo el día (el horario se prueba aparte).
        cls.sauna_space.write({'open_hour': 0.0, 'close_hour': 24.0})
        cls.icp = cls.env['ir.config_parameter'].sudo()
        for key, value in {
            'spa_crm.guest_welcome': 'True',
            'spa_crm.followup_days': '1',
            'spa_crm.courtesy_monthly_limit': '0',
            'spa_crm.courtesy_validity_days': '15',
            'spa_crm.retention_low_usage_pct': '0',
            'spa_crm.retention_low_usage_day': '15',
            'spa_crm.retention_expiry_days': '0',
        }.items():
            cls.icp.set_param(key, value)
        cls.reception = new_test_user(cls.env, login='spa_crm_reception', groups='spa_base.group_spa_reception')
        cls.manager = new_test_user(cls.env, login='spa_crm_manager', groups='spa_base.group_spa_manager')
        cls.member = cls._membership(cls.plan_premium)

    def _stage(self, code):
        return self.env.ref(f'spa_crm.stage_{code}')

    def _partner(self, name, phone=None, email=None):
        return self.env['res.partner'].create({'name': name, 'phone': phone, 'email': email})

    def _pass(self, user=None, **vals):
        values = {
            'guest_name': 'Sofía Vargas',
            'phone': '71234567',
            'service_ids': [(6, 0, self.sauna.ids)],
        }
        values.update(vals)
        return self.Pass.with_user(user or self.reception).create(values).sudo()

    def _retention_leads(self, membership):
        return self.Lead.with_context(active_test=False).search(
            [('spa_membership_id', '=', membership.id), ('team_id', '=', self.team_ret.id)])

    # ------------------------------------------------------------------
    # Invitados → prospectos
    # ------------------------------------------------------------------
    def test_guest_becomes_referred_lead_without_duplicates(self):
        guest = self.Guest.with_user(self.reception).create({
            'name': 'Luis Rojas', 'phone': '70011122', 'email': 'luis.rojas@example.com',
            'membership_id': self.member.id}).sudo()
        lead = guest.lead_id
        self.assertTrue(lead, 'El invitado debe quedar como prospecto.')
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id, self._stage('visit'))
        self.assertEqual(lead.type, 'opportunity')
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_member_guest'))
        self.assertEqual(lead.referred_by_partner_id, self.partner)
        self.assertEqual(lead.partner_id, guest.partner_id)
        self.assertEqual(lead.spa_phone_key, '59170011122')
        self.assertEqual(lead.activity_ids.date_deadline, guest.date + timedelta(days=1))
        welcome = self.env['spa.message'].search([('res_model', '=', 'spa.guest'), ('res_id', '=', guest.id)])
        self.assertEqual(welcome.template_id.code, 'guest_welcome')
        self.assertIn(self.partner.name, welcome.body)

        # Mismo celular con otro formato y otro anfitrión: mismo prospecto, conserva el primer referido.
        host2 = self._partner('Carlos Mendoza', '+59170099988')
        member2 = self._membership(self.plan_basic, partner=host2)
        guest2 = self.Guest.create({'name': 'Luis R.', 'phone': '+591 700-11122', 'membership_id': member2.id})
        self.assertEqual(guest2.lead_id, lead)
        self.assertEqual(self.Lead.search_count([('spa_phone_key', '=', '59170011122')]), 1)
        self.assertEqual(lead.referred_by_partner_id, self.partner)
        self.assertEqual(lead.spa_guest_count, 2)

        # Mismo correo con otro celular: mismo prospecto.
        guest3 = self.Guest.create({'name': 'Luis', 'phone': '79999999', 'email': 'LUIS.ROJAS@example.com',
                                    'membership_id': member2.id})
        self.assertEqual(guest3.lead_id, lead)

    def test_guest_member_or_without_contact_is_not_a_lead(self):
        carla = self._partner('Carla Suárez', '70022233')
        self._membership(self.plan_basic, partner=carla)
        guest = self.Guest.create({'name': 'Carla', 'phone': '70022233', 'membership_id': self.member.id})
        self.assertEqual(guest.partner_id, carla)
        self.assertFalse(guest.lead_id)
        self.assertFalse(self.Lead.search([('partner_id', '=', carla.id), ('team_id', '=', self.team_acq.id)]))
        anonymous = self.Guest.create({'name': 'Invitado 1 de Ana', 'membership_id': self.member.id})
        self.assertFalse(anonymous.lead_id)

    def test_web_lead_goes_to_acquisition(self):
        lead = self.Lead.create({'name': 'Consulta desde la web', 'contact_name': 'Juan Pérez',
                                 'phone': '70044455', 'source_id': self.env.ref('spa_crm.utm_source_web').id})
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id, self._stage('interested'))
        # Un prospecto de captación no cambia de embudo al reasignar el responsable.
        lead.user_id = self.manager
        self.assertEqual(lead.team_id, self.team_acq)

    # ------------------------------------------------------------------
    # Pases de cortesía
    # ------------------------------------------------------------------
    def test_courtesy_issue_creates_lead_and_message(self):
        courtesy = self._pass(reason='Sorteo Instagram')
        self.assertEqual(courtesy.state, 'issued')
        self.assertTrue(courtesy.name.startswith('CORT/'))
        self.assertEqual(len(courtesy.token), 10)
        self.assertEqual(courtesy.issued_by_id, self.reception)
        self.assertEqual(courtesy.valid_to, self.today + timedelta(days=15))
        self.assertEqual(courtesy.partner_id.phone, '71234567')
        lead = courtesy.lead_id
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id, self._stage('visit'))
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_courtesy'))
        self.assertEqual(lead.courtesy_pass_ids, courtesy)
        message = courtesy.spa_message_id
        self.assertEqual(message.template_id.code, 'courtesy_pass')
        self.assertEqual(message.phone, '59171234567')
        self.assertIn(courtesy.token, message.body)
        self.assertIn(self.sauna.name, message.body)
        # «Enviar por WhatsApp» abre el mensaje pendiente; si ya se envió, genera uno nuevo.
        action = courtesy.with_user(self.reception).action_send_whatsapp()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(message.state, 'sent')
        courtesy.with_user(self.reception).action_send_whatsapp()
        self.assertNotEqual(courtesy.spa_message_id, message)
        with self.assertRaisesRegex(UserError, 'celular o el correo'):
            self._pass(phone=False)

        # Un interesado que recibe cortesía avanza de etapa (no se duplica).
        interested = self.Lead.create({'name': 'Consulta Instagram', 'contact_name': 'Rosa', 'phone': '72223334',
                                       'source_id': self.env.ref('spa_crm.utm_source_instagram').id})
        self.assertEqual(interested.stage_id, self._stage('interested'))
        courtesy2 = self._pass(guest_name='Rosa', phone='+591 72223334')
        self.assertEqual(courtesy2.lead_id, interested)
        self.assertEqual(interested.stage_id, self._stage('visit'))
        self.assertEqual(interested.source_id, self.env.ref('spa_crm.utm_source_instagram'))

    def test_courtesy_from_lead_by_marketing(self):
        marketing = new_test_user(self.env, login='spa_crm_marketing', groups='spa_base.group_spa_marketing')
        lead = self.Lead.with_user(marketing).create({
            'name': 'Consulta por WhatsApp', 'contact_name': 'Elena Rocha', 'phone': '75556667',
            'source_id': self.env.ref('spa_crm.utm_source_whatsapp').id})
        self.assertEqual(lead.team_id, self.team_acq)
        context = lead.action_spa_issue_courtesy()['context']
        courtesy = self.Pass.with_user(marketing).with_context(**context).create(
            {'service_ids': [(6, 0, self.sauna.ids)]})
        self.assertEqual(courtesy.guest_name, 'Elena Rocha')
        self.assertEqual(courtesy.lead_id, lead)
        self.assertEqual(courtesy.issued_by_id, marketing)
        self.assertEqual(lead.stage_id, self._stage('visit'))
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_whatsapp'))
        self.assertEqual(lead.courtesy_pass_count, 1)

    def test_courtesy_redeem(self):
        courtesy = self._pass(visits=2)
        # Lector de QR de recepción: acepta el código del pase.
        log = self.Log.with_user(self.reception).do_check_in(self.sauna_space, token=courtesy.token.lower())
        self.assertEqual(log.courtesy_pass_id, courtesy)
        self.assertEqual(log.courtesy_ref, courtesy.name)
        self.assertEqual(log.method, 'qr')
        self.assertEqual(log.partner_id, courtesy.partner_id)
        self.assertEqual(courtesy.visits_left, 1)
        self.assertEqual(courtesy.state, 'issued')
        self.assertEqual(self.sauna_space.occupancy, 1)
        with self.assertRaisesRegex(UserError, 'ya está dentro'):
            courtesy._redeem(self.sauna_space)
        log.action_check_out()

        wizard = self.env['spa.courtesy.redeem.wizard'].with_user(self.reception).create({
            'pass_id': courtesy.id, 'space_id': self.sauna_space.id})
        wizard.action_redeem()
        self.assertEqual(courtesy.visits_left, 0)
        self.assertEqual(courtesy.state, 'redeemed')
        self.assertEqual(len(courtesy.access_log_ids), 2)
        self.assertTrue(courtesy.lead_id.activity_ids)
        courtesy.access_log_ids.action_check_out()
        with self.assertRaisesRegex(UserError, 'ya se usó'):
            courtesy._redeem(self.sauna_space)
        with self.assertRaisesRegex(UserError, 'ya se usó'):
            courtesy.action_cancel()

    def test_courtesy_redeem_rejections(self):
        # Servicio no incluido
        massage_pass = self._pass(service_ids=[(6, 0, self.massage.ids)], phone='73330001')
        with self.assertRaisesRegex(UserError, 'no incluye'):
            massage_pass._redeem(self.sauna_space)
        # Vencido
        old_pass = self._pass(phone='73330002', valid_from=self.today - timedelta(days=10),
                              valid_to=self.today - timedelta(days=1))
        with self.assertRaisesRegex(UserError, 'venció'):
            old_pass._redeem(self.sauna_space)
        self.Pass._cron_expire_passes()
        self.assertEqual(old_pass.state, 'expired')
        self.assertEqual(massage_pass.state, 'issued')
        # Aún no vigente
        future_pass = self._pass(phone='73330003', valid_from=self.today + timedelta(days=2),
                                 valid_to=self.today + timedelta(days=5))
        with self.assertRaisesRegex(UserError, 'válido desde'):
            future_pass._redeem(self.sauna_space)
        # Aforo completo
        self.sauna_space.capacity = 1
        member_log = self.Log.do_check_in(self.sauna_space, token=self.member.qr_token)
        ok_pass = self._pass(phone='73330004')
        with self.assertRaisesRegex(UserError, 'lleno'):
            ok_pass._redeem(self.sauna_space)
        member_log.action_check_out()
        self.assertTrue(ok_pass._redeem(self.sauna_space))
        # Anulado
        cancelled = self._pass(phone='73330005')
        cancelled.action_cancel()
        with self.assertRaisesRegex(UserError, 'anulado'):
            cancelled._redeem(self.sauna_space)

    def test_courtesy_monthly_limit(self):
        self.icp.set_param('spa_crm.courtesy_monthly_limit', '2')
        first = self._pass(phone='74440001')
        self._pass(phone='74440002')
        with self.assertRaisesRegex(UserError, 'límite'):
            self._pass(phone='74440003')
        # Un pase anulado no cuenta.
        first.with_user(self.reception).action_cancel()
        self._pass(phone='74440003')
        # Los gerentes no tienen límite.
        for index in range(3):
            self._pass(user=self.manager, phone=f'7444010{index}')

    # ------------------------------------------------------------------
    # Captación ganada
    # ------------------------------------------------------------------
    def test_activation_wins_lead(self):
        guest = self.Guest.create({'name': 'Pedro Gutiérrez', 'phone': '70033344', 'membership_id': self.member.id})
        lead = guest.lead_id
        self.assertEqual(lead.won_status, 'pending')
        new_member = self._membership(self.plan_basic, partner=guest.partner_id)
        self.assertEqual(lead.stage_id, self._stage('member'))
        self.assertEqual(lead.won_status, 'won')
        self.assertEqual(lead.spa_membership_id, new_member)
        self.assertEqual(lead.expected_revenue, new_member.period_id.price)
        self.assertEqual(lead.spa_conversion_rate, 100.0)
        # Ya es socio: un nuevo registro como invitado no crea otro prospecto.
        guest2 = self.Guest.create({'name': 'Pedro', 'phone': '70033344', 'membership_id': self.member.id})
        self.assertFalse(guest2.lead_id)

    # ------------------------------------------------------------------
    # Retención
    # ------------------------------------------------------------------
    def test_retention_grace_then_recovered(self):
        client = self._partner('Mario Flores', '70055566')
        membership = self._membership(self.plan_basic, partner=client)
        membership.write({'date_end': self.today - timedelta(days=2), 'state': 'grace'})
        self.Membership._cron_spa_retention()
        leads = self._retention_leads(membership)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads.stage_id, self._stage('at_risk'))
        self.assertEqual(leads.spa_risk_reason, 'grace')
        self.assertEqual(leads.spa_risk_date_end, membership.date_end)
        self.assertEqual(len(leads.activity_ids), 1)
        self.assertEqual(leads.activity_ids.user_id, self.team_ret.user_id)
        # Sin duplicados al volver a correr (y sube de gravedad sin duplicar la actividad).
        membership.state = 'suspended'
        self.Membership._cron_spa_retention()
        self.assertEqual(self._retention_leads(membership), leads)
        self.assertEqual(leads.spa_risk_reason, 'suspended')
        self.assertEqual(len(leads.activity_ids), 1)
        # Renovó: recuperado.
        membership.action_activate()
        self.assertEqual(leads.stage_id, self._stage('recovered'))
        self.assertEqual(leads.won_status, 'won')
        self.Membership._cron_spa_retention()
        self.assertEqual(len(self._retention_leads(membership)), 1)

    def test_retention_expired_moves_to_ex_member(self):
        client = self._partner('Lucía Paz', '70066677')
        membership = self._membership(self.plan_basic, partner=client)
        membership.write({'date_end': self.today - timedelta(days=40), 'state': 'suspended'})
        self.Membership._cron_spa_retention()
        lead = self._retention_leads(membership)
        self.assertEqual(lead.stage_id, self._stage('at_risk'))
        membership.state = 'expired'
        self.Membership._cron_spa_retention()
        self.assertEqual(self._retention_leads(membership), lead)
        self.assertEqual(lead.stage_id, self._stage('ex_member'))
        self.assertEqual(lead.spa_risk_reason, 'expired')
        self.assertEqual(lead.won_status, 'pending')
        # El ex-socio viene como invitado: se anota en su oportunidad de retención (sin prospecto nuevo).
        guest = self.Guest.create({'name': 'Lucía', 'phone': '70066677', 'membership_id': self.member.id})
        self.assertEqual(guest.partner_id, client)
        self.assertEqual(guest.lead_id, lead)
        self.assertFalse(self.Lead.search([('partner_id', '=', client.id), ('team_id', '=', self.team_acq.id)]))
        # El ex-socio vuelve con una membresía nueva: recuperado.
        self._membership(self.plan_premium, partner=client)
        self.assertEqual(lead.stage_id, self._stage('recovered'))

        # Vencida sin oportunidad previa: va directo a «Ex-socio», una sola vez.
        other = self._membership(self.plan_basic, partner=self._partner('Raúl Vaca', '70077788'))
        other.write({'date_end': self.today - timedelta(days=100), 'state': 'expired'})
        self.Membership._cron_spa_retention()
        self.Membership._cron_spa_retention()
        ex_lead = self._retention_leads(other)
        self.assertEqual(len(ex_lead), 1)
        self.assertEqual(ex_lead.stage_id, self._stage('ex_member'))

    def test_retention_low_usage_and_expiring(self):
        self.icp.set_param('spa_crm.retention_low_usage_pct', '50')
        self.icp.set_param('spa_crm.retention_low_usage_day', '1')
        idle = self._membership(self.plan_basic, partner=self._partner('Socio sin uso', '70088801'))
        busy = self._membership(self.plan_basic, partner=self._partner('Socio frecuente', '70088802'))
        now = self._dt(self.today, 10.0)
        for _index in range(4):  # 4 de 8 sesiones de sauna = 50 %
            busy._spa_consume(self.sauna, now, 'checkin')
        self.Membership._cron_spa_retention()
        self.assertEqual(self._retention_leads(idle).spa_risk_reason, 'low_usage')
        self.assertFalse(self._retention_leads(busy))

        self.icp.set_param('spa_crm.retention_low_usage_pct', '0')
        self.icp.set_param('spa_crm.retention_expiry_days', '7')
        expiring = self._membership(self.plan_basic, partner=self._partner('Socio por vencer', '70088803'))
        expiring.date_end = self.today + timedelta(days=2)
        invoiced = self._membership(self.plan_basic, partner=self._partner('Socio con factura', '70088804'))
        invoiced.date_end = self.today + timedelta(days=2)
        invoiced.action_create_invoice()
        self.Membership._cron_spa_retention()
        self.assertEqual(self._retention_leads(expiring).spa_risk_reason, 'expiring')
        self.assertFalse(self._retention_leads(invoiced))
