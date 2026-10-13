# Part of ERP Servicios Spa. License LGPL-3.
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import freeze_time, new_test_user, tagged

from odoo.addons.spa_membership.tests.common import SpaCommon

NOW = datetime(2027, 3, 2, 15, 0, 0)  # martes 2 de marzo de 2027, 11:00 en La Paz


@tagged('post_install', '-at_install', 'spa')
@freeze_time(NOW)
class TestSpaCrmFixes(SpaCommon):
    """Permisos de recepción en el CRM, fuente por defecto del sitio web, cortesías a socios,
    horario y aforo del canje, y altas web sin pagar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env['crm.lead']
        cls.team_acq = cls.env.ref('spa_crm.team_acquisition')
        cls.sauna_space = cls.env.ref('spa_base.space_sauna')
        cls.pool_space = cls.env.ref('spa_base.space_pool')
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('spa_crm.followup_days', '1')
        icp.set_param('spa_crm.courtesy_monthly_limit', '0')
        icp.set_param('spa_crm.signup_lead_reception', '')
        cls.reception = new_test_user(cls.env, login='spa_crm_fix_reception', groups='spa_base.group_spa_reception')
        cls.marketing = new_test_user(cls.env, login='spa_crm_fix_marketing', groups='spa_base.group_spa_marketing')

    def _stage(self, code):
        return self.env.ref(f'spa_crm.stage_{code}')

    def _web_read_form(self, user, record):
        self.env.invalidate_all()
        model = record.with_user(user)
        fields_info = model.get_views([(False, 'form')])['models'][record._name]['fields']
        spec = {name: ({'fields': {'display_name': {}}} if info['type'] in ('many2one', 'one2many', 'many2many')
                       else {}) for name, info in fields_info.items()}
        return model.web_read(spec)[0]

    # ------------------------------------------------------------------
    # Recepción en el CRM y prospectos del sitio web
    # ------------------------------------------------------------------
    def test_reception_registers_walk_in_lead(self):
        lead = self.Lead.with_user(self.reception).create({
            'name': 'Pasó por recepción: Tomás', 'phone': '+591 71230000',
            'source_id': self.env.ref('spa_crm.utm_source_reception').id})
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id, self._stage('interested'))
        self.assertTrue(self.reception.has_group('sales_team.group_sale_salesman'), 'docs/10: Recepción = CRM usuario')
        self.assertTrue(self.marketing.has_group('sales_team.group_sale_manager'), 'docs/10: Marketing = CRM gerente')
        # Recepción abre un pase de cortesía emitido por marketing (con su prospecto, de otro responsable).
        courtesy = self.env['spa.courtesy.pass'].with_user(self.marketing).create({
            'guest_name': 'Sofía Vargas', 'phone': '71234567', 'service_ids': [Command.set(self.sauna.ids)]})
        self.assertTrue(courtesy.sudo().lead_id)
        values = self._web_read_form(self.reception, courtesy)
        self.assertEqual(values['guest_name'], 'Sofía Vargas')
        guest_values = self._web_read_form(self.marketing, courtesy)
        self.assertEqual(guest_values['lead_id']['id'], courtesy.sudo().lead_id.id)

    def test_default_source_routes_to_acquisition(self):
        instagram = self.env.ref('spa_crm.utm_source_instagram')
        # Fuente por defecto (p. ej. la cookie UTM del visitante, vía utm.mixin.default_get).
        lead = self.Lead.with_context(default_source_id=instagram.id).create({'name': 'Desde un anuncio'})
        self.assertEqual(lead.source_id, instagram)
        self.assertEqual(lead.team_id, self.team_acq)
        # Formulario del sitio sin fuente y con equipo vacío: Captación.
        website_medium = self.env.ref('utm.utm_medium_website')
        lead = self.Lead.create({'name': 'Contáctenos', 'team_id': False, 'medium_id': website_medium.id})
        self.assertEqual(lead.team_id, self.team_acq)
        self.assertEqual(lead.stage_id, self._stage('interested'))
        if 'website' in self.env and 'crm_default_team_id' in self.env['website']._fields:
            website = self.env['website'].search([], limit=1)
            website.crm_default_team_id = False
            self.Lead._spa_setup_website_team()
            self.assertEqual(website.crm_default_team_id, self.team_acq)

    # ------------------------------------------------------------------
    # Cortesías
    # ------------------------------------------------------------------
    def test_courtesy_for_member_matches_phone_and_skips_lead(self):
        ana = self.env['res.partner'].create({'name': 'Ana Rojas', 'phone': '+591 70000101'})
        self._membership(self.plan_premium, partner=ana)
        courtesy = self.env['spa.courtesy.pass'].with_user(self.marketing).create({
            'guest_name': 'Ana Rojas', 'phone': '70000101', 'service_ids': [Command.set(self.sauna.ids)],
            'reason': 'Evento aniversario'}).sudo()
        self.assertEqual(courtesy.partner_id, ana)
        self.assertFalse(courtesy.lead_id)
        self.assertFalse(self.Lead.search([('partner_id', '=', ana.id), ('team_id', '=', self.team_acq.id),
                                           ('won_status', '=', 'pending')]))
        self.assertFalse(self.Lead._spa_upsert_acquisition(ana, self.env.company, stage_code='visit'))

    def test_courtesy_redeem_respects_hours_and_walk_in_capacity(self):
        courtesy = self.env['spa.courtesy.pass'].create({
            'guest_name': 'Raúl Pinto', 'phone': '71234501', 'visits': 3,
            'service_ids': [Command.set((self.sauna | self.pool).ids)]})
        self.sauna_space.write({'closure_ids': [Command.create({
            'date_from': self.today, 'date_to': self.today, 'reason': 'Mantenimiento'})]})
        with self.assertRaisesRegex(UserError, 'cerrado'):
            courtesy._redeem(self.sauna_space)
        with freeze_time(NOW - timedelta(hours=5)), self.assertRaisesRegex(UserError, 'cerrado'):  # 06:00
            courtesy._redeem(self.pool_space)
        # Piscina (por franja) con aforo 2: el canje ocupa un lugar en las reservas siguientes.
        self.pool_space.capacity = 2
        log = courtesy._redeem(self.pool_space)
        self.assertEqual(log.service_id, self.pool)
        self.assertEqual(self.pool_space._seats_taken(NOW + timedelta(minutes=30), NOW + timedelta(hours=2)), 1)
        member = self._membership(self.plan_premium)
        booking = self.env['spa.booking'].create({
            'partner_id': self.partner.id, 'membership_id': member.id, 'payment_mode': 'membership',
            'service_id': self.pool.id, 'start': NOW + timedelta(minutes=30)})
        booking.action_confirm()
        other = self.env['spa.courtesy.pass'].create({
            'guest_name': 'Rita Pinto', 'phone': '71234502', 'service_ids': [Command.set(self.pool.ids)]})
        with self.assertRaisesRegex(UserError, 'lleno'):
            other._redeem(self.pool_space)

    # ------------------------------------------------------------------
    # Altas web sin pagar
    # ------------------------------------------------------------------
    def test_web_signup_moves_lead_to_proposal(self):
        portal = new_test_user(self.env, login='spa_crm_fix_portal', groups='base.group_portal',
                               name='Lucía Web', email='lucia.web@example.com', phone='+591 71112233')
        partner = portal.partner_id
        period = self.plan_premium.period_ids.filtered(lambda p: p.months == 1)
        # Lo que hace la web del socio: crea la membresía con sudo() conservando el usuario del portal.
        membership = self.env['spa.membership'].with_user(portal).sudo().create({
            'partner_id': partner.id, 'plan_id': self.plan_premium.id, 'period_id': period.id})
        lead = self.Lead.search([('partner_id', '=', partner.id), ('team_id', '=', self.team_acq.id)])
        self.assertEqual(len(lead), 1)
        self.assertRecordValues(lead, [{
            'stage_id': self._stage('proposal').id, 'source_id': self.env.ref('spa_crm.utm_source_web').id,
            'spa_membership_id': membership.id, 'expected_revenue': 890.0, 'won_status': 'pending'}])
        self.assertEqual(lead.activity_ids.date_deadline, self.today + timedelta(days=1))
        # Paga y se activa: el prospecto se gana.
        membership.action_activate()
        self.assertEqual(lead.won_status, 'won')
        self.assertEqual(lead.stage_id, self._stage('member'))

    def test_signup_advances_existing_lead_and_internal_drafts(self):
        interested = self.Lead.create({
            'name': 'Consulta por Instagram', 'contact_name': 'Marcos', 'phone': '72220001',
            'source_id': self.env.ref('spa_crm.utm_source_instagram').id})
        marcos = self.env['res.partner'].create({'name': 'Marcos', 'phone': '+591 72220001'})
        period = self.plan_basic.period_ids.filtered(lambda p: p.months == 1)
        Membership = self.env['spa.membership'].with_user(self.reception)
        Membership.create({'partner_id': marcos.id, 'plan_id': self.plan_basic.id, 'period_id': period.id})
        self.assertEqual(interested.stage_id, self._stage('proposal'), 'Recepción: avanza el prospecto existente')
        self.assertEqual(interested.source_id, self.env.ref('spa_crm.utm_source_instagram'))
        # Alta de recepción sin prospecto previo: no crea uno (salvo que se active el ajuste).
        nuevo = self.env['res.partner'].create({'name': 'Nuevo en recepción', 'phone': '72220002'})
        Membership.create({'partner_id': nuevo.id, 'plan_id': self.plan_basic.id, 'period_id': period.id})
        self.assertFalse(self.Lead.search([('partner_id', '=', nuevo.id)]))
        self.env['ir.config_parameter'].sudo().set_param('spa_crm.signup_lead_reception', 'True')
        otro = self.env['res.partner'].create({'name': 'Otro en recepción', 'phone': '72220003'})
        Membership.create({'partner_id': otro.id, 'plan_id': self.plan_basic.id, 'period_id': period.id})
        lead = self.Lead.search([('partner_id', '=', otro.id)])
        self.assertEqual(lead.stage_id, self._stage('proposal'))
        self.assertEqual(lead.source_id, self.env.ref('spa_crm.utm_source_reception'))
        # Contexto explícito de la web; y un socio vigente que agrega otra membresía no es prospecto.
        member = self._membership(self.plan_basic)
        self.env['spa.membership'].with_context(spa_portal_signup=True).create({
            'partner_id': member.partner_id.id, 'plan_id': self.plan_premium.id,
            'period_id': self.plan_premium.period_ids[:1].id})
        self.assertFalse(self.Lead.search([('partner_id', '=', member.partner_id.id),
                                           ('team_id', '=', self.team_acq.id), ('won_status', '=', 'pending')]))
