# Part of ERP Servicios Spa. License LGPL-3.
import logging

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

# Ordenadas de menor a mayor gravedad.
RISK_REASONS = [
    ('low_usage', 'Uso bajo'),
    ('expiring', 'Próxima a vencer sin renovación'),
    ('grace', 'En gracia (mora)'),
    ('suspended', 'Suspendida por falta de pago'),
    ('expired', 'Vencida (ex-socio)'),
]
RISK_LEVEL = {code: index for index, (code, _label) in enumerate(RISK_REASONS)}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    spa_pipeline = fields.Selection(related='team_id.spa_pipeline', store=True, string='Embudo del spa')
    spa_phone_key = fields.Char('Celular normalizado', compute='_compute_spa_phone_key', store=True,
                                index='btree_not_null',
                                help='Celular solo con dígitos y código de país; se usa para evitar duplicados.')
    referred_by_partner_id = fields.Many2one('res.partner', string='Socio que refiere', index='btree_not_null',
                                             tracking=True)
    spa_membership_id = fields.Many2one('spa.membership', string='Membresía', index='btree_not_null',
                                        tracking=True, groups='spa_base.group_spa_reception')
    spa_member_state = fields.Selection(related='partner_id.spa_member_state', string='Estado de socio',
                                        groups='spa_base.group_spa_reception')
    spa_guest_ids = fields.One2many('spa.guest', 'lead_id', string='Visitas como invitado',
                                    groups='spa_base.group_spa_reception')
    spa_guest_count = fields.Integer('Nº de visitas como invitado', compute='_compute_spa_counts',
                                     groups='spa_base.group_spa_reception')
    courtesy_pass_ids = fields.One2many('spa.courtesy.pass', 'lead_id', string='Pases de cortesía',
                                        groups='spa_base.group_spa_reception')
    courtesy_pass_count = fields.Integer('Nº de pases de cortesía', compute='_compute_spa_counts',
                                         groups='spa_base.group_spa_reception')
    spa_risk_reason = fields.Selection(RISK_REASONS, string='Motivo de riesgo', tracking=True)
    spa_risk_date_end = fields.Date('Vencimiento evaluado',
                                    help='Vencimiento de la membresía cuando se detectó el riesgo. '
                                         'Si el socio renueva más allá de esta fecha, la oportunidad se gana.')
    spa_days_to_convert = fields.Float('Días hasta convertir', compute='_compute_spa_conversion', store=True,
                                       aggregator='avg', help='Días entre el alta del prospecto y su conversión.')
    spa_conversion_rate = fields.Float('Tasa de conversión (%)', compute='_compute_spa_conversion', store=True,
                                       aggregator='avg', help='100 si se ganó, 0 si no. Su promedio es la tasa de conversión.')

    @api.depends('phone')
    def _compute_spa_phone_key(self):
        Message = self.env['spa.message']
        for lead in self:
            lead.spa_phone_key = Message._normalize_phone(lead.phone) or False

    @api.depends('won_status', 'date_closed')
    def _compute_spa_conversion(self):
        for lead in self:
            won = lead.won_status == 'won'
            lead.spa_conversion_rate = 100.0 if won else 0.0
            if won and lead.date_closed and lead.create_date:
                lead.spa_days_to_convert = round((lead.date_closed - lead.create_date).total_seconds() / 86400.0, 1)
            else:
                lead.spa_days_to_convert = 0.0

    def _compute_spa_counts(self):
        for lead in self:
            lead.spa_guest_count = len(lead.spa_guest_ids)
            lead.courtesy_pass_count = len(lead.courtesy_pass_ids)

    @api.depends('user_id', 'type')
    def _compute_team_id(self):
        """Los prospectos de los embudos del spa no cambian de embudo al reasignar el responsable."""
        spa_leads = self.filtered(lambda lead: lead.team_id.spa_pipeline)
        return super(CrmLead, self - spa_leads)._compute_team_id()

    @api.model_create_multi
    def create(self, vals_list):
        """Un prospecto sin equipo va al embudo de su fuente; los del sitio web, a Captación.

        La fuente puede venir en los valores o por defecto (``utm.mixin.default_get``: cookie
        ``odoo_utm_source`` del visitante que llegó desde un anuncio). El formulario de contacto
        del sitio (website_crm) envía ``team_id`` vacío cuando el sitio no tiene equipo por
        defecto: también se trata como «sin equipo».
        """
        if not self.env.context.get('default_team_id'):
            Source = self.env['utm.source'].sudo()
            website_medium = self.env.ref('utm.utm_medium_website', raise_if_not_found=False)
            default_source = None
            for vals in vals_list:
                if vals.get('team_id'):
                    continue
                source_id = vals.get('source_id')
                if not source_id and 'source_id' not in vals:
                    if default_source is None:
                        default_source = self.default_get(['source_id']).get('source_id') or False
                    source_id = default_source
                team = Source.browse(source_id).spa_team_id if source_id else self.env['crm.team']
                if not (team and team.active) and website_medium and vals.get('medium_id') == website_medium.id:
                    company = self.env['res.company'].browse(vals.get('company_id')) if vals.get('company_id') \
                        else self.env.company
                    team = self._spa_team('acquisition', company)
                if team and team.active:
                    vals['team_id'] = team.id
        return super().create(vals_list)

    @api.model
    def _spa_setup_website_team(self):
        """Los formularios «Contáctenos» del sitio crean prospectos en Captación.

        Solo si website_crm está instalado (campo ``website.crm_default_team_id``) y el sitio no
        tiene ya un equipo elegido por el administrador. Se ejecuta al instalar/actualizar.
        """
        if 'website' not in self.env or 'crm_default_team_id' not in self.env['website']._fields:
            return False
        websites = self.env['website'].sudo().search([('crm_default_team_id', '=', False)])
        for website in websites:
            team = self._spa_team('acquisition', website.company_id)
            if team:
                website.crm_default_team_id = team
        return True

    # ------------------------------------------------------------------
    # Embudos y etapas del spa
    # ------------------------------------------------------------------
    @api.model
    def _spa_team(self, pipeline, company=None):
        """Equipo del embudo ``pipeline`` para ``company`` (o el compartido)."""
        company = company or self.env.company
        teams = self.env['crm.team'].sudo().search(
            [('spa_pipeline', '=', pipeline), ('company_id', 'in', [company.id, False])])
        return teams.filtered(lambda team: team.company_id == company)[:1] or teams[:1]

    @api.model
    def _spa_stage(self, team, code):
        if not team:
            return self.env['crm.stage']
        return self.env['crm.stage'].sudo().search(
            [('spa_stage_code', '=', code), '|', ('team_ids', '=', False), ('team_ids', 'in', team.ids)],
            order='sequence, id', limit=1)

    @api.model
    def _spa_source(self, code):
        """Fuente de los datos del módulo (``utm_source_<code>``) o vacía si se borró."""
        return self.env.ref(f'spa_crm.utm_source_{code}', raise_if_not_found=False) or self.env['utm.source']

    @api.model
    def _spa_find_open_leads(self, team, partner=None, phone=None, email=None, limit=1):
        """Prospectos abiertos del equipo que coinciden por contacto, celular normalizado o correo."""
        if not team:
            return self.browse()
        Message = self.env['spa.message']
        phones = {phone, partner.phone if partner else False}
        emails = {email, partner.email if partner else False}
        keys = {Message._normalize_phone(value) for value in phones if value} - {False}
        normalized = {email_normalize(value) for value in emails if value} - {False, None}
        conditions = []
        if partner:
            conditions.append(Domain('partner_id', '=', partner.id))
        if keys:
            conditions.append(Domain('spa_phone_key', 'in', list(keys)))
        if normalized:
            conditions.append(Domain('email_normalized', 'in', list(normalized)))
        if not conditions:
            return self.browse()
        domain = Domain.AND([
            Domain('team_id', '=', team.id),
            Domain('won_status', '=', 'pending'),
            Domain('active', '=', True),
            Domain.OR(conditions),
        ])
        return self.sudo().search(domain, order='create_date desc, id desc', limit=limit)

    @api.model
    def _spa_upsert_acquisition(self, partner, company, source=None, stage_code='visit', name=None,
                                referred_by=None, phone=None, email=None, note=None, lead=None):
        """Crea o actualiza el prospecto de captación de una persona y lo devuelve.

        Si ya tiene un prospecto abierto (mismo contacto, celular o correo) se reutiliza:
        solo avanza de etapa (nunca retrocede) y conserva la fuente original. Si es un ex-socio
        con una oportunidad de retención abierta, se anota allí y no se crea un prospecto nuevo.
        """
        Lead = self.sudo()
        if partner and partner._spa_has_live_membership():
            # Un socio vigente (aunque esté en gracia o suspendido) no es un prospecto de captación.
            return Lead.browse()
        if partner and not lead:
            retention = Lead.search([('spa_pipeline', '=', 'retention'), ('won_status', '=', 'pending'),
                                     ('partner_id', '=', partner.id)], limit=1)
            if retention:
                if note:
                    retention.message_post(body=note)
                return retention
        team = Lead._spa_team('acquisition', company)
        if not team:
            _logger.warning('spa_crm: no hay un equipo con embudo de captación; no se crea el prospecto.')
            return Lead.browse()
        stage = Lead._spa_stage(team, stage_code)
        lead = lead.sudo() if lead else Lead.browse()
        if lead and not (lead.active and lead.won_status == 'pending'):
            lead = Lead.browse()
        lead = lead or Lead._spa_find_open_leads(team, partner, phone, email)
        if lead:
            vals = {}
            if stage and lead.team_id == team and not lead.stage_id.is_won \
                    and lead.stage_id.sequence < stage.sequence:
                vals['stage_id'] = stage.id
            if referred_by and not lead.referred_by_partner_id:
                vals.update(referred_by_partner_id=referred_by.id, referred=referred_by.name)
            if partner and not lead.partner_id:
                vals['partner_id'] = partner.id
            if vals:
                lead.write(vals)
        else:
            vals = {
                'name': name or (partner.name if partner else False) or self.env._('Prospecto'),
                'type': 'opportunity',
                'team_id': team.id,
                'user_id': team.user_id.id or False,
                'company_id': company.id,
                'partner_id': partner.id if partner else False,
                'source_id': source.id if source else False,
                'referred_by_partner_id': referred_by.id if referred_by else False,
                'referred': referred_by.name if referred_by else False,
            }
            if stage:
                vals['stage_id'] = stage.id
            if not partner:
                vals.update(contact_name=name, phone=phone, email_from=email)
            else:
                if phone and not partner.phone:
                    vals['phone'] = phone
                if email and not partner.email:
                    vals['email_from'] = email
            lead = Lead.create(vals)
        if note:
            lead.message_post(body=note)
        return lead

    def _spa_win(self, stage_code, membership=None):
        """Marca ganados los prospectos en la etapa ganada del spa (``member`` o ``recovered``)."""
        for lead in self.sudo():
            vals = {}
            if membership:
                vals['spa_membership_id'] = membership.id
                if not lead.partner_id:
                    vals['partner_id'] = membership.partner_id.id
                if not lead.expected_revenue and membership.period_id.price:
                    vals['expected_revenue'] = membership.period_id.price
            stage = lead._spa_stage(lead.team_id, stage_code)
            if stage:
                vals['stage_id'] = stage.id
            lead.write(vals)
            if not stage or not stage.is_won:
                lead.action_set_won()
            if membership:
                lead.message_post(body=self.env._('Ganado: membresía %(name)s (%(plan)s) activa hasta el %(date)s.',
                                                  name=membership.name, plan=membership.plan_id.name,
                                                  date=membership.date_end.strftime('%d/%m/%Y')))
        return True

    def _spa_check_recovered(self):
        """Gana (Recuperado) las oportunidades de retención cuyo socio ya renovó."""
        for lead in self.sudo().filtered(lambda l: l.spa_pipeline == 'retention' and l.won_status == 'pending'
                                         and l.partner_id):
            renewed = lead.partner_id.spa_membership_ids.filtered(
                lambda m: m.state == 'active' and m.date_end
                and (not lead.spa_risk_date_end or m.date_end > lead.spa_risk_date_end))
            if renewed:
                lead._spa_win('recovered', renewed.sorted('date_end', reverse=True)[:1])
        return True

    @api.model
    def _spa_activity_type(self):
        value = self.env['ir.config_parameter'].sudo().get_param('spa_crm.activity_type_id')
        activity_type = self.env['mail.activity.type']
        if value and str(value).isdigit():
            activity_type = activity_type.browse(int(value)).exists()
        return activity_type or self.env.ref('mail.mail_activity_data_call', raise_if_not_found=False) \
            or self.env['mail.activity.type']

    def _spa_schedule_activity(self, summary, deadline=None, note=None):
        """Programa una actividad de seguimiento (sin duplicar una abierta con el mismo resumen)."""
        activity_type = self._spa_activity_type()
        deadline = deadline or self.env['spa.tools'].local_today()
        for lead in self.sudo():
            if lead.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            user = lead.user_id or lead.team_id.user_id or lead.team_id.member_ids[:1] or self.env.user
            lead.activity_schedule(activity_type_id=activity_type.id, date_deadline=deadline, summary=summary,
                                   note=note or '', user_id=user.id)
        return True

    # ------------------------------------------------------------------
    # Botones
    # ------------------------------------------------------------------
    def action_spa_view_courtesy_passes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Pases de cortesía'),
            'res_model': 'spa.courtesy.pass',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    def action_spa_view_guests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Visitas como invitado'),
            'res_model': 'spa.guest',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'create': False},
        }

    def action_spa_issue_courtesy(self):
        """Abre un pase de cortesía con los datos del prospecto."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Emitir pase de cortesía'),
            'res_model': 'spa.courtesy.pass',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_lead_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_guest_name': self.contact_name or self.partner_id.name or self.name,
                'default_phone': self.phone,
                'default_email': self.email_from,
                'default_referrer_partner_id': self.referred_by_partner_id.id,
            },
        }
