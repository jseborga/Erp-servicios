# Part of ERP Servicios Spa. License LGPL-3.
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import format_amount

from .crm_lead import RISK_LEVEL

ACCESS_STATES = ('active', 'grace')
LIVE_STATES = ('active', 'grace', 'suspended')


class SpaMembership(models.Model):
    _inherit = 'spa.membership'

    spa_lead_ids = fields.One2many('crm.lead', 'spa_membership_id', string='Oportunidades',
                                   groups='sales_team.group_sale_salesman')
    spa_lead_count = fields.Integer('Nº de oportunidades', compute='_compute_spa_lead_count',
                                    groups='sales_team.group_sale_salesman')

    def _compute_spa_lead_count(self):
        for membership in self:
            membership.spa_lead_count = len(membership.spa_lead_ids)

    def action_view_spa_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Oportunidades'),
            'res_model': 'crm.lead',
            'view_mode': 'list,form',
            'domain': [('spa_membership_id', '=', self.id)],
            'context': {'active_test': False, 'create': False},
        }

    # ------------------------------------------------------------------
    # Alta sin pagar → prospecto en «Propuesta»
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        memberships = super().create(vals_list)
        memberships._spa_crm_after_signup()
        return memberships

    @api.model
    def _spa_crm_signup_origin(self):
        """'web' si el alta la hace el propio socio en la web, 'internal' si la registra el personal.

        Señal: la clave de contexto ``spa_portal_signup`` (la puede pasar el controlador de la
        web) o, si no viene, el usuario que crea la membresía no es interno (socio del portal;
        la web crea con ``sudo()`` pero conserva el usuario). El personal (recepción, caja) y
        los procesos automáticos son usuarios internos.
        """
        if self.env.context.get('spa_portal_signup') or not self.env.user._is_internal():
            return 'web'
        return 'internal'

    def _spa_crm_after_signup(self):
        """Membresía en borrador de alguien que aún no es socio: su prospecto pasa a «Propuesta».

        * Alta web (abandonada hasta que pague): crea o avanza el prospecto de Captación (fuente
          «Web» si es nuevo), lo vincula a la membresía y programa el seguimiento.
        * Alta del personal: solo avanza un prospecto abierto (lo habitual es que pague en el
          momento); con el ajuste «Prospecto también para altas de recepción» también lo crea
          (fuente «Recepción»).
        Al activarse la membresía el prospecto se gana (``_spa_crm_after_activation``).
        """
        Lead = self.env['crm.lead'].sudo()
        origin = self._spa_crm_signup_origin()
        params = self.env['ir.config_parameter'].sudo()
        create_internal = str(params.get_param('spa_crm.signup_lead_reception') or '').lower() in ('1', 'true')
        try:
            followup_days = int(params.get_param('spa_crm.followup_days', 0) or 0)
        except (TypeError, ValueError):
            followup_days = 0
        today = self.env['spa.tools'].local_today()
        for membership in self.sudo().filtered(lambda m: m.state == 'draft'):
            partner = membership.partner_id
            if partner._spa_has_live_membership(exclude=membership):
                continue
            team = Lead._spa_team('acquisition', membership.company_id)
            existing = Lead._spa_find_open_leads(team, partner)
            if origin == 'internal' and not existing and not create_internal:
                continue
            if origin == 'web':
                source = Lead._spa_source('web')
                name = self.env._('Alta web: %(partner)s (%(plan)s)', partner=partner.name,
                                  plan=membership.plan_id.name)
                how = self.env._('alta web')
            else:
                source = Lead._spa_source('reception')
                name = self.env._('Alta: %(partner)s (%(plan)s)', partner=partner.name, plan=membership.plan_id.name)
                how = self.env._('alta en recepción')
            lead = Lead._spa_upsert_acquisition(
                partner, membership.company_id, source=source, stage_code='proposal', lead=existing or None,
                name=name, note=self.env._(
                    'Inició el %(how)s del plan %(plan)s (%(period)s, %(price)s): pendiente de pago.',
                    how=how, plan=membership.plan_id.name, period=membership.period_id.name,
                    price=format_amount(self.env, membership.price, membership.currency_id)))
            if not lead or lead.spa_pipeline != 'acquisition':
                continue
            vals = {}
            if not lead.spa_membership_id:
                vals['spa_membership_id'] = membership.id
            if not lead.expected_revenue and membership.period_id.price:
                vals['expected_revenue'] = membership.period_id.price
            if vals:
                lead.write(vals)
            if origin == 'web' and followup_days:
                lead._spa_schedule_activity(self.env._('Alta web sin pagar: ayudar a completar el pago'),
                                            deadline=today + timedelta(days=followup_days))
        return True

    # ------------------------------------------------------------------
    # Captación ganada y socio recuperado
    # ------------------------------------------------------------------
    def action_activate(self, start_date=None):
        res = super().action_activate(start_date=start_date)
        self._spa_crm_after_activation()
        return res

    def _spa_crm_after_activation(self):
        Lead = self.env['crm.lead'].sudo()
        for membership in self.sudo().filtered(lambda m: m.state == 'active'):
            partner = membership.partner_id
            team = Lead._spa_team('acquisition', membership.company_id)
            if team:
                leads = Lead._spa_find_open_leads(team, partner, limit=None)
                leads._spa_win('member', membership)
            Lead.search([
                ('spa_pipeline', '=', 'retention'), ('won_status', '=', 'pending'),
                ('partner_id', '=', partner.id),
            ])._spa_check_recovered()
        return True

    # ------------------------------------------------------------------
    # Retención
    # ------------------------------------------------------------------
    @api.model
    def _spa_retention_params(self):
        params = self.env['ir.config_parameter'].sudo()

        def as_int(key, default=0):
            try:
                return int(params.get_param(key, default) or 0)
            except (TypeError, ValueError):
                return default

        return {
            'low_usage_pct': as_int('spa_crm.retention_low_usage_pct'),
            'low_usage_day': as_int('spa_crm.retention_low_usage_day') or 15,
            'expiry_days': as_int('spa_crm.retention_expiry_days'),
        }

    def _spa_usage_rate(self, day):
        """Porcentaje usado del saldo del mes (servicios con cupo).

        Si el plan solo tiene servicios ilimitados devuelve 100 cuando hubo algún uso y 0 si no.
        ``None`` si el plan no tiene servicios.
        """
        self.ensure_one()
        membership = self.sudo()
        membership._ensure_entitlements(day)
        start, _end = self.env['spa.tools'].month_bounds(day)
        entitlements = membership.entitlement_ids.filtered(lambda e: e.period_start == start)
        if not entitlements:
            return None
        limited = entitlements.filtered(lambda e: not e.unlimited)
        available = sum(e.granted + e.carried_in for e in limited)
        if available > 0:
            return 100.0 * sum(limited.mapped('used')) / available
        return 100.0 if sum(entitlements.mapped('used')) > 0 else 0.0

    def _spa_retention_reason(self, today, params):
        """Motivo por el que el socio está en riesgo, o False."""
        self.ensure_one()
        if self.state == 'grace':
            return 'grace'
        if self.state == 'suspended':
            return 'suspended'
        if self.state != 'active':
            return False
        days = params['expiry_days']
        if days and self.date_end and today <= self.date_end <= today + timedelta(days=days) \
                and not self.sudo()._open_period_invoice():
            return 'expiring'
        pct, from_day = params['low_usage_pct'], params['low_usage_day']
        if pct and today.day >= from_day and self.date_start \
                and self.date_start <= today - timedelta(days=from_day - 1):
            rate = self._spa_usage_rate(today)
            if rate is not None and rate < pct:
                return 'low_usage'
        return False

    def _spa_has_other_membership(self):
        """True si el socio tiene otra membresía con acceso que vence después (cambió de plan)."""
        self.ensure_one()
        return bool(self.partner_id.spa_membership_ids.filtered(
            lambda m: m != self and m.state in ACCESS_STATES
            and (not self.date_end or (m.date_end and m.date_end > self.date_end))))

    def _spa_open_retention(self, reason):
        """Crea (una sola vez) la oportunidad «En riesgo» de la membresía, o la actualiza."""
        self.ensure_one()
        Lead = self.env['crm.lead'].sudo()
        team = Lead._spa_team('retention', self.company_id)
        if not team:
            return Lead.browse()
        reason_label = dict(Lead._fields['spa_risk_reason'].selection)[reason]
        existing = Lead.with_context(active_test=False).search([
            ('spa_membership_id', '=', self.id), ('team_id', '=', team.id),
            '|', ('won_status', '=', 'pending'), ('spa_risk_date_end', '=', self.date_end),
        ], order='id desc', limit=1)
        if existing:
            if existing.active and existing.won_status == 'pending' \
                    and RISK_LEVEL.get(reason, 0) > RISK_LEVEL.get(existing.spa_risk_reason, -1):
                existing.write({'spa_risk_reason': reason})
                existing.message_post(body=self.env._('Nuevo motivo de riesgo: %s.', reason_label))
            return existing
        stage = Lead._spa_stage(team, 'ex_member' if reason == 'expired' else 'at_risk')
        vals = {
            'name': self.env._('Retención: %(partner)s (%(plan)s)', partner=self.partner_id.name,
                               plan=self.plan_id.name),
            'type': 'opportunity',
            'team_id': team.id,
            'user_id': team.user_id.id or False,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'spa_membership_id': self.id,
            'spa_risk_reason': reason,
            'spa_risk_date_end': self.date_end,
            'expected_revenue': self.period_id.price,
        }
        if stage:
            vals['stage_id'] = stage.id
        lead = Lead.create(vals)
        lead.message_post(body=self.env._('Socio en riesgo: %(reason)s. Membresía %(name)s, vence el %(date)s.',
                                          reason=reason_label, name=self.name,
                                          date=self.date_end.strftime('%d/%m/%Y') if self.date_end else '-'))
        if reason != 'expired':
            lead._spa_schedule_activity(self.env._('Contactar socio en riesgo: %s', reason_label))
        return lead

    @api.model
    def _cron_spa_retention(self):
        """Detecta socios en riesgo, recuperados y ex-socios (embudo de Retención)."""
        Lead = self.env['crm.lead'].sudo()
        Membership = self.sudo()
        today = self.env['spa.tools'].local_today()
        params = self._spa_retention_params()

        # 1. Renovaron: se ganan como «Recuperado».
        Lead.search([('spa_pipeline', '=', 'retention'), ('won_status', '=', 'pending')])._spa_check_recovered()

        # 2. Socios en riesgo (mora, suspensión, por vencer o con uso bajo).
        for membership in Membership.search([('state', 'in', LIVE_STATES)]):
            reason = membership._spa_retention_reason(today, params)
            if reason and not membership._spa_has_other_membership():
                membership._spa_open_retention(reason)

        # 3. Membresías vencidas: la oportunidad abierta pasa a «Ex-socio».
        for lead in Lead.search([('spa_pipeline', '=', 'retention'), ('won_status', '=', 'pending'),
                                 ('spa_membership_id.state', '=', 'expired')]):
            stage = Lead._spa_stage(lead.team_id, 'ex_member')
            if stage and lead.stage_id != stage:
                lead.write({'stage_id': stage.id, 'spa_risk_reason': 'expired'})
                lead.message_post(body=self.env._('La membresía venció sin renovarse: pasa a ex-socio.'))

        # 4. Vencidas que nunca tuvieron oportunidad de retención (una por socio).
        covered = Lead.with_context(active_test=False).search(
            [('spa_pipeline', '=', 'retention'), ('spa_membership_id', '!=', False)]).spa_membership_id
        open_partners = Lead.search([('spa_pipeline', '=', 'retention'), ('won_status', '=', 'pending')]).partner_id
        done = self.env['res.partner']
        for membership in Membership.search([('state', '=', 'expired'), ('id', 'not in', covered.ids)],
                                            order='date_end desc, id desc'):
            partner = membership.partner_id
            if partner in done or partner in open_partners \
                    or partner.spa_membership_ids.filtered(lambda m: m.state in LIVE_STATES):
                continue
            done |= partner
            membership._spa_open_retention('expired')
        return True
