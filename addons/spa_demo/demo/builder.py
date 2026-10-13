# Part of ERP Servicios Spa. License LGPL-3.
"""Construye un spa «que opera hace seis semanas» con los métodos reales del negocio.

Cómo funciona
-------------
1. Se arma una agenda con cada operación en su fecha y hora (altas, reservas, ingresos con QR,
   cancelaciones, invitados, cortesías, pagos, compras, fondo fijo, eventos, clases y POS) y
   los procesos automáticos de cada día (06:05 estados de membresía, cobranza y devengo; 12:00
   recordatorios; 21:30 salidas, no-show, eventos y clases).
2. :class:`DemoClock` congela la hora en cada evento y lo ejecuta con el usuario del rol que lo
   haría en el spa (recepción, caja, gerente, marketing, contador, custodio, mesero, socio del
   portal). Nada se escribe por SQL ni se fuerzan estados: las facturas, asientos, saldos y
   prospectos los generan los módulos del spa.
3. Si una regla del negocio rechaza un evento (p. ej. la franja se llenó o el socio no tiene
   saldo) el evento se descarta en su punto de guardado y la demo sigue: así se comporta la
   recepción real. Los errores de programación o de permisos detienen la instalación.
"""
import base64
import logging
import random
import time
import unicodedata
import uuid
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.l10n_bo_purchase.tools import siat

from . import data
from .clock import DemoClock
from .images import payment_qr_png, receipt_png

_logger = logging.getLogger(__name__)

TZ = 'America/La_Paz'
# Reloj real para medir tiempos (freezegun reemplaza las referencias a time.perf_counter a nivel de módulo).
REAL_CLOCK = {'perf_counter': time.perf_counter}
CUFD_CONTROL = '67A75AC82F24C74'   # código de control de CUFD de ejemplo (formato de go-siat)
POOL_STARTS = (7, 9, 11, 13, 15, 17, 19)


class SpaDemoBuilder:

    def __init__(self, env):
        lang = env['res.lang'].sudo().search([('code', '=', 'es_BO'), ('active', '=', True)], limit=1)
        context = dict(env.context, tz=TZ)
        if lang:
            context['lang'] = lang.code
        self.env = env(context=context, su=True)
        self.lang = lang.code if lang else False
        self.company = self.env.company
        self.tools = self.env['spa.tools']
        self.rng = random.Random(data.SEED)
        self.stats = {'events': 0, 'skipped': 0}
        self.skipped = {}
        self.timing = {}
        self.users = {}
        self.portal = {}
        self.members = {}
        self.partners = {}
        self.leads = {}
        self.courtesies = {}
        self.vendors = {}
        self.rentals = {}
        self.fund = self.fund_report = self.class_template = None
        self.clock = None

    # ==================================================================
    # Entrada
    # ==================================================================
    def _blocked_reason(self):
        icp = self.env['ir.config_parameter']
        if icp.get_param(data.DEMO_PARAM):
            return 'ya se cargó (parámetro %s)' % data.DEMO_PARAM
        if self.company.chart_template != 'bo':
            return 'la compañía %s no usa el plan contable boliviano' % self.company.name
        if self.env['spa.membership'].search_count([], limit=1):
            return 'la base ya tiene membresías: la demo solo se carga en una base nueva'
        if self.env['account.move'].search_count([('state', '=', 'posted')], limit=1):
            return 'la base ya tiene asientos contables: la demo solo se carga en una base nueva'
        return False

    def load(self):
        reason = self._blocked_reason()
        if reason:
            _logger.warning('spa_demo: no se cargan datos de demostración: %s.', reason)
            return False
        started = time.perf_counter()
        self.today = self.tools.local_today()
        self.first_day = self.today - timedelta(days=data.DAYS_BACK)
        self._prepare_members()
        earliest = min([self.first_day] + [spec['start_date'] for spec in self.members.values()
                                           if spec.get('start_date')]) - timedelta(days=1)
        self.clock = DemoClock(self.env)
        self.real_now = self.clock.real_now
        self.clock.start(self._utc(earliest, 8.0))
        try:
            mark = REAL_CLOCK['perf_counter']()
            self._setup()
            self.stats['setup_s'] = round(REAL_CLOCK['perf_counter']() - mark, 1)
            self._plan()
            self.clock.run(self._run_event)
        except BaseException:
            self.clock.stop(flush=False)  # la hora vuelve a ser la real aunque la instalación falle
            raise
        self.clock.stop()
        self._finish()
        elapsed = time.perf_counter() - started
        _logger.info('spa_demo: demo cargada en %.1f s: %s eventos, %s descartados por reglas del negocio (%s).',
                     elapsed, self.stats['events'], self.stats['skipped'],
                     ', '.join('%s: %s' % item for item in sorted(self.skipped.items())) or '-')
        return True

    # ==================================================================
    # Utilidades
    # ==================================================================
    def _utc(self, day, hour):
        return self.tools.local_combine(day, hour)

    def _day(self, offset):
        return self.today + timedelta(days=offset)

    def _at(self, offset, hour, func, *args, label=None, **kwargs):
        return self.clock.schedule(self._utc(self._day(offset), hour), label or func.__name__, func, *args, **kwargs)

    def _run_event(self, label, func, args, kwargs):
        self.env.invalidate_all()  # como una petición nueva: sin datos leídos por otro usuario
        self.stats['events'] += 1
        started = REAL_CLOCK['perf_counter']()
        try:
            with self.env.cr.savepoint():
                func(*args, **kwargs)
        except AccessError:
            raise
        except (UserError, ValidationError) as error:
            self.stats['skipped'] += 1
            key = label.split(':')[0]
            self.skipped[key] = self.skipped.get(key, 0) + 1
            _logger.debug('spa_demo: %s descartado: %s', label, error)
        finally:
            spent = self.timing.setdefault(label, [0, 0.0])
            spent[0] += 1
            spent[1] += REAL_CLOCK['perf_counter']() - started

    def _ref(self, xmlid):
        return self.env.ref(xmlid)

    def _source(self, key):
        """Fuente del CRM (las de spa_crm; Facebook es la estándar de utm)."""
        xmlid = 'utm.utm_source_facebook' if key == 'facebook' else 'spa_crm.utm_source_%s' % key
        return self.env.ref(xmlid, raise_if_not_found=False) or self.env['utm.source']

    def _acc(self, xmlid):
        return self.env['account.chart.template'].with_company(self.company).ref(xmlid)

    def _as(self, role):
        return self.users[role]

    def _email(self, name):
        base = name.replace('Demo – ', '').split(' (')[0].lower()
        ascii_text = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode()
        clean = ''.join(c for c in ascii_text if c.isalnum() or c == ' ')
        return '%s@%s' % ('.'.join(clean.split()), data.EMAIL_DOMAIN)

    def _start_for_end(self, end, months):
        """Fecha de alta cuya duración vence en ``end`` (o lo más cerca posible)."""
        base = end + timedelta(days=1) - relativedelta(months=months)
        best = None
        for delta in (0, -1, 1, -2, 2, -3, 3):
            start = base + timedelta(days=delta)
            got = start + relativedelta(months=months) - timedelta(days=1)
            score = abs((got - end).days)
            if best is None or score < best[0]:
                best = (score, start)
        return best[1]

    def _end_of(self, start, months):
        return start + relativedelta(months=months) - timedelta(days=1)

    def _partner(self, name, phone, email=None, vat=None, user=None, doc_type='1'):
        """Contacto (lo crea recepción); reutiliza el que ya existe con ese celular."""
        Partner = self.env['res.partner']
        partner = Partner._spa_find_by_phone(phone)
        vals = {'name': name, 'phone': phone, 'email': email or self._email(name), 'city': 'La Paz',
                'country_id': self._ref('base.bo').id}
        if vat:
            vals.update(vat=vat, l10n_bo_siat_id_type=doc_type)
        if partner:
            partner.with_user(user or self._as('reception')).write(vals)
            return partner
        return Partner.with_user(user or self._as('reception')).create(vals).sudo()

    def _receipt_vals(self, amount, reference):
        return {'receipt': receipt_png(self.company.currency_id.format(amount), reference),
                'receipt_filename': 'comprobante-%s.png' % reference.lower()}

    def _reference(self, method):
        prefix = {'qr': 'QR', 'transfer': 'TRF', 'cash': 'REC', 'card': 'TAR'}[method]
        return '%s-%06d' % (prefix, self.rng.randint(1, 999999))

    # ==================================================================
    # 1. Configuración (gerente / dueño)
    # ==================================================================
    def _setup(self):
        self._setup_users()
        owner = self._as('owner')
        company = self.company
        icp = self.env['ir.config_parameter']
        for key, value in {
            'spa.timezone': TZ,
            'spa_messaging.provider': 'wa_link',
            'spa_crm.guest_welcome': 'True',
            'spa_crm.followup_days': '2',
            'spa_crm.courtesy_monthly_limit': '10',
            'spa_crm.courtesy_validity_days': '15',
            'spa_crm.retention_low_usage_pct': '10',
            'spa_crm.retention_low_usage_day': '15',
            'spa_crm.retention_expiry_days': '0',
            'spa_portal.booking_days': '14',
        }.items():
            icp.set_param(key, value)

        Journal = self.env['account.journal'].with_user(owner)
        bank = Journal.search([('code', '=', 'BDEMO'), ('company_id', '=', company.id)], limit=1) or Journal.create({
            'name': 'Banco Demo (ficticio) – QR y transferencias', 'code': 'BDEMO', 'type': 'bank',
            'company_id': company.id})
        cash = Journal.search([('code', '=', 'CDEMO'), ('company_id', '=', company.id)], limit=1) or Journal.create({
            'name': 'Caja recepción (demo)', 'code': 'CDEMO', 'type': 'cash', 'company_id': company.id})
        self.bank_journal = bank.sudo()
        provider = self.env['l10n_bo.siat.provider']._l10n_bo_create_demo(company)
        company.with_user(owner).write({
            'name': 'Spa Demo Bolivia',
            'vat': '1020304050',
            'street': 'Av. Ficticia 123 (dirección de demostración)',
            'city': 'La Paz',
            'country_id': self._ref('base.bo').id,
            'phone': '+591 70008100',
            'email': 'contacto@%s' % data.EMAIL_DOMAIN,
            'spa_payment_qr': base64.b64encode(payment_qr_png(self.env)),
            'spa_bank_account_text': 'Banco Demo (FICTICIO) · Cta. 0000-000000 · Spa Demo Bolivia — no realizar pagos',
            'spa_payment_instructions': 'DEMOSTRACIÓN: el QR y la cuenta son ficticios. En producción, el socio paga '
                                        'con el QR de su app bancaria y envía el comprobante.',
            'spa_payment_journal_id': bank.id,
            'spa_cash_journal_id': cash.id,
            'spa_renewal_days': 5,
            'l10n_bo_siat_provider_id': provider.id,
            'l10n_bo_siat_mode': 'provider',
        })
        self._ref('spa_messaging.tpl_booking_confirmed').with_user(owner).active = True
        # Personal: masajista e instructor con su usuario (ven su agenda).
        self._ref('spa_base.employee_massage_therapist').with_user(owner).write({
            'name': 'Demo – Rosa Quispe (masajista)', 'user_id': self._as('therapist').id})
        self._ref('spa_rental.employee_swim_instructor').with_user(owner).write({
            'name': 'Demo – Marco Alanoca (instructor de natación)', 'user_id': self._as('instructor').id})
        self.plans = {'basic': self._ref('spa_membership.plan_basic'),
                      'premium': self._ref('spa_membership.plan_premium'),
                      'vip': self._ref('spa_membership.plan_vip')}
        for key, plan in self.plans.items():
            plan.with_user(owner).write({'website_published': True, 'active': True,
                                         'freeze_max_days': {'basic': 0, 'premium': 30, 'vip': 45}[key]})
        # Ofertas de pago de la campaña (vigentes desde antes de la historia).
        Offer = self.env['spa.payment.offer'].with_user(owner)
        self.offers = {
            'installments': Offer.create({
                'name': 'Demo – Plan anual Premium en 3 cuotas sin recargo', 'offer_type': 'installments',
                'installments': 3, 'months': 12, 'plan_ids': [Command.set(self.plans['premium'].ids)],
                'date_from': self.first_day - timedelta(days=30), 'date_to': self.today + timedelta(days=60),
                'description': 'Oferta de demostración.'}).sudo(),
            'annual_discount': Offer.create({
                'name': 'Demo – Plan anual con 10 % (lanzamiento)', 'offer_type': 'discount',
                'discount_percent': 10.0, 'months': 12,
                'date_from': self.first_day - timedelta(days=30), 'date_to': self.today + timedelta(days=60),
                'description': 'Oferta de demostración.'}).sudo(),
        }
        self.services = {
            'pool': self._ref('spa_base.service_pool'), 'sauna': self._ref('spa_base.service_sauna'),
            'jacuzzi': self._ref('spa_base.service_jacuzzi'), 'massage': self._ref('spa_base.service_massage'),
        }
        self.spaces = {
            'pool': self._ref('spa_base.space_pool'), 'sauna': self._ref('spa_base.space_sauna'),
            'jacuzzi': self._ref('spa_base.space_jacuzzi'), 'massage': self._ref('spa_base.space_massage_room'),
        }

    def _setup_users(self):
        Users = self.env['res.users'].with_context(no_reset_password=True)
        company = self.company
        for role, login, name, phone in data.STAFF:
            groups = [self._ref(xmlid).id for xmlid in data.ROLE_GROUPS[role]]
            user = Users.with_context(active_test=False).search([('login', '=', login)], limit=1)
            vals = {
                'name': name, 'login': login, 'email': '%s@%s' % (
                    login.replace('.demo', ''), data.EMAIL_DOMAIN),
                'phone': phone, 'tz': TZ, 'notification_type': 'inbox',
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(groups)],
            }
            if self.lang:
                vals['lang'] = self.lang
            user = user or Users.create(vals)
            self._set_demo_password(user)
            self.users[role] = user

    def _set_demo_password(self, user):
        """Contraseña «demo» (el hash se calcula una vez: es la parte lenta de crear usuarios)."""
        if not getattr(self, '_password_hash', None):
            self._password_hash = self.env['res.users']._crypt_context().hash(data.DEMO_PASSWORD)
        self.env['res.users']._set_encrypted_password(user.id, self._password_hash)

    def _portal_user(self, key, login, partner):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'login': login, 'partner_id': partner.id,
            'group_ids': [Command.set([self._ref('base.group_portal').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)], 'tz': TZ,
            **({'lang': self.lang} if self.lang else {}),
        })
        self._set_demo_password(user)
        self.portal[key] = user
        return user

    # ==================================================================
    # 2. Agenda
    # ==================================================================
    def _prepare_members(self):
        for index, spec in enumerate(data.MEMBERS):
            spec = dict(spec)
            spec['phone'] = '+591 7000%04d' % (1001 + index)
            spec['ci'] = '%d' % (8100001 + index)
            spec['email'] = self._email(spec['name'])
            if 'start' in spec:
                spec['start_date'] = self._day(spec['start'])
            elif 'end' in spec:
                spec['start_date'] = self._start_for_end(self._day(spec['end']), spec['months'])
            if spec.get('start_date'):
                spec['end_date'] = self._end_of(spec['start_date'], spec['months'])
            self.members[spec['key']] = spec

    def _plan(self):
        first = (self.first_day - self.today).days
        # Socio antiguo que no renovó: sus procesos de mora antes de la historia de seis semanas.
        walter = self.members['walter']
        for offset in (-5, 1, 5, 15):
            day = (walter['end_date'] + timedelta(days=offset) - self.today).days
            if day < first:
                self._at(day, 6 + 5 / 60, self._ev_membership_crons, label='cron:membership')
        for offset in range(first, 1):
            self._plan_daily_crons(offset)
        for spec in self.members.values():
            self._plan_member(spec)
        self._plan_usage()
        self._plan_guests()
        self._plan_crm()
        self._plan_visitors()
        self._plan_pos()
        self._plan_purchases()
        self._plan_petty_cash()
        self._plan_rentals()
        self._plan_classes()
        self._plan_today()

    def _plan_daily_crons(self, offset):
        morning = self._utc(self._day(offset), 6 + 5 / 60)
        if offset == 0:
            # Hoy: si la instalación es de madrugada, el proceso diario corre al instalar.
            morning = min(morning, self.real_now)
        self.clock.schedule(morning, 'cron:morning', self._ev_morning_crons)
        self._at(offset, 12.0, self._ev_reminders, label='cron:reminders')
        self._at(offset, 21.5, self._ev_evening_crons, label='cron:evening')

    # ------------------------------------------------------------------
    # Procesos automáticos (como ir.cron: superusuario)
    # ------------------------------------------------------------------
    def _ev_membership_crons(self):
        Membership = self.env['spa.membership']
        Membership._cron_membership_daily()
        Membership._cron_billing_daily()
        Membership._cron_spa_retention()

    def _ev_morning_crons(self):
        self._ev_membership_crons()
        self.env['spa.courtesy.pass']._cron_expire_passes()
        self.env['spa.class.template']._cron_generate_sessions()

    def _ev_reminders(self):
        self.env['spa.booking']._cron_booking_reminders()

    def _ev_evening_crons(self):
        self.env['spa.access.log']._cron_auto_check_out()
        self.env['spa.booking']._cron_booking_states()
        self.env['spa.rental']._cron_rentals()
        self.env['spa.class.session']._cron_sessions()
        # Recepción envía los WhatsApp del día (enlace wa.me) antes de cerrar.
        reception = self._as('reception')
        for message in self.env['spa.message'].search([('state', '=', 'ready')]):
            message.with_user(reception).action_open_whatsapp()

    # ==================================================================
    # 3. Socios
    # ==================================================================
    def _plan_member(self, spec):
        story = spec.get('story')
        if story == 'web_signup':
            self._at(-1, 19 + 50 / 60, self._ev_web_signup, spec, label='member:web_signup')
            return
        if story == 'today':
            self.clock.schedule(self.real_now, 'member:today', self._ev_today_member, spec)
            return
        start = spec['start_date']
        hour = self.rng.choice([9.5, 10.25, 11.0, 12.5, 15.0, 16.75, 18.0])
        spec['enroll_at'] = self._utc(start, hour)
        self.clock.schedule(spec['enroll_at'], 'member:enroll', self._ev_enroll, spec)
        offset = (start - self.today).days
        if story == 'renew_portal':
            pay_day = (spec['end_date'] - self.today).days - 2
            self._at(pay_day, 20.5, self._ev_portal_renewal, spec, label='member:portal_renewal')
            self._at(pay_day + 1, 9.5, self._ev_validate_pending, spec, label='member:validate')
        elif story == 'installments':
            self._at(-1, 21.0, self._ev_portal_installment, spec, label='member:portal_installment')
        elif story == 'downgrade':
            self._at(-6, 11.0, self._ev_plan_change, spec, 'basic', label='member:downgrade')
        elif story == 'upgrade':
            self._at(-10, 16.0, self._ev_plan_change, spec, 'vip', label='member:upgrade')
        elif story == 'freeze':
            self._at(-4, 11.0, self._ev_freeze, spec, label='member:freeze')
        elif story == 'cancelled':
            self._at(offset + 16, 10.0, self._ev_cancel_membership, spec, label='member:cancel')

    def _ev_enroll(self, spec):
        reception, cashier = self._as('reception'), self._as('cashier')
        partner = self._partner(spec['name'], spec['phone'], spec['email'], vat=spec['ci'])
        self.partners[spec['key']] = partner
        plan = self.plans[spec['plan']]
        period = plan.period_ids.filtered(lambda p: p.months == spec['months'])[:1]
        membership = self.env['spa.membership'].with_user(reception).create({
            'partner_id': partner.id, 'plan_id': plan.id, 'period_id': period.id,
            'note': 'Socio de demostración (ficticio).'})
        spec['membership'] = membership.sudo()
        offer = self.offers.get(spec.get('story'))
        self.env.invalidate_all()
        invoice = membership.with_user(reception).action_create_invoice(offer=offer).sudo()
        amount = None
        if offer and offer.offer_type == 'installments':
            amount = invoice._get_invoice_next_payment_values()['next_amount_to_pay']
        request = self._payment_request(membership, spec['pay'], reception, amount=amount)
        self.env.invalidate_all()
        request.with_user(cashier).action_validate()
        if spec.get('portal') and spec['key'] not in self.portal:
            self._portal_user(spec['key'], spec['portal'], partner)

    def _payment_request(self, membership, method, user, amount=None):
        """Recepción registra el pago desde la membresía (queda «por validar» en caja)."""
        self.env.invalidate_all()
        action = membership.with_user(user).action_register_payment_request()
        context = action['context']
        reference = self._reference(method)
        vals = {'method': method, 'reference': reference}
        if amount is not None:
            vals['amount'] = amount
        if method in ('qr', 'transfer'):
            vals.update(self._receipt_vals(amount or context.get('default_amount') or 0.0, reference))
        return self.env['spa.payment.request'].with_user(user).with_context(**context).create(vals).sudo()

    def _portal_payment(self, invoice, user, amount, method='qr'):
        """El socio informa su pago en la web (/my/spa/pay/<factura>/submit) con la foto del comprobante."""
        reference = self._reference(method)
        vals = {
            'partner_id': invoice.partner_id.id,
            'membership_id': invoice.spa_membership_id.id,
            'invoice_id': invoice.id,
            'company_id': invoice.company_id.id,
            'amount': amount,
            'method': method,
            'reference': reference,
            'channel': 'portal',
        }
        vals.update(self._receipt_vals(amount, reference))
        return self.env['spa.payment.request'].with_user(user).sudo().with_context(
            mail_create_nosubscribe=True).create(vals)

    def _ev_portal_renewal(self, spec):
        membership = spec['membership']
        invoice = membership._open_period_invoice()[:1]
        if not invoice:
            raise UserError('Sin cobro de renovación')
        self._portal_payment(invoice, self.portal[spec['key']], invoice.amount_residual)

    def _ev_validate_pending(self, spec):
        cashier = self._as('cashier')
        for request in spec['membership'].payment_request_ids.filtered(lambda r: r.state == 'pending'):
            request.with_user(cashier).action_validate()

    def _ev_portal_installment(self, spec):
        membership = spec['membership']
        invoice = membership.invoice_ids.filtered(
            lambda m: m.spa_invoice_kind == 'membership' and m.state == 'posted' and m.amount_residual > 0)[:1]
        if not invoice:
            raise UserError('Sin cuota pendiente')
        amount = invoice._get_invoice_next_payment_values().get('next_amount_to_pay') or invoice.amount_residual
        self._portal_payment(invoice, self.portal[spec['key']], amount, method='transfer')

    def _ev_plan_change(self, spec, plan_key):
        reception, cashier = self._as('reception'), self._as('cashier')
        membership = spec['membership']
        wizard = self.env['spa.plan.change'].with_user(reception).create({
            'membership_id': membership.id, 'new_plan_id': self.plans[plan_key].id})
        action = wizard.action_confirm()
        if action.get('res_model') == 'spa.payment.request':
            reference = self._reference('cash')
            request = self.env['spa.payment.request'].with_user(reception).with_context(**action['context']).create(
                {'method': 'cash', 'reference': reference})
            self.env.invalidate_all()
            request.with_user(cashier).action_validate()

    def _ev_freeze(self, spec):
        membership = spec['membership']
        for booking in membership.booking_ids.filtered(
                lambda b: b.state == 'confirmed' and self.tools.to_local(b.start).date() >= self._day(-2)):
            booking.with_user(self._as('reception')).action_cancel()
        membership.with_user(self._as('owner'))._spa_freeze(
            self._day(-2), self._day(12), 'Viaje familiar (demostración)')

    def _ev_cancel_membership(self, spec):
        membership = spec['membership']
        membership.with_user(self._as('owner')).action_cancel()
        membership.message_post(body='Baja solicitada por el socio: se muda a otra ciudad (demostración).')

    def _ev_web_signup(self, spec):
        """Alta en la web (/spa/plan/<id>/subscribe) de alguien que crea su cuenta; paga con QR y queda por validar."""
        partner = self._partner(spec['name'], spec['phone'], spec['email'], vat=spec['ci'])
        self.partners[spec['key']] = partner
        user = self._portal_user(spec['key'], spec['portal'], partner)
        plan = self.plans[spec['plan']]
        period = plan.period_ids.filtered(lambda p: p.months == spec['months'])[:1]
        Membership = self.env['spa.membership'].with_user(user).sudo().with_context(mail_create_nosubscribe=True)
        membership = Membership.create({'partner_id': partner.id, 'plan_id': plan.id, 'period_id': period.id,
                                        'company_id': plan.company_id.id})
        spec['membership'] = membership
        invoice = membership.action_create_invoice()
        invoice.filtered(lambda m: m.invoice_user_id and not m.invoice_user_id._is_internal()).with_context(
            tracking_disable=True).write({'invoice_user_id': False})
        self.clock.schedule(fields.Datetime.now() + timedelta(minutes=12), 'member:web_payment',
                            self._portal_payment, invoice, user, invoice.amount_residual)

    def _ev_today_member(self, spec):
        """Alta de hoy en recepción: venía como prospecto de mostrador y paga en efectivo."""
        lead_partner = self._partner(spec['name'], spec['phone'], spec['email'], vat=spec['ci'])
        self.env['crm.lead'].with_user(self._as('reception')).create({
            'name': 'Consulta en recepción: %s' % spec['name'], 'partner_id': lead_partner.id,
            'phone': spec['phone'], 'email_from': spec['email'],
            'source_id': self._source('reception').id})
        self._ev_enroll(spec)

    # ==================================================================
    # 4. Uso: reservas, ingresos con QR, cancelaciones y no-show
    # ==================================================================
    def _usage_days(self, spec):
        story = spec.get('story')
        if not spec.get('usage') or not spec.get('start_date'):
            if story == 'today':
                return [self._day(offset) for offset in range(0, data.DAYS_AHEAD + 1)]
            return []
        first = max(spec['start_date'] + timedelta(days=1), self.first_day)
        last = self._day(data.DAYS_AHEAD)
        end = spec['end_date']
        if story in ('grace', 'suspended'):
            last = min(last, end + timedelta(days=1))
        elif story == 'cancelled':
            last = min(last, spec['start_date'] + timedelta(days=15))
        days = []
        day = first
        while day <= last:
            if not (story == 'freeze' and self._day(-5) <= day <= self._day(12)):
                days.append(day)
            day += timedelta(days=1)
        return days

    def _plan_usage(self):
        weights = {
            'basic': [('pool', 6), ('sauna', 4)],
            'premium': [('pool', 3), ('sauna', 2), ('jacuzzi', 3), ('massage', 2)],
            'vip': [('pool', 2), ('sauna', 2), ('jacuzzi', 3), ('massage', 3)],
        }
        probability = {1: 0.12, 2: 0.2, 3: 0.32}
        # Servicios con cupo que el socio usa al empezar cada mes (así solo «Rosa» queda con uso bajo).
        habit = {'basic': ('sauna', 'sauna'), 'premium': ('jacuzzi', 'massage'), 'vip': ('massage', 'massage')}
        for spec in self.members.values():
            usage = spec.get('usage') or 0
            days = self._usage_days(spec)
            if not usage or not days:
                continue
            for year, month in sorted({(day.year, day.month) for day in days}):
                early = [day for day in days if (day.year, day.month) == (year, month) and day.day <= 13]
                for target, kind in zip((3, 9), habit[spec['plan']]):
                    if early:
                        day = min(early, key=lambda d, t=target: abs(d.day - t))
                        self._plan_visit(spec, kind, day, outcome='attend')
            for day in days:
                # La agenda de los próximos días ya tiene más reservas que un día cualquiera del pasado.
                if self.rng.random() >= probability[usage] * (1.6 if day > self.today else 1.0):
                    continue
                kinds, kind_weights = zip(*weights[spec['plan']])
                kind = self.rng.choices(kinds, kind_weights)[0]
                self._plan_visit(spec, kind, day)

    def _plan_visit(self, spec, kind, day, guests=(), hour=None, outcome=None, channel=None, sauna_guests=0):
        rng = self.rng
        if kind == 'sauna':
            hour = hour or rng.choice([10.5, 11.25, 12.0, 15.5, 16.25, 17.0, 18.0, 18.75])
            when = self._utc(day, hour)
            if when < self.real_now:
                visit = {'member': spec['key'], 'guests': sauna_guests}
                self.clock.schedule(when, 'visit:sauna', self._ev_sauna, visit)
            return
        if hour is None:
            hour = {'pool': rng.choice(POOL_STARTS), 'jacuzzi': rng.randint(10, 19),
                    'massage': rng.randint(9, 17)}[kind]
        start = self._utc(day, hour)
        service = self.services[kind]
        stop = start + timedelta(hours=service.duration)
        enroll_at = spec.get('enroll_at') or self.real_now
        created = start - timedelta(hours=rng.uniform(3, 40))
        local = self.tools.to_local(created)
        if local.hour < 8 or local.hour >= 21:
            created = self._utc(local.date(), rng.choice([8.5, 9.0, 20.5]))
        created = max(created, enroll_at + timedelta(minutes=30)).replace(second=0, microsecond=0)
        if created >= start - timedelta(hours=2.5):
            created = start - timedelta(hours=2.5)
        if created < enroll_at:
            return
        if created > self.real_now:
            if start <= self.real_now + timedelta(hours=1):
                return
            created = self.real_now
        if channel is None:
            channels = ['reception', 'whatsapp', 'phone'] + (['portal', 'portal'] if spec.get('portal') else [])
            channel = rng.choice(channels)
        visit = {'member': spec['key'], 'service': kind, 'start': start, 'stop': stop, 'channel': channel,
                 'guests': list(guests)}
        self.clock.schedule(created, 'visit:book', self._ev_book, visit)
        if outcome is None:
            outcome = rng.choices(['attend', 'no_show', 'late_cancel', 'cancel'], [80, 6, 7, 7])[0]
        cancel_at = created + timedelta(minutes=40)
        if outcome == 'cancel' and start - cancel_at <= timedelta(hours=13):
            outcome = 'attend'  # reservó con poca anticipación: no alcanza a cancelar a tiempo
        if outcome == 'attend':
            checkin = start - timedelta(minutes=rng.randint(2, 15))
            self.clock.schedule(checkin, 'visit:checkin', self._ev_checkin, visit)
            self.clock.schedule(stop + timedelta(minutes=rng.randint(1, 6)), 'visit:checkout', self._ev_checkout,
                                visit)
        elif outcome == 'late_cancel':
            self.clock.schedule(start - timedelta(hours=rng.uniform(1.0, 2.5)), 'visit:late_cancel',
                                self._ev_cancel_booking, visit)
        elif outcome == 'cancel':
            self.clock.schedule(cancel_at, 'visit:cancel', self._ev_cancel_booking, visit)

    def _ev_book(self, visit):
        spec = self.members[visit['member']]
        membership = spec.get('membership')
        if not membership:
            raise UserError('Sin membresía')
        partner = membership.partner_id
        vals = {
            'partner_id': partner.id,
            'membership_id': membership.id,
            'payment_mode': 'membership',
            'service_id': self.services[visit['service']].id,
            'start': visit['start'],
            'channel': visit['channel'],
            'company_id': membership.company_id.id,
            'guest_ids': [Command.create({'name': name, 'phone': phone}) for name, phone in visit['guests']],
        }
        portal_user = self.portal.get(visit['member'])
        if visit['channel'] == 'portal' and portal_user:
            Booking = self.env['spa.booking'].with_user(portal_user).sudo().with_context(mail_create_nosubscribe=True)
        else:
            if visit['channel'] == 'portal':
                vals['channel'] = 'whatsapp'
            Booking = self.env['spa.booking'].with_user(self._as('reception'))
        booking = Booking.create(vals)
        booking.action_confirm()
        visit['booking'] = booking.sudo()

    def _ev_checkin(self, visit):
        booking = visit.get('booking')
        if not booking or booking.state != 'confirmed':
            return
        membership = self.members[visit['member']]['membership']
        log = self.env['spa.access.log'].with_user(self._as('reception')).do_check_in(
            booking.space_id, token=membership.qr_token)
        visit['log'] = log.sudo()

    def _ev_checkout(self, visit):
        log = visit.get('log')
        if log and log.state == 'open':
            log.with_user(self._as('reception')).action_check_out()

    def _ev_cancel_booking(self, visit):
        booking = visit.get('booking')
        if booking and booking.state == 'confirmed':
            booking.with_user(self._as('reception')).action_cancel()

    def _ev_sauna(self, visit):
        membership = self.members[visit['member']].get('membership')
        if not membership:
            raise UserError('Sin membresía')
        log = self.env['spa.access.log'].with_user(self._as('reception')).do_check_in(
            self.spaces['sauna'], token=membership.qr_token, guests=visit.get('guests', 0))
        visit['log'] = log.sudo()
        self.clock.schedule(fields.Datetime.now() + timedelta(minutes=self.rng.randint(35, 58)), 'visit:checkout',
                            self._ev_checkout, visit)

    # ------------------------------------------------------------------
    # Invitados
    # ------------------------------------------------------------------
    def _same_month(self, offset, gap):
        """Dos días (offset, offset+gap) del mismo mes, retrocediendo si cruzan de mes."""
        while self._day(offset).month != self._day(offset + gap).month:
            offset -= 1
        return offset, offset + gap

    def _plan_guests(self):
        guests = data.GUESTS
        ana, bruno, dario, nicolas, lorena = (self.members[k] for k in ('ana', 'bruno', 'dario', 'nicolas', 'lorena'))
        self._plan_visit(ana, 'jacuzzi', self._day(-30), guests=[guests['lucia']], hour=11, outcome='attend',
                         channel='portal')
        # La invitada Isabel se hace socia 17 días después (prospecto ganado).
        self._plan_visit(ana, 'jacuzzi', self._day(-20), guests=[guests['isabel']], hour=16, outcome='attend',
                         channel='reception')
        self._plan_visit(bruno, 'jacuzzi', self._day(-16), guests=[guests['mateo'], guests['diana']], hour=12,
                         outcome='attend', channel='portal')
        # Básica: 1 invitado gratis al mes; el segundo del mes paga la tarifa de invitado.
        first, second = self._same_month(-12, 2)
        self._plan_visit(dario, 'pool', self._day(first), guests=[guests['ernesto']], hour=9, outcome='attend')
        self._plan_visit(dario, 'pool', self._day(second), guests=[guests['carmen']], hour=17, outcome='attend')
        self._plan_visit(nicolas, 'pool', self._day(-7), guests=[guests['pedro']], hour=11, outcome='attend')
        self._plan_visit(lorena, 'sauna', self._day(-5), hour=16.5, sauna_guests=1)

    # ==================================================================
    # 5. CRM: prospectos, cortesías y conversiones
    # ==================================================================
    def _plan_crm(self):
        for index, lead in enumerate(data.LEADS):
            lead = dict(lead, phone='+591 7000%04d' % (3001 + index))
            if lead['day'] == 0:
                self.clock.schedule(self.real_now, 'crm:lead', self._ev_lead, lead)
            else:
                self._at(lead['day'], 10.0 + index * 0.4, self._ev_lead, lead, label='crm:lead')
        # Hugo: Instagram → cortesía → la usa en la piscina → se hace socio.
        hugo = self.members['hugo']
        hugo_lead = {'key': 'hugo', 'name': hugo['name'], 'phone': hugo['phone'], 'source': 'instagram',
                     'stage': 'interested', 'note': 'Escribió por Instagram tras ver una historia del spa.'}
        offset = (hugo['start_date'] - self.today).days
        self._at(offset - 7, 10.5, self._ev_lead, hugo_lead, label='crm:lead')
        self._at(offset - 6, 11.0, self._ev_lead_courtesy, hugo_lead, 'pool', 1, label='crm:courtesy')
        self._at(offset - 4, 10.0, self._ev_redeem, hugo_lead, 'pool', label='crm:redeem')
        # Gonzalo (TikTok): cortesía de sauna canjeada, sigue en «Visita».
        gonzalo = next(lead for lead in data.LEADS if lead['key'] == 'gonzalo')
        self._at(gonzalo['day'] + 1, 12.0, self._ev_lead_courtesy, {'key': 'gonzalo'}, 'sauna', 1,
                 label='crm:courtesy')
        self._at(gonzalo['day'] + 2, 16.0, self._ev_redeem, {'key': 'gonzalo'}, 'sauna', label='crm:redeem')
        # Cortesías sueltas: vencida, canjeada y vigente.
        for index, courtesy in enumerate(data.COURTESIES):
            courtesy = dict(courtesy, phone='+591 7000%04d' % (3101 + index))
            self._at(courtesy['issue'], 15.0, self._ev_courtesy, courtesy, label='crm:courtesy')
            if courtesy['redeem'] is not None:
                self._at(courtesy['redeem'], 17.0, self._ev_redeem, courtesy, 'sauna', label='crm:redeem')

    def _ev_lead(self, lead):
        marketing = self._as('marketing')
        Lead = self.env['crm.lead']
        source = self._source(lead['source'])
        vals = {
            'name': 'Consulta: %s' % lead['name'],
            'contact_name': lead['name'],
            'phone': lead['phone'],
            'email_from': self._email(lead['name']),
            'source_id': source.id,
            'description': lead.get('note'),
            'team_id': (source.spa_team_id or Lead._spa_team('acquisition', self.company)).id,
        }
        if lead.get('referrer'):
            referrer = self.partners.get(lead['referrer'])
            if referrer:
                vals.update(referred_by_partner_id=referrer.id, referred=referrer.name)
        record = Lead.with_user(marketing).create(vals).sudo()
        self.leads[lead['key']] = record
        stage = lead.get('stage')
        if stage in ('visit', 'proposal'):
            target = Lead._spa_stage(record.team_id, stage)
            if target:
                record.with_user(marketing).write({'stage_id': target.id})
        elif stage == 'lost':
            self.clock.schedule(fields.Datetime.now() + timedelta(days=3), 'crm:lost', self._ev_lead_lost,
                                lead['key'])

    def _ev_lead_lost(self, key):
        lead = self.leads[key]
        reason = self.env['crm.lost.reason'].search([], limit=1)
        lead.with_user(self._as('marketing')).action_set_lost(lost_reason_id=reason.id)
        lead.message_post(body='Se contactó dos veces: por ahora no le interesa (demostración).')

    def _ev_lead_courtesy(self, lead, kind, visits):
        """Marketing emite el pase desde el prospecto (botón «Emitir pase de cortesía»)."""
        record = self.leads[lead['key']]
        marketing = self._as('marketing')
        action = record.with_user(marketing).action_spa_issue_courtesy()
        courtesy = self.env['spa.courtesy.pass'].with_user(marketing).with_context(**action['context']).create({
            'service_ids': [Command.set(self.services[kind].ids)], 'visits': visits,
            'reason': 'Visita de prueba (demostración)'})
        self.courtesies[lead['key']] = courtesy.sudo()

    def _ev_courtesy(self, courtesy):
        user = self._as('reception') if courtesy['key'] == 'ricardo' else self._as('marketing')
        record = self.env['spa.courtesy.pass'].with_user(user).create({
            'guest_name': courtesy['name'], 'phone': courtesy['phone'], 'email': self._email(courtesy['name']),
            'service_ids': [Command.set((self.services['sauna'] | self.services['pool']).ids)],
            'visits': courtesy['visits'], 'reason': courtesy['reason'],
            'source_id': self._source(courtesy['source']).id})
        self.courtesies[courtesy['key']] = record.sudo()

    def _ev_redeem(self, lead, kind):
        courtesy = self.courtesies[lead['key']]
        log = self.env['spa.access.log'].with_user(self._as('reception')).do_check_in(
            self.spaces[kind], token=courtesy.token)
        visit = {'log': log.sudo()}
        self.clock.schedule(fields.Datetime.now() + timedelta(minutes=75), 'visit:checkout', self._ev_checkout, visit)

    # ==================================================================
    # 6. Visitantes sin membresía: entradas sueltas y pases diarios
    # ==================================================================
    def _plan_visitors(self):
        plan = [(-37, 'pool', 11), (-29, 'massage', 15), (-22, 'pool', 15), (-15, 'massage', 10),
                (-8, 'pool', 9), (-3, 'massage', 16), (2, 'pool', 13)]
        for index, (offset, kind, hour) in enumerate(plan):
            visitor = data.VISITORS[index % len(data.VISITORS)]
            visit = {'visitor': visitor, 'service': kind, 'start': self._utc(self._day(offset), hour)}
            created = visit['start'] - timedelta(hours=26)
            if visit['start'] > self.real_now:
                created = self.real_now
                if visit['start'] <= self.real_now + timedelta(hours=1):
                    continue
            self.clock.schedule(created, 'single:book', self._ev_single_book, visit)
            self.clock.schedule(visit['start'] - timedelta(minutes=8), 'single:checkin', self._ev_single_checkin, visit)
        for index, offset in enumerate((-33, -19, -11, -4)):
            visitor = data.VISITORS[(index + 2) % len(data.VISITORS)]
            self._at(offset, 11.5 + index, self._ev_day_pass, {'visitor': visitor}, label='single:day_pass')

    def _visitor(self, visitor):
        name, phone = visitor
        return self._partner(name, phone)

    def _ev_single_book(self, visit):
        partner = self._visitor(visit['visitor'])
        booking = self.env['spa.booking'].with_user(self._as('reception')).create({
            'partner_id': partner.id, 'payment_mode': 'single', 'service_id': self.services[visit['service']].id,
            'start': visit['start'], 'channel': 'phone'})
        booking.action_confirm()
        visit['booking'] = booking.sudo()

    def _ev_single_checkin(self, visit):
        booking = visit.get('booking')
        if not booking or booking.state != 'confirmed':
            return
        reception, cashier = self._as('reception'), self._as('cashier')
        log = self.env['spa.access.log'].with_user(reception).do_check_in(booking.space_id, partner=booking.partner_id)
        visit['log'] = log.sudo()
        self.env.invalidate_all()
        action = booking.with_user(reception).action_register_payment_request()
        request = self.env['spa.payment.request'].with_user(reception).with_context(**action['context']).create({
            'method': 'cash', 'reference': self._reference('cash')})
        self.env.invalidate_all()
        request.with_user(cashier).action_validate()
        self.clock.schedule(booking.stop + timedelta(minutes=2), 'visit:checkout', self._ev_checkout, visit)

    def _ev_day_pass(self, visit):
        reception, cashier = self._as('reception'), self._as('cashier')
        partner = self._visitor(visit['visitor'])
        log = self.env['spa.access.log'].with_user(reception).do_check_in(
            self.spaces['sauna'], partner=partner, day_pass=True).sudo()
        invoice = log.invoice_id
        request = self.env['spa.payment.request'].with_user(reception).create({
            'partner_id': partner.id, 'invoice_id': invoice.id, 'amount': invoice.amount_residual,
            'method': 'cash', 'reference': self._reference('cash'), 'channel': 'reception'})
        self.env.invalidate_all()
        request.with_user(cashier).action_validate()
        visit['log'] = log
        self.clock.schedule(fields.Datetime.now() + timedelta(minutes=50), 'visit:checkout', self._ev_checkout, visit)

    # ==================================================================
    # 7. Restaurante y cafetería (POS)
    # ==================================================================
    def _plan_pos(self):
        restaurant = self.env['pos.config']._spa_get_config('restaurant')
        cafe = self.env['pos.config']._spa_get_config('cafe')
        self.pos_products = {name: self._ref('spa_pos.product_%s' % name) for name in (
            'coffee', 'cappuccino', 'juice', 'saltena', 'salad', 'trout', 'pique_macho', 'water')}
        sessions = [
            (restaurant, -9, [12.2, 12.5, 12.8, 13.1, 13.4, 13.7, 14.0, 14.3, 14.6, 19.2, 19.5, 19.8, 20.1, 20.4,
                              20.6, 20.8, 12.9, 13.9, 19.9, 20.3]),
            (cafe, -2, [8.6, 9.1, 9.7, 10.2, 10.8, 11.3, 11.9, 12.4, 15.1, 15.6, 16.0, 16.4, 16.8, 17.1, 17.4,
                        17.7, 9.4, 10.5, 16.2, 17.2]),
        ]
        menus = {
            'restaurant': [[('trout', 1), ('juice', 1)], [('pique_macho', 1), ('water', 2)],
                           [('salad', 1), ('juice', 1)], [('trout', 2), ('water', 2)],
                           [('pique_macho', 2), ('juice', 2)], [('salad', 2), ('water', 1)]],
            'cafe': [[('coffee', 1), ('saltena', 2)], [('cappuccino', 1)], [('juice', 1), ('saltena', 1)],
                     [('coffee', 2)], [('cappuccino', 2), ('saltena', 2)], [('water', 1)]],
        }
        for config, offset, hours in sessions:
            kind = 'restaurant' if config == restaurant else 'cafe'
            hours = sorted(hours)
            self._at(offset, hours[0] - 0.2, self._ev_pos_open, config, label='pos:open')
            for index, hour in enumerate(hours):
                lines = menus[kind][index % len(menus[kind])]
                customer, payment = self._pos_customer(index)
                self._at(offset, hour, self._ev_pos_order, config, lines, customer, payment, label='pos:order')
            self._at(offset, hours[-1] + 0.4, self._ev_pos_close, config, label='pos:close')
        # Los socios pagan sus consumos cargados a la cuenta.
        self._at(-5, 10.0, self._ev_pay_pos_debt, 'bruno', 'cashier', label='pos:pay_debt')
        self._at(-1, 19.0, self._ev_pay_pos_debt, 'ana', 'portal', label='pos:pay_debt')

    def _pos_customer(self, index):
        """Cliente y medio de pago de la orden ``index``: mostrador, socio con descuento o cargo a cuenta."""
        cycle = [(None, 'cash'), ('ana', 'member'), (None, 'qr'), ('bruno', 'cash'), (None, 'cash'),
                 ('nicolas', 'member'), ('gabriela', 'qr'), (None, 'qr'), ('bruno', 'member'), ('karen', 'cash')]
        return cycle[index % len(cycle)]

    def _ev_pos_open(self, config):
        config = config.with_user(self._as('waiter'))
        if not config.current_session_id:
            config.open_ui()
            config.current_session_id.set_opening_control(0, None)

    def _ev_pos_order(self, config, lines, customer, payment):
        """Cobro de una orden en la interfaz del POS (misma llamada ``sync_from_ui``)."""
        waiter = self._as('waiter')
        session = config.current_session_id
        if not session:
            raise UserError('Sesión cerrada')
        partner = self.partners.get(customer) if customer else self.env['res.partner']
        currency = session.currency_id
        pricelist = partner.property_product_pricelist if partner and \
            partner.property_product_pricelist in config.available_pricelist_ids else config.pricelist_id
        order_lines, total, untaxed = [], 0.0, 0.0
        for name, qty in lines:
            product = self.pos_products[name]
            price = pricelist._get_product_price(product, qty) if pricelist else product.lst_price
            taxes = product.taxes_id.filtered(lambda t: t.company_id == self.company)
            amounts = taxes.compute_all(price, currency, qty, product=product, partner=partner)
            total += amounts['total_included']
            untaxed += amounts['total_excluded']
            order_lines.append(Command.create({
                'product_id': product.id, 'qty': qty, 'price_unit': price, 'discount': 0.0,
                'price_subtotal': amounts['total_excluded'], 'price_subtotal_incl': amounts['total_included'],
                'tax_ids': [Command.set(taxes.ids)],
            }))
        total = currency.round(total)
        methods = config.payment_method_ids
        method = {
            'cash': methods.filtered('is_cash_count')[:1],
            'qr': self._ref('spa_pos.pm_qr'),
            'member': self._ref('spa_pos.pm_member_account'),
        }[payment]
        now = fields.Datetime.to_string(fields.Datetime.now())
        values = {
            'uuid': str(uuid.uuid4()),
            'session_id': session.id,
            'user_id': waiter.id,
            'partner_id': partner.id if partner else False,
            'pricelist_id': pricelist.id if pricelist else False,
            'fiscal_position_id': False,
            'date_order': now,
            'lines': order_lines,
            'payment_ids': [Command.create({'amount': total, 'name': now, 'payment_method_id': method.id})],
            'amount_total': total,
            'amount_tax': total - untaxed,
            'amount_paid': total,
            'amount_return': 0.0,
            'to_invoice': False,
            'last_order_preparation_change': '{}',
        }
        # Sin PDF al facturar el cargo a cuenta: se genera al imprimir o enviar la factura.
        self.env['pos.order'].with_user(waiter).with_context(generate_pdf=False).sync_from_ui([values])

    def _ev_pos_close(self, config):
        session = config.current_session_id.with_user(self._as('waiter'))
        cash = session.order_ids.payment_ids.filtered(lambda p: p.payment_method_id.is_cash_count)
        session.post_closing_cash_details(sum(cash.mapped('amount')))
        result = session.close_session_from_ui()
        if not result.get('successful'):
            raise UserError('No se pudo cerrar la sesión del POS: %s' % result)

    def _ev_pay_pos_debt(self, key, channel):
        spec = self.members[key]
        membership = spec['membership']
        invoices = self.env['account.move'].search([
            ('partner_id', '=', membership.partner_id.id), ('spa_invoice_kind', '=', 'pos'),
            ('state', '=', 'posted'), ('amount_residual', '>', 0)], order='invoice_date, id')
        for invoice in invoices[:1] if channel == 'portal' else invoices:
            if channel == 'portal':
                self._portal_payment(invoice, self.portal[key], invoice.amount_residual)
                continue
            request = self.env['spa.payment.request'].with_user(self._as('cashier')).create({
                'partner_id': invoice.partner_id.id, 'membership_id': membership.id, 'invoice_id': invoice.id,
                'amount': invoice.amount_residual, 'method': 'qr', 'reference': self._reference('qr')})
            request.with_user(self._as('cashier')).action_validate()

    # ==================================================================
    # 8. Compras (con factura SIAT y sin factura con retención)
    # ==================================================================
    def _plan_purchases(self):
        self._at(-39, 9.0, self._ev_vendors, label='buy:vendors')
        self._at(-38, 10.0, self._ev_purchase_order, label='buy:po')
        bills = [
            # (día, proveedor, cuenta, concepto, importe, número, tipo, área, pagar en días)
            (-33, 'food', 'l10n_bo_spa_51011', 'Carnes, verduras y bebidas para el restaurante', 2150.0, 3311,
             'siat_online', 'l10n_bo_spa.analytic_area_restaurante', 8),
            (-31, 'power', 'l10n_bo_spa_5121', 'Energía eléctrica del mes (ficticia)', 3480.0, 88121,
             'siat_online', None, 11),
            (-29, 'water', 'l10n_bo_spa_5122', 'Agua potable del mes (ficticia)', 1210.0, 45210, 'siat_online', None,
             19),
            (-18, 'spa_supplies', 'l10n_bo_spa_5117', 'Aceites esenciales y cremas de masaje', 890.0, 1544,
             'dosificacion', None, None),
            (-12, 'laundry', 'l10n_bo_spa_5119', 'Lavado de toallas y batas', 640.0, 2207, 'siat_online',
             'l10n_bo_spa.analytic_area_spa', None),
        ]
        for offset, vendor, account, label, amount, number, doc_type, area, pay_after in bills:
            bill = {'vendor': vendor, 'account': account, 'label': label, 'amount': amount, 'number': number,
                    'doc_type': doc_type, 'area': area}
            self._at(offset, 11.0, self._ev_vendor_bill, bill, label='buy:bill')
            if pay_after:
                self._at(offset + pay_after, 15.0, self._ev_pay_bill, bill, label='buy:pay')
        self._at(-16, 16.0, self._ev_bill_without_invoice, 'plumber', 'l10n_bo_spa_5124',
                 'Reparación de fuga en la sala de máquinas', 1000.0, 'supplier_bears', 'eventual', label='buy:noinv')
        self._at(-7, 12.0, self._ev_bill_without_invoice, 'designer', 'l10n_bo_spa_52061',
                 'Diseño de piezas para redes sociales', 1200.0, 'company_bears', 'services', label='buy:noinv')

    def _ev_vendors(self):
        Partner = self.env['res.partner'].with_user(self._as('owner'))  # datos maestros: el gerente
        for index, (key, (name, nit)) in enumerate(sorted(data.VENDORS.items())):
            self.vendors[key] = Partner.create({
                'name': name, 'vat': nit, 'l10n_bo_siat_id_type': '5', 'supplier_rank': 1, 'is_company': True,
                'phone': '+591 7000%04d' % (7001 + index), 'email': self._email(name),
                'city': 'La Paz', 'country_id': self._ref('base.bo').id}).sudo()
        for index, (key, name) in enumerate(sorted(data.FREELANCERS.items())):
            self.vendors[key] = Partner.create({
                'name': name, 'supplier_rank': 1, 'phone': '+591 7000%04d' % (7101 + index),
                'city': 'La Paz', 'country_id': self._ref('base.bo').id}).sudo()

    def _cuf(self, nit, number, day):
        emission = datetime.combine(day, datetime.min.time()) + timedelta(hours=10, minutes=15)
        return siat.encode_cuf(nit, emission, 0, 1, 1, 1, 1, number, 0, CUFD_CONTROL)

    def _ev_purchase_order(self):
        """Comprador pide cloro; el gerente aprueba (doble validación) y el contador registra la factura SIAT."""
        buyer, owner, accountant = self._as('buyer'), self._as('owner'), self._as('accountant')
        chart_tax = self._acc('l10n_bo_iva_13_purchase')
        product = self.env['product.product'].with_user(owner).create({
            'name': 'Demo – Cloro granulado 45 kg', 'type': 'consu', 'purchase_method': 'purchase',
            'categ_id': self._ref('l10n_bo_spa.categ_supplies_pool').id,
            'supplier_taxes_id': [Command.set(chart_tax.ids)], 'standard_price': 1130.0})
        self.company.with_user(owner).write({'po_double_validation': 'two_step', 'po_double_validation_amount': 1000.0})
        vendor = self.vendors['chemicals']
        order = self.env['purchase.order'].with_user(buyer).create({
            'partner_id': vendor.id,
            'order_line': [Command.create({'product_id': product.id, 'product_qty': 2, 'price_unit': 1130.0})]})
        order.button_confirm()
        order.with_user(owner).button_approve()
        self._receive(order)
        order.action_create_invoice()
        bill = order.sudo().invoice_ids[:1]
        today = self.tools.local_today()
        bill.with_user(accountant).write({
            'invoice_date': today, 'l10n_bo_invoice_number': '5120',
            'l10n_bo_cuf': self._cuf(vendor.vat, 5120, today)})
        bill.with_user(accountant).action_post()
        self.clock.schedule(fields.Datetime.now() + timedelta(days=7), 'buy:pay', self._ev_pay_moves, bill)

    def _receive(self, order):
        """Bodega recibe la mercadería (si la recepción se puede validar sin pasos extra)."""
        for picking in order.sudo().picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            try:
                with self.env.cr.savepoint():
                    for move in picking.move_ids:
                        move.quantity = move.product_uom_qty
                    picking.with_user(self._as('owner')).button_validate()
            except (UserError, ValidationError, AccessError) as error:
                _logger.info('spa_demo: recepción %s sin validar: %s', picking.name, error)

    def _ev_vendor_bill(self, bill):
        accountant = self._as('accountant')
        vendor = self.vendors[bill['vendor']]
        today = self.tools.local_today()
        line = {'name': bill['label'], 'account_id': self._acc(bill['account']).id, 'quantity': 1,
                'price_unit': bill['amount'], 'tax_ids': [Command.set(self._acc('l10n_bo_iva_13_purchase').ids)]}
        if bill['area']:
            line['analytic_distribution'] = {str(self._ref(bill['area']).id): 100}
        vals = {'move_type': 'in_invoice', 'partner_id': vendor.id, 'invoice_date': today,
                'l10n_bo_doc_type': bill['doc_type'], 'l10n_bo_invoice_number': str(bill['number']),
                'invoice_line_ids': [Command.create(line)]}
        if bill['doc_type'] == 'siat_online':
            vals['l10n_bo_cuf'] = self._cuf(vendor.vat, bill['number'], today)
        else:
            vals.update(l10n_bo_auth_number='29040011007', l10n_bo_control_code='7B-F3-48-A8')
        move = self.env['account.move'].with_user(accountant).create(vals)
        move.action_post()
        bill['move'] = move.sudo()

    def _ev_pay_bill(self, bill):
        if bill.get('move'):
            self._ev_pay_moves(bill['move'])

    def _ev_pay_moves(self, moves):
        moves = moves.filtered(lambda m: m.state == 'posted' and m.payment_state in ('not_paid', 'partial'))
        if moves:
            self.env['account.payment.register'].with_user(self._as('accountant')).with_context(
                active_model='account.move', active_ids=moves.ids).create(
                    {'journal_id': self.bank_journal.id})._create_payments()

    def _ev_bill_without_invoice(self, key, account, label, amount, mode, kind):
        """Compra sin factura: retención al proveedor (recibe el neto) o asumida por la empresa (grossing-up)."""
        accountant = self._as('accountant')
        move = self.env['account.move'].with_user(accountant).create({
            'move_type': 'in_invoice', 'partner_id': self.vendors[key].id,
            'invoice_date': self.tools.local_today(),
            'l10n_bo_doc_type': 'none', 'l10n_bo_withholding_mode': mode, 'l10n_bo_purchase_kind': kind,
            'invoice_line_ids': [Command.create({'name': label, 'account_id': self._acc(account).id,
                                                 'price_unit': amount, 'quantity': 1,
                                                 'tax_ids': [Command.clear()]})],
        })
        move.action_l10n_bo_apply_withholding()
        move.action_post()
        self._ev_pay_moves(move.sudo())

    # ==================================================================
    # 9. Fondo fijo (caja chica)
    # ==================================================================
    def _plan_petty_cash(self):
        self._at(-35, 9.5, self._ev_fund_open, label='petty:open')
        first = [(-32, 'bookstore', 'Papel, tóner y archivadores', 'l10n_bo_53008', 226.0, 901),
                 (-28, None, 'Escoba, baldes y trapeadores (mercado)', 'l10n_bo_spa_5118', 150.0, None),
                 (-24, 'bookstore', 'Detergente y papel higiénico', 'l10n_bo_spa_5118', 113.0, 917)]
        second = [(-12, None, 'Flores para la recepción (mercado)', 'l10n_bo_spa_52062', 80.0, None),
                  (-8, 'bookstore', 'Bolígrafos y fichas de registro', 'l10n_bo_53008', 67.8, 958),
                  (-4, None, 'Hielo y limones para la cafetería (mercado)', 'l10n_bo_spa_5118', 45.0, None)]
        for offset, vendor, label, account, amount, number in first + second:
            self._at(offset, 13.0, self._ev_voucher, vendor, label, account, amount, number, label='petty:voucher')
        self._at(-21, 17.0, self._ev_fund_report, label='petty:report')
        self._at(-20, 10.0, self._ev_fund_approve, label='petty:approve')
        self._at(-1, 18.0, self._ev_fund_report, label='petty:report')

    def _ev_fund_open(self):
        fund = self.env['l10n_bo.petty.cash.fund'].with_user(self._as('accountant')).create({
            'name': 'Demo – Caja chica Recepción', 'custodian_id': self._as('custodian').id, 'amount_fixed': 1500.0,
            'max_expense': 1200.0, 'analytic_account_id': self._ref('l10n_bo_spa.analytic_area_administracion').id,
            'bank_journal_id': self.bank_journal.id})
        fund.action_open()
        self.fund = fund.sudo()

    def _ev_voucher(self, vendor_key, label, account, amount, number):
        values = {'fund_id': self.fund.id, 'description': label, 'account_id': self._acc(account).id,
                  'amount': amount}
        values.update(self._receipt_vals(amount, 'CAJA-%s' % (number or self.rng.randint(100, 999))))
        if vendor_key:
            vendor = self.vendors[vendor_key]
            values.update(partner_id=vendor.id, l10n_bo_doc_type='siat_online', l10n_bo_invoice_number=str(number),
                          l10n_bo_cuf=self._cuf(vendor.vat, number, self.tools.local_today()))
        else:
            values.update(supplier_name='Demo – Vendedora del mercado (sin factura)', l10n_bo_doc_type='none',
                          l10n_bo_withholding_mode='supplier_bears', l10n_bo_purchase_kind='goods')
        self.env['l10n_bo.petty.cash.voucher'].with_user(self._as('custodian')).create(values)

    def _ev_fund_report(self):
        custodian = self._as('custodian')
        Voucher = self.env['l10n_bo.petty.cash.voucher'].with_user(custodian)
        pending = Voucher.search([('fund_id', '=', self.fund.id), ('state', '=', 'draft')])
        counted = self.fund.amount_fixed - sum(pending.mapped('amount_paid'))
        report = self.env['l10n_bo.petty.cash.report'].with_user(custodian).create({
            'fund_id': self.fund.id, 'cash_counted': counted})
        report.action_submit()
        self.fund_report = report.sudo()

    def _ev_fund_approve(self):
        self.fund_report.with_user(self._as('accountant')).action_approve()

    # ==================================================================
    # 10. Alquiler de ambientes y clases
    # ==================================================================
    def _plan_rentals(self):
        event_day = -14
        self._at(event_day - 10, 10.0, self._ev_rental_quote, 'birthday', event_day, 10.0, 13.0, 'exclusive', 0, 500.0,
                 'Demo – Cumpleaños de Mateo', label='rent:quote')
        self._at(event_day - 8, 9.5, self._ev_rental_confirm, 'birthday', label='rent:confirm')
        self._at(event_day - 6, 11.0, self._ev_rental_pay, 'birthday', 'deposit', 500.0, 'cash', label='rent:pay')
        self._at(event_day - 6, 11.1, self._ev_rental_pay, 'birthday', 'invoice', 0.5, 'qr', label='rent:pay')
        self._at(event_day + 1, 10.0, self._ev_rental_pay, 'birthday', 'invoice', 1.0, 'cash', label='rent:pay')
        self._at(event_day + 1, 10.2, self._ev_rental_refund, 'birthday', label='rent:refund')
        self._at(-3, 10.0, self._ev_rental_quote, 'club', 5, 16.0, 18.0, 'partial', 6, 300.0,
                 'Demo – Clínica de aquagym del Club Delfines', label='rent:quote')
        self._at(-2, 9.5, self._ev_rental_confirm, 'club', label='rent:confirm')

    def _ev_rental_quote(self, key, offset, hour_from, hour_to, mode, seats, deposit, event):
        name, phone, nit, doc_type = data.EVENT_CUSTOMERS[key]
        customer = self._partner(name, phone, vat=nit, doc_type=doc_type)
        rental = self.env['spa.rental'].with_user(self._as('reception')).create({
            'event_name': event, 'partner_id': customer.id, 'space_id': self.spaces['pool'].id,
            'start': self._utc(self._day(offset), hour_from), 'stop': self._utc(self._day(offset), hour_to),
            'mode': mode, 'seats': seats, 'deposit_amount': deposit, 'attendees': 25 if mode == 'exclusive' else 6,
            'note': 'Evento de demostración (ficticio).'})
        self.rentals[key] = rental.sudo()

    def _ev_rental_confirm(self, key):
        self.rentals[key].with_user(self._as('owner')).action_confirm()

    def _ev_rental_pay(self, key, kind, share, method):
        rental = self.rentals[key]
        cashier = self._as('cashier')
        action = rental.with_user(cashier).action_open_deposit_payment() if kind == 'deposit' else \
            rental.with_user(cashier).action_open_payment()
        context = {key_[len('default_'):]: value for key_, value in action['context'].items()
                   if key_.startswith('default_')}
        if kind == 'invoice':
            invoice = rental.invoice_id
            due = invoice.amount_residual if invoice.state == 'posted' else invoice.amount_total
            context['amount'] = invoice.currency_id.round(due * share) if share < 1 else due
        else:
            context['amount'] = share
        context.update(method=method, reference=self._reference(method))
        self.env['spa.rental.payment.wizard'].with_user(cashier).create(context).action_confirm()

    def _ev_rental_refund(self, key):
        rental = self.rentals[key]
        self.env['spa.rental.deposit.wizard'].with_user(self._as('cashier')).create({
            'rental_id': rental.id, 'operation': 'refund', 'amount': rental.deposit_balance,
            'method': 'cash'}).action_confirm()

    def _plan_classes(self):
        self._at(-21, 9.0, self._ev_class_activate, label='class:activate')
        self._at(-20, 10.0, self._ev_class_package, 0, label='class:package')
        self._at(-14, 10.0, self._ev_class_singles, 1, 3, label='class:single')
        self._at(-6, 10.0, self._ev_class_package, 2, label='class:package')

    def _ev_class_activate(self):
        template = self._ref('spa_rental.class_template_swim')
        template.with_user(self._as('owner')).write({
            'active': True, 'date_from': self.tools.local_today(),
            'name': 'Natación – lunes, miércoles y viernes 18:00 (demo)'})
        self.class_template = template

    def _student(self, index):
        name, phone = data.STUDENTS[index]
        return self._partner(name, phone)

    def _ev_class_package(self, index):
        reception, cashier = self._as('reception'), self._as('cashier')
        student = self._student(index)
        wizard = self.env['spa.class.package.wizard'].with_user(reception).create({
            'template_id': self.class_template.id, 'partner_id': student.id})
        wizard.action_confirm()
        enrollments = self.env['spa.class.enrollment'].search(
            [('partner_id', '=', student.id), ('state', '=', 'enrolled')], order='start')
        action = enrollments[:1].with_user(cashier).action_open_payment()
        context = {key[len('default_'):]: value for key, value in action['context'].items()
                   if key.startswith('default_')}
        context.update(method='qr', reference=self._reference('qr'))
        self.env['spa.rental.payment.wizard'].with_user(cashier).create(context).action_confirm()
        self._plan_class_attendance(enrollments)

    def _ev_class_singles(self, index, count):
        reception, cashier = self._as('reception'), self._as('cashier')
        student = self._student(index)
        sessions = self.class_template._spa_upcoming_sessions(count)
        enrollments = self.env['spa.class.enrollment']
        for session in sessions:
            enrollment = self.env['spa.class.enrollment'].with_user(reception).create({
                'session_id': session.id, 'partner_id': student.id, 'payment_mode': 'invoice'})
            enrollment.action_enroll()
            enrollments |= enrollment.sudo()
        first = enrollments[:1]
        action = first.with_user(cashier).action_open_payment()
        context = {key[len('default_'):]: value for key, value in action['context'].items()
                   if key.startswith('default_')}
        context.update(method='cash', reference=self._reference('cash'))
        self.env['spa.rental.payment.wizard'].with_user(cashier).create(context).action_confirm()
        self._plan_class_attendance(enrollments)

    def _plan_class_attendance(self, enrollments):
        for enrollment in enrollments:
            if self.rng.random() < 0.85:
                self.clock.schedule(enrollment.start - timedelta(minutes=self.rng.randint(5, 20)), 'class:checkin',
                                    self._ev_class_checkin, enrollment)

    def _ev_class_checkin(self, enrollment):
        if enrollment.state != 'enrolled' or enrollment.session_id.state != 'planned':
            return
        self.env['spa.access.log'].with_user(self._as('reception')).do_check_in(
            enrollment.space_id, partner=enrollment.partner_id)

    # ==================================================================
    # 11. Hoy
    # ==================================================================
    def _plan_today(self):
        now = self.real_now
        local = self.tools.to_local(now)
        hour = local.hour + local.minute / 60.0
        if 10.0 <= hour <= 19.0:
            # Personas dentro ahora (aforo en vivo del sauna).
            for key in ('elena', 'karen'):
                self.clock.schedule(now, 'visit:sauna_now', self._ev_sauna_now, key)

    def _ev_sauna_now(self, key):
        membership = self.members[key].get('membership')
        if membership:
            self.env['spa.access.log'].with_user(self._as('reception')).do_check_in(
                self.spaces['sauna'], token=membership.qr_token)

    # ==================================================================
    # 12. Cierre
    # ==================================================================
    def _finish(self):
        self.env['ir.config_parameter'].set_param(data.DEMO_PARAM, fields.Date.to_string(self.today))
        # Ningún correo real: los avisos internos de la demo quedan cancelados en la cola de salida.
        mails = self.env['mail.mail'].search([('state', 'in', ('outgoing', 'exception'))])
        if mails:
            mails.cancel()
        self.env.flush_all()
