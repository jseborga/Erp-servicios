# Part of ERP Servicios Spa. License LGPL-3.
"""Web del socio: planes públicos (/spa) y portal de la membresía (/my/spa).

Seguridad: los usuarios portal no tienen permisos sobre los modelos del spa.
Cada registro se lee con ``sudo()`` SOLO después de comprobar que pertenece a
la cuenta del usuario conectado (``commercial_partner_id``) y a la compañía del
sitio; si no, se responde 404. Los únicos datos que se leen con ``sudo()`` sin
dueño son los públicos por diseño: planes publicados y ofertas vigentes.
"""
import base64
import math
import re
from datetime import timedelta

from werkzeug.exceptions import NotFound
from werkzeug.urls import url_encode

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.http import request
from odoo.tools import format_date
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.portal.controllers.portal import CustomerPortal

from odoo.addons.spa_billing.models.account_move import PENDING_KINDS

from ..models.res_config_settings import DEFAULT_BOOKING_DAYS, DEFAULT_RECEIPT_MAX_MB

ACCESS_STATES = ('active', 'grace')
LIVE_STATES = ('active', 'grace', 'suspended')
OPEN_STATES = ('draft',) + LIVE_STATES
STATE_RANK = {'active': 0, 'grace': 0, 'suspended': 1, 'draft': 2, 'expired': 3}
STATE_BADGE = {'active': 'success', 'grace': 'warning', 'suspended': 'danger', 'draft': 'warning',
               'expired': 'secondary', 'cancelled': 'secondary'}
PORTAL_PAY_METHODS = ('qr', 'transfer')
PHONE_RE = re.compile(r'^\+?[\d\s\-().]{7,20}$')
MAX_NAME = 100


def parse_amount(text):
    """Monto escrito por el socio -> float. Acepta «890», «890,50», «1.234,50», «1,234.50» y «Bs 890».

    El último separador (punto o coma) es el decimal. Lanza ValueError si no es un número válido.
    """
    text = re.sub(r'[A-Za-z$]+\.?', '', text or '').replace(' ', '')
    if ',' in text and '.' in text:
        decimal = ',' if text.rfind(',') > text.rfind('.') else '.'
        text = text.replace('.' if decimal == ',' else ',', '').replace(',', '.')
    else:
        text = text.replace(',', '.')
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


class SpaPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Utilidades: dueño, compañía, formato
    # ------------------------------------------------------------------
    def _spa_commercial(self):
        return request.env.user.partner_id.commercial_partner_id

    def _spa_owner_domain(self):
        return [('partner_id', 'child_of', self._spa_commercial().id),
                ('company_id', '=', request.env.company.id)]

    def _spa_is_owner(self, record):
        return bool(record) and record.partner_id.commercial_partner_id == self._spa_commercial() \
            and record.company_id == request.env.company

    def _spa_get_owned(self, model, record_id):
        """Registro (sudo) de la cuenta del usuario conectado; 404 si no existe o es de otro socio."""
        record = request.env[model].sudo().browse(int(record_id)).exists()
        if not self._spa_is_owner(record):
            raise NotFound()
        return record

    def _spa_memberships(self):
        return request.env['spa.membership'].sudo().search(
            self._spa_owner_domain() + [('state', '!=', 'cancelled')])

    def _spa_current_membership(self):
        """Membresía a mostrar: la propia antes que la de la cuenta; vigente, suspendida, por pagar."""
        partner = request.env.user.partner_id
        return self._spa_memberships().sorted(lambda m: (
            m.partner_id != partner, STATE_RANK.get(m.state, 9),
            -(m.date_end.toordinal() if m.date_end else 0), -m.id))[:1]

    def _spa_payable_domain(self):
        """Lo que el socio puede pagar: facturas emitidas con saldo y cobros pendientes (borrador: la factura
        se emite al validar el pago). Los cargos del mes en curso se emiten al cerrar el mes."""
        return [('move_type', '=', 'out_invoice'), ('amount_residual', '>', 0), ('spa_invoice_kind', '!=', False),
                ('payment_state', 'not in', ('paid', 'reversed', 'in_payment')),
                '|', ('state', '=', 'posted'), '&', ('state', '=', 'draft'), ('spa_invoice_kind', 'in', list(PENDING_KINDS))]

    def _spa_open_invoices(self):
        return request.env['account.move'].sudo().search(
            self._spa_owner_domain() + self._spa_payable_domain(), order='invoice_date_due, id')

    def _spa_param(self, key, default, cast):
        value = request.env['ir.config_parameter'].sudo().get_param(key)
        try:
            value = cast(value) if value not in (None, False, '') else default
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _spa_booking_days(self):
        return min(self._spa_param('spa_portal.booking_days', DEFAULT_BOOKING_DAYS, int), 60)

    def _spa_today(self):
        return request.env['spa.tools'].local_today()

    def _spa_clean_salesperson(self, moves):
        """Una factura generada desde la web no tiene vendedor: no dejar al usuario portal como tal."""
        moves = moves.filtered(lambda m: m.invoice_user_id and not m.invoice_user_id._is_internal())
        if moves:
            moves.with_context(tracking_disable=True).write({'invoice_user_id': False})

    def _spa_helpers(self):
        env = request.env
        tools = env['spa.tools']
        company = env.company

        def money(amount, currency=None):
            return (currency or company.currency_id).format(amount or 0.0)

        def fmt_date(value, pattern=False):
            return format_date(env, value, date_format=pattern) if value else ''

        def fmt_dt(value):
            if not value:
                return ''
            local = tools.to_local(value)
            return '%s · %s' % (format_date(env, local.date(), date_format='EEE d MMM'), local.strftime('%H:%M'))

        return {'money': money, 'fmt_date': fmt_date, 'fmt_dt': fmt_dt}

    def _spa_flash(self, code):
        _ = request.env._
        messages = {
            'booked': ('success', _('Reserva confirmada. ¡Te esperamos!')),
            'cancelled': ('success', _('Reserva cancelada. La sesión volvió a tu saldo.')),
            'late_none': ('info', _('Cancelaste fuera de plazo, pero tu plan no aplica penalidad: la sesión volvió a tu saldo.')),
            'late_lose_session': ('warning', _('Cancelaste fuera de plazo: según la política de tu plan, la sesión se descuenta de tu saldo.')),
            'late_fee': ('warning', _('Cancelaste fuera de plazo: según la política de tu plan, se carga la penalidad a tu cuenta.')),
            'cancel_denied': ('warning', _('Esta reserva ya no se puede cancelar desde la web. Comunícate con recepción.')),
            'guest_free_pass': ('success', _('Invitado registrado con free pass.')),
            'guest_fee': ('warning', _('Invitado registrado. Ya usaste tus free pass del mes: la tarifa de invitado se carga a tu cuenta.')),
            'received': ('success', _('Recibimos tu comprobante; caja lo validará. Te avisaremos cuando quede confirmado.')),
            'existing': ('info', _('Ya tienes una membresía de este plan: aquí está su estado.')),
            'paid': ('info', _('Esta factura ya no tiene saldo pendiente.')),
            'nothing_due': ('info', _('No tienes pagos pendientes.')),
            'no_membership': ('info', _('Primero elige un plan para hacerte socio.')),
            'inactive': ('warning', _('Tu membresía no está activa. Paga tu saldo pendiente para volver a reservar.')),
        }
        return messages.get(code)

    def _spa_member_values(self, page, membership, msg=None, error=None):
        values = self._prepare_portal_layout_values()
        values.update(self._spa_helpers())
        values.update({
            'page_name': page,
            'membership': membership,
            'flash': self._spa_flash(msg),
            'error': error,
            'currency': request.env.company.currency_id,
        })
        return values

    # ------------------------------------------------------------------
    # Portada del portal (/my)
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'spa_membership_count' in counters:
            values['spa_membership_count'] = request.env['spa.membership'].sudo().search_count(
                self._spa_owner_domain() + [('state', '!=', 'cancelled')])
        return values

    # ------------------------------------------------------------------
    # Público: planes
    # ------------------------------------------------------------------
    def _spa_published_plans(self):
        # Catálogo público por diseño: solo planes publicados de la compañía del sitio.
        return request.env['spa.plan'].sudo().search([
            ('website_published', '=', True), ('company_id', '=', request.env.company.id)])

    def _spa_get_published_plan(self, plan_id):
        plan = request.env['spa.plan'].sudo().browse(int(plan_id)).exists()
        if not plan or not plan.active or not plan.website_published or plan.company_id != request.env.company:
            raise NotFound()
        return plan

    def _spa_plan_lines(self, plan):
        return [{
            'name': line.service_id.name,
            'summary': line._summary(),
            'guests': line.guests_per_booking if line.service_id.guest_allowed else 0,
        } for line in plan.line_ids]

    def _spa_offer_partner(self):
        return request.env.user.partner_id.sudo()

    def _spa_plan_options(self, plan):
        """Opciones de compra: cada duración y cada oferta vigente aplicable a esa duración."""
        Offer = request.env['spa.payment.offer'].sudo()
        partner = self._spa_offer_partner()
        helpers = self._spa_helpers()
        money, fmt_date = helpers['money'], helpers['fmt_date']
        _ = request.env._
        options = []
        for period in plan.period_ids.filtered('active'):
            note = _('Equivale a %s al mes', money(period.monthly_price, plan.currency_id)) if period.months > 1 else ''
            options.append({'key': '%s:0' % period.id, 'period': period, 'offer': Offer, 'label': period.name,
                            'price': period.price, 'note': note})
            for offer in Offer._applicable_offers(period, partner):
                until = _('vigente hasta el %s', fmt_date(offer.date_to))
                if offer.offer_type == 'discount':
                    price = period.price * (1 - offer.discount_percent / 100.0)
                    note = '%s · %s' % (_('Ahorras %s', money(period.price - price, plan.currency_id)), until)
                else:
                    price = period.price
                    note = '%s · %s' % (_('%(n)s cuotas de %(amount)s', n=offer.installments,
                                          amount=money(period.price / offer.installments, plan.currency_id)), until)
                options.append({'key': '%s:%s' % (period.id, offer.id), 'period': period, 'offer': offer,
                                'label': '%s · %s' % (period.name, offer.name), 'price': price, 'note': note})
        return options

    @http.route('/spa', type='http', auth='public', website=True, sitemap=True)
    def spa_plans(self, **kw):
        Offer = request.env['spa.payment.offer'].sudo()
        partner = self._spa_offer_partner()
        mine = self._spa_current_membership().plan_id if not request.env.user._is_public() else False
        cards = []
        for plan in self._spa_published_plans():
            periods = plan.period_ids.filtered('active')
            offers = Offer.browse()
            for period in periods:
                offers |= Offer._applicable_offers(period, partner)
            cards.append({
                'plan': plan,
                'periods': periods,
                'offers': offers,
                'lines': self._spa_plan_lines(plan),
                'is_mine': bool(mine) and mine == plan,
            })
        values = self._spa_helpers()
        values.update({'cards': cards, 'currency': request.env.company.currency_id})
        return request.render('spa_portal.spa_plans', values)

    def _spa_existing_for_plan(self, plan):
        return self._spa_memberships().filtered(
            lambda m: m.plan_id == plan and m.state in OPEN_STATES).sorted(lambda m: STATE_RANK.get(m.state, 9))[:1]

    def _spa_other_live(self, plan):
        # La vigente antes que la suspendida o la que está por pagar.
        return self._spa_memberships().filtered(
            lambda m: m.plan_id != plan and m.state in OPEN_STATES).sorted(lambda m: STATE_RANK.get(m.state, 9))[:1]

    def _spa_render_plan(self, plan, option=None, error=None, phone=None):
        is_public = request.env.user._is_public()
        options = self._spa_plan_options(plan)
        keys = [opt['key'] for opt in options]
        redirect = '/spa/plan/%s' % plan.id + ('?%s' % url_encode({'option': option}) if option in keys else '')
        values = self._spa_helpers()
        values.update({
            'plan': plan,
            'lines': self._spa_plan_lines(plan),
            'options': options,
            'selected': option if option in keys else (keys[0] if keys else False),
            'is_public': is_public,
            'existing': False if is_public else self._spa_existing_for_plan(plan),
            'other': False if is_public else self._spa_other_live(plan),
            'need_phone': not is_public and not request.env.user.partner_id.phone,
            'phone': phone or '',
            'error': error,
            'login_url': '/web/login?%s' % url_encode({'redirect': redirect}),
            'signup_url': '/web/signup?%s' % url_encode({'redirect': redirect}),
            'signup_enabled': request.env['res.users'].sudo()._get_signup_invitation_scope() == 'b2c',
            'currency': plan.currency_id,
        })
        return request.render('spa_portal.spa_plan_detail', values)

    @http.route('/spa/plan/<int:plan_id>', type='http', auth='public', website=True, sitemap=False)
    def spa_plan(self, plan_id, option=None, **kw):
        plan = self._spa_get_published_plan(plan_id)
        return self._spa_render_plan(plan, option=option)

    def _spa_redirect_existing(self, membership):
        """Lleva al socio a su membresía (o a pagarla) en lugar de duplicarla."""
        invoice = membership._open_period_invoice().filtered(lambda m: m.amount_residual > 0)[:1]
        if membership.state == 'draft' and not invoice:
            invoice = membership.with_context(mail_create_nosubscribe=True).action_create_invoice()
            self._spa_clean_salesperson(invoice)
        if invoice:
            return request.redirect('/my/spa/pay/%s?%s' % (invoice.id, url_encode({'msg': 'existing'})))
        return request.redirect('/my/spa?msg=existing')

    @http.route('/spa/plan/<int:plan_id>/subscribe', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def spa_plan_subscribe(self, plan_id, option=None, phone=None, **kw):
        plan = self._spa_get_published_plan(plan_id)
        _ = request.env._
        if request.env.user._is_public():
            target = '/spa/plan/%s?%s' % (plan.id, url_encode({'option': option or ''}))
            return request.redirect('/web/login?%s' % url_encode({'redirect': target}))
        existing = self._spa_existing_for_plan(plan)
        if existing:
            return self._spa_redirect_existing(existing)
        other = self._spa_other_live(plan)
        if other:
            return self._spa_render_plan(plan, option=option, error=_(
                'Ya tienes la membresía %(plan)s (%(state)s). Para cambiar de plan comunícate con recepción: '
                'te ayudamos con el prorrateo.', plan=other.plan_id.name,
                state=dict(other._fields['state']._description_selection(request.env))[other.state]))
        # Duración y oferta elegidas
        period, offer = self._spa_parse_option(plan, option)
        if not period:
            return self._spa_render_plan(plan, error=_('Elige una duración del plan.'))
        if offer is None:
            return self._spa_render_plan(plan, option='%s:0' % period.id,
                                         error=_('Esa oferta ya no está vigente. Elige otra opción.'))
        partner = request.env.user.partner_id
        phone = (phone or '').strip()
        if not partner.phone:
            if not phone or not PHONE_RE.match(phone):
                return self._spa_render_plan(plan, option=option, phone=phone, error=_(
                    'Escribe tu número de celular (WhatsApp) para enviarte avisos de reservas y pagos.'))
        try:
            with request.env.cr.savepoint():
                if phone and not partner.phone:
                    partner.sudo().phone = phone
                membership = request.env['spa.membership'].sudo().with_context(mail_create_nosubscribe=True).create({
                    'partner_id': partner.id,
                    'plan_id': plan.id,
                    'period_id': period.id,
                    'company_id': plan.company_id.id,
                })
                invoice = membership.action_create_invoice(offer=offer or None)
                self._spa_clean_salesperson(invoice)
        except UserError as error:
            return self._spa_render_plan(plan, option=option, phone=phone, error=str(error))
        return request.redirect('/my/spa/pay/%s' % invoice.id)

    def _spa_parse_option(self, plan, option):
        """'<period_id>:<offer_id>' -> (period, offer). offer=None si la oferta no aplica."""
        Offer = request.env['spa.payment.offer'].sudo()
        try:
            period_id, offer_id = (int(part) for part in (option or '').split(':'))
        except ValueError:
            return None, Offer
        period = plan.period_ids.filtered(lambda p: p.id == period_id and p.active)
        if not period:
            return None, Offer
        if not offer_id:
            return period, Offer
        offer = Offer.browse(offer_id).exists()
        if not offer or offer not in Offer._applicable_offers(period, self._spa_offer_partner()):
            return period, None
        return period, offer

    # ------------------------------------------------------------------
    # Portal: mi membresía
    # ------------------------------------------------------------------
    def _spa_policy_text(self, policy):
        if not policy:
            return ''
        _ = request.env._
        hours = '%g' % policy.free_cancel_hours
        late = dict(policy._fields['late_cancel_action']._description_selection(request.env))[policy.late_cancel_action]
        text = _('Política «%(name)s»: cancelación sin costo hasta %(hours)s h antes. Después: %(late)s.',
                 name=policy.name, hours=hours, late=late.lower())
        if policy.max_cancellations_month:
            text += ' ' + _('Máximo %s cancelaciones sin costo al mes.', policy.max_cancellations_month)
        return text

    def _spa_cancel_info(self, booking):
        """(tardía, texto de la consecuencia) si el socio cancela ahora."""
        _ = request.env._
        policy = booking._policy()
        if not policy or not booking._is_late_cancel():
            return False, _('Cancelación sin costo: la sesión vuelve a tu saldo.')
        action = policy.late_cancel_action
        if action == 'none':
            return True, _('Estás fuera de plazo, pero tu plan no aplica penalidad: la sesión vuelve a tu saldo.')
        if action == 'fee':
            product = policy.late_cancel_fee_product_id
            amount = self._spa_helpers()['money'](product.lst_price) if product else ''
            return True, _('Estás fuera de plazo: según tu plan se cobra una penalidad %s.', amount)
        return True, _('Estás fuera de plazo: según tu plan pierdes la sesión.')

    def _spa_can_cancel(self, booking):
        return booking.state == 'confirmed' and booking.payment_mode == 'membership' \
            and booking.start > fields.Datetime.now()

    def _spa_home_values(self, msg=None, error=None):
        membership = self._spa_current_membership()
        values = self._spa_member_values('spa', membership, msg=msg, error=error)
        if not membership:
            return values
        _ = request.env._
        now = fields.Datetime.now()
        state_label = dict(membership._fields['state']._description_selection(request.env))[membership.state]
        pending = request.env['spa.payment.request'].sudo().search(
            self._spa_owner_domain() + [('state', '=', 'pending')])
        if membership.state == 'draft':
            state_label = _('Pago en validación') if pending else _('Pendiente de pago')
        balances = []
        if membership.state in ACCESS_STATES:
            for item in membership._balance_summary():
                available = item['available'] or 0
                if item['unlimited']:
                    label, pct = _('Ilimitado'), 100
                else:
                    label = _('%(left)s de %(total)s', left=item['remaining'], total=available)
                    pct = int(round(100.0 * max(item['remaining'], 0) / available)) if available else 0
                balances.append(dict(item, label=label, pct=pct))
        bookings = []
        for booking in request.env['spa.booking'].sudo().search(self._spa_owner_domain() + [
                ('state', 'in', ('confirmed', 'checked_in')), ('stop', '>=', now)], order='start', limit=20):
            can_cancel = self._spa_can_cancel(booking)
            late, consequence = self._spa_cancel_info(booking) if can_cancel else (False, '')
            bookings.append({'record': booking, 'can_cancel': can_cancel, 'late': late,
                             'consequence': consequence, 'guests': booking._guest_count()})
        quota = membership.plan_id.guest_quota
        used = membership.guests_this_month
        invoices = self._spa_open_invoices()
        token = membership.qr_token
        values.update({
            'state_label': state_label,
            'state_badge': STATE_BADGE.get(membership.state, 'secondary'),
            'show_qr': membership.state in ACCESS_STATES and bool(token),
            'qr_url': '/report/barcode/QR/%s?%s' % (token, url_encode({'width': 300, 'height': 300})),
            'balances': balances,
            'month_label': format_date(request.env, self._spa_today(), date_format='MMMM yyyy'),
            'guest_quota': quota,
            'guest_used': used,
            'guest_pct': int(round(100.0 * max(quota - used, 0) / quota)) if quota else 0,
            'bookings': bookings,
            'policy_text': self._spa_policy_text(membership.plan_id.cancel_policy_id),
            'open_invoices': invoices,
            'amount_due': sum(invoices.mapped('amount_residual')),
            'access_until': membership._spa_access_until() if membership.state == 'grace' else False,
            'payment_requests': request.env['spa.payment.request'].sudo().search(
                self._spa_owner_domain(), limit=10),
        })
        return values

    @http.route('/my/spa', type='http', auth='user', website=True, sitemap=False)
    def spa_my_home(self, msg=None, **kw):
        return request.render('spa_portal.spa_my_home', self._spa_home_values(msg=msg))

    @http.route('/my/spa/booking/<int:booking_id>/cancel', type='http', auth='user', website=True,
                methods=['POST'], sitemap=False)
    def spa_booking_cancel(self, booking_id, **kw):
        booking = self._spa_get_owned('spa.booking', booking_id)
        if not self._spa_can_cancel(booking):
            return request.redirect('/my/spa?msg=cancel_denied')
        try:
            with request.env.cr.savepoint():
                late_action = booking._policy().late_cancel_action if booking._is_late_cancel() else False
                booking.action_cancel()
        except UserError as error:
            return request.render('spa_portal.spa_my_home', self._spa_home_values(error=str(error)))
        return request.redirect('/my/spa?msg=%s' % ('late_%s' % late_action if late_action else 'cancelled'))

    # ------------------------------------------------------------------
    # Portal: reservar
    # ------------------------------------------------------------------
    def _spa_blocked_reason(self, membership):
        _ = request.env._
        if not membership:
            return _('Aún no tienes una membresía. Elige un plan para empezar.')
        if membership.state == 'expired':
            return _('Tu membresía venció. Elige un plan para volver a ser socio.')
        if membership.state not in ACCESS_STATES:
            return _('Tu membresía no está activa (%s). Paga tu saldo pendiente para reservar.',
                     dict(membership._fields['state']._description_selection(request.env))[membership.state])
        return False

    def _spa_slots(self, service, day, membership, guests):
        """Franjas del día con ocupación (pct), valor del formulario y leyenda para el socio."""
        _ = request.env._
        slots = []
        for slot in service._get_slots(day, seats=service.seats_per_booking + guests, membership=membership,
                                       guests=guests):
            taken = slot['capacity'] - slot['free']
            slots.append(dict(
                slot,
                value=fields.Datetime.to_string(slot['start']),
                pct=int(round(100.0 * taken / slot['capacity'])) if slot['capacity'] else 100,
                caption=slot['reason'] if not slot['available'] else _('%(free)s de %(cap)s libres',
                                                                       free=slot['free'], cap=slot['capacity']),
            ))
        return slots

    def _spa_access_hint(self, service, membership, slots, guests):
        """Si no hay horarios libres, el motivo concreto de la membresía (saldo, tope semanal, vigencia...).

        ``_get_slots`` solo indica «no incluido en su plan»; aquí se pide el detalle a la regla del núcleo
        con la primera franja futura.
        """
        if not slots or any(slot['available'] for slot in slots):
            return False
        now = fields.Datetime.now()
        slot = next((s for s in slots if s['start'] > now), None)
        if not slot:
            return False
        try:
            membership._spa_check_access(service, slot['start'], slot['stop'], guests=guests)
        except UserError as error:
            return str(error)
        return False

    def _spa_book_values(self, membership, service_id=None, day=None, guests=0, error=None, form=None):
        _ = request.env._
        values = self._spa_member_values('spa_book', membership, error=error)
        values.update({'blocked': self._spa_blocked_reason(membership), 'services': [], 'form': form or {}})
        if values['blocked']:
            return values
        plan = membership.plan_id
        lines = plan.line_ids.filtered(lambda l: l.service_id.active and l.service_id.space_id.access_mode == 'slot'
                                       and l.service_id.space_id.state == 'active')
        free_lines = plan.line_ids.filtered(lambda l: l.service_id.active and l.service_id.space_id.access_mode == 'free')
        services = lines.service_id
        values['free_spaces'] = [{'service': line.service_id, 'space': line.service_id.space_id}
                                 for line in free_lines]
        if not services:
            return values
        try:
            service = services.filtered(lambda s: s.id == int(service_id or 0))[:1] or services[:1]
        except (TypeError, ValueError):
            service = services[:1]
        line = plan._line_for_service(service)
        max_guests = line.guests_per_booking if service.guest_allowed else 0
        try:
            guests = min(max(int(guests or 0), 0), max_guests)
        except (TypeError, ValueError):
            guests = 0
        today = self._spa_today()
        # Solo días dentro de la vigencia de la membresía (incluida la gracia).
        days = [d for d in (today + timedelta(days=index) for index in range(self._spa_booking_days()))
                if membership._covers_date(d)] or [today]
        requested = day
        try:
            day = fields.Date.to_date(day) if day else days[0]
        except (TypeError, ValueError):
            day = days[0]
        if day not in days:
            day = days[0]
        slots = self._spa_slots(service, day, membership, guests)
        if not requested and not any(slot['available'] for slot in slots):
            # Sin fecha elegida: saltar al primer día (de la próxima semana) con horarios libres.
            for candidate in days[1:7]:
                if not service.space_id._is_open_on(candidate):
                    continue
                candidate_slots = self._spa_slots(service, candidate, membership, guests)
                if any(slot['available'] for slot in candidate_slots):
                    day, slots = candidate, candidate_slots
                    break
        entitlement = membership._entitlement_for(service, day)
        if line.unlimited:
            balance = _('Ilimitado · %s', line._summary())
        else:
            balance = _('Te quedan %(left)s de %(total)s en el mes · %(rule)s', left=entitlement.remaining,
                        total=entitlement.granted + entitlement.carried_in, rule=line._summary())

        def book_url(**changes):
            params = {'service_id': service.id, 'day': fields.Date.to_string(day), 'guests': guests}
            params.update(changes)
            return '/my/spa/book?%s' % url_encode(params)

        values.update({
            'services': services,
            'service': service,
            'line': line,
            'balance': balance,
            'days': [{'date': d, 'value': fields.Date.to_string(d), 'weekday': format_date(request.env, d, date_format='EEE'),
                      'number': d.day, 'open': service.space_id._is_open_on(d)} for d in days],
            'day': day,
            'day_value': fields.Date.to_string(day),
            'day_label': format_date(request.env, day, date_format="EEEE d 'de' MMMM"),
            'guests': guests,
            'guest_choices': list(range(max_guests + 1)),
            'guest_rows': list(range(guests)),
            'slots': slots,
            'any_available': any(slot['available'] for slot in slots),
            'access_hint': self._spa_access_hint(service, membership, slots, guests),
            'book_url': book_url,
            'policy_text': self._spa_policy_text(plan.cancel_policy_id),
        })
        return values

    @http.route('/my/spa/book', type='http', auth='user', website=True, sitemap=False)
    def spa_book(self, service_id=None, day=None, guests=0, **kw):
        membership = self._spa_current_membership()
        return request.render('spa_portal.spa_my_book', self._spa_book_values(membership, service_id, day, guests))

    @http.route('/my/spa/book/confirm', type='http', auth='user', website=True, methods=['POST'], sitemap=False)
    def spa_book_confirm(self, service_id=None, day=None, guests=0, start=None, **kw):
        _ = request.env._
        membership = self._spa_current_membership()
        values = self._spa_book_values(membership, service_id, day, guests, form=kw)

        def fail(message):
            values['error'] = message
            values['form'] = dict(kw, start=start)
            return request.render('spa_portal.spa_my_book', values)

        if values['blocked']:
            return fail(values['blocked'])
        service = values.get('service')
        if not service or str(service.id) != str(service_id):
            return fail(_('Elige un servicio incluido en tu plan.'))
        if str(values['guests']) != str(guests or 0):
            return fail(_('Tu plan permite hasta %s invitado(s) en este servicio.', len(values['guest_choices']) - 1))
        slot = next((s for s in values['slots'] if s['value'] == start), None)
        if not slot:
            return fail(_('Elige un horario de la lista.'))
        if not slot['available']:
            return fail(_('El horario %(slot)s ya no está disponible (%(reason)s). Elige otro.',
                          slot=slot['label'], reason=slot['reason']))
        guest_vals = []
        for index in values['guest_rows']:
            name = (kw.get('guest_name_%s' % index) or '').strip()[:MAX_NAME]
            phone = (kw.get('guest_phone_%s' % index) or '').strip()
            if not name:
                return fail(_('Escribe el nombre de cada invitado.'))
            if phone and not PHONE_RE.match(phone):
                return fail(_('El celular del invitado %s no es válido.', name))
            guest_vals.append(Command.create({'name': name, 'phone': phone or False}))
        try:
            with request.env.cr.savepoint():
                booking = request.env['spa.booking'].sudo().with_context(mail_create_nosubscribe=True).create({
                    'partner_id': membership.partner_id.id,
                    'membership_id': membership.id,
                    'payment_mode': 'membership',
                    'service_id': service.id,
                    'start': slot['start'],
                    'channel': 'portal',
                    'company_id': membership.company_id.id,
                    'guest_ids': guest_vals,
                })
                booking.action_confirm()
                self._spa_clean_salesperson(booking.guest_ids.charge_line_id.move_id)
        except UserError as error:
            values = self._spa_book_values(membership, service_id, day, guests)
            return fail(str(error))
        return request.redirect('/my/spa?msg=booked')

    # ------------------------------------------------------------------
    # Portal: invitados (espacios de acceso libre)
    # ------------------------------------------------------------------
    def _spa_guest_values(self, membership, error=None, msg=None, form=None):
        values = self._spa_member_values('spa_guests', membership, msg=msg, error=error)
        values.update({'blocked': self._spa_blocked_reason(membership), 'form': form or {}, 'guest_lines': []})
        if values['blocked']:
            return values
        plan = membership.plan_id
        lines = plan.line_ids.filtered(lambda l: l.service_id.active and l.service_id.guest_allowed
                                       and l.guests_per_booking > 0
                                       and l.service_id.space_id.access_mode == 'free')
        today = self._spa_today()
        days = [d for d in (today + timedelta(days=i) for i in range(self._spa_booking_days()))
                if membership._covers_date(d)]
        fee = plan.guest_fee_product_id
        quota = plan.guest_quota
        used = membership.guests_this_month
        values.update({
            'guest_lines': lines,
            'days': [{'value': fields.Date.to_string(d), 'label': format_date(request.env, d, date_format="EEEE d 'de' MMMM")}
                     for d in days],
            'guest_quota': quota,
            'guest_used': used,
            'guest_left': max(quota - used, 0),
            'fee_amount': fee.lst_price if fee else 0.0,
            'next_charge': membership._guest_charge_type(today),
            'guests': membership.guest_ids.sorted(lambda g: (g.date, g.id), reverse=True)[:20],
            'slot_lines': plan.line_ids.filtered(lambda l: l.service_id.active and l.service_id.guest_allowed
                                                 and l.guests_per_booking > 0
                                                 and l.service_id.space_id.access_mode == 'slot'),
        })
        return values

    @http.route('/my/spa/guests', type='http', auth='user', website=True, sitemap=False)
    def spa_guests(self, msg=None, **kw):
        membership = self._spa_current_membership()
        return request.render('spa_portal.spa_my_guests', self._spa_guest_values(membership, msg=msg))

    @http.route('/my/spa/guests/register', type='http', auth='user', website=True, methods=['POST'], sitemap=False)
    def spa_guests_register(self, name=None, phone=None, date=None, service_id=None, **kw):
        _ = request.env._
        membership = self._spa_current_membership()
        form = {'name': name or '', 'phone': phone or '', 'date': date or '', 'service_id': service_id or ''}
        values = self._spa_guest_values(membership, form=form)

        def fail(message):
            values['error'] = message
            return request.render('spa_portal.spa_my_guests', values)

        if values['blocked']:
            return fail(values['blocked'])
        name = (name or '').strip()[:MAX_NAME]
        phone = (phone or '').strip()
        if not name:
            return fail(_('Escribe el nombre del invitado.'))
        if phone and not PHONE_RE.match(phone):
            return fail(_('El número de celular no es válido.'))
        line = values['guest_lines'].filtered(lambda l: str(l.service_id.id) == str(service_id))[:1]
        if not line:
            return fail(_('Elige un espacio de acceso libre incluido en tu plan.'))
        if date not in [d['value'] for d in values['days']]:
            return fail(_('Elige una fecha de la lista (dentro de la vigencia de tu membresía).'))
        visit_date = fields.Date.to_date(date)
        same_visit = membership.guest_ids.filtered(
            lambda g: g.date == visit_date and g.service_id == line.service_id and g.state != 'cancelled')
        if len(same_visit) >= line.guests_per_booking:
            return fail(_('Tu plan permite hasta %(n)s invitado(s) por visita en %(service)s y ya registraste '
                          '%(count)s para ese día. Para más invitados comunícate con recepción.',
                          n=line.guests_per_booking, service=line.service_id.name, count=len(same_visit)))
        try:
            with request.env.cr.savepoint():
                guest = request.env['spa.guest'].sudo().with_context(mail_create_nosubscribe=True).create({
                    'name': name,
                    'phone': phone or False,
                    'membership_id': membership.id,
                    'date': visit_date,
                    'service_id': line.service_id.id,
                })
                self._spa_clean_salesperson(guest.charge_line_id.move_id)
        except UserError as error:
            return fail(str(error))
        return request.redirect('/my/spa/guests?msg=guest_%s' % guest.charge_type)

    # ------------------------------------------------------------------
    # Portal: pagar
    # ------------------------------------------------------------------
    def _spa_get_invoice(self, invoice_id):
        invoice = self._spa_get_owned('account.move', invoice_id)
        if invoice.move_type != 'out_invoice' or not invoice.spa_invoice_kind or not (
                invoice.state == 'posted' or invoice._spa_is_pending_charge()):
            raise NotFound()
        return invoice

    def _spa_receipt_max_bytes(self):
        return int(self._spa_param('spa_portal.receipt_max_mb', DEFAULT_RECEIPT_MAX_MB, float) * 1024 * 1024)

    def _spa_pay_values(self, invoice, msg=None, error=None, form=None, more=False):
        _ = request.env._
        membership = invoice.spa_membership_id or self._spa_current_membership()
        values = self._spa_member_values('spa_pay', membership, msg=msg, error=error)
        payable = invoice.amount_residual > 0 and invoice.payment_state not in ('paid', 'reversed', 'in_payment')
        next_values = invoice._get_invoice_next_payment_values() if payable else {}
        next_amount = next_values.get('next_amount_to_pay') or invoice.amount_residual
        requests = request.env['spa.payment.request'].sudo().search([('invoice_id', '=', invoice.id)])
        pending = requests.filtered(lambda r: r.state == 'pending')
        company = invoice.company_id
        max_mb = self._spa_receipt_max_bytes() / (1024 * 1024)
        values.update({
            'invoice': invoice,
            'currency': invoice.currency_id,
            'payable': payable,
            'pending_charge': invoice._spa_is_pending_charge(),
            'doc_label': invoice._spa_document_label(),
            'amount_due': invoice.amount_residual,
            'next_amount': next_amount,
            'installment': next_values.get('installment_state') in ('next', 'overdue'),
            'next_due_date': next_values.get('next_due_date'),
            'payment_ref': invoice._spa_payment_reference(),
            'has_qr': bool(company.spa_payment_qr),
            'qr_url': '/my/spa/pay/%s/qr' % invoice.id,
            'bank_text': company.spa_bank_account_text,
            'instructions': company.spa_payment_instructions,
            'requests': requests,
            'pending': pending,
            'show_form': payable and (not pending or more or error),
            'form': form or {},
            'max_mb': '%g' % max_mb,
            'methods': [('qr', _('QR')), ('transfer', _('Transferencia o depósito'))],
        })
        return values

    @http.route(['/my/spa/pay', '/my/spa/pay/<int:invoice_id>'], type='http', auth='user', website=True,
                sitemap=False)
    def spa_pay(self, invoice_id=None, msg=None, more=None, **kw):
        if not invoice_id:
            invoice = self._spa_open_invoices()[:1]
            if not invoice:
                return request.redirect('/my/spa?msg=nothing_due')
            return request.redirect('/my/spa/pay/%s' % invoice.id)
        invoice = self._spa_get_invoice(invoice_id)
        return request.render('spa_portal.spa_my_pay', self._spa_pay_values(invoice, msg=msg, more=bool(more)))

    @http.route('/my/spa/pay/<int:invoice_id>/qr', type='http', auth='user', website=True, sitemap=False,
                readonly=True)
    def spa_pay_qr(self, invoice_id, **kw):
        """QR de cobro de la compañía: solo para quien tiene una factura pendiente con ella."""
        invoice = self._spa_get_invoice(invoice_id)
        company = invoice.company_id.sudo()
        if invoice.amount_residual <= 0 or not company.spa_payment_qr:
            raise NotFound()
        stream = request.env['ir.binary']._get_image_stream_from(company, 'spa_payment_qr')
        response = stream.get_response()
        response.headers['Cache-Control'] = 'private, max-age=300'
        return response

    @http.route('/my/spa/pay/<int:invoice_id>/submit', type='http', auth='user', website=True, methods=['POST'],
                sitemap=False)
    def spa_pay_submit(self, invoice_id, amount=None, method=None, reference=None, receipt=None, **kw):
        _ = request.env._
        invoice = self._spa_get_invoice(invoice_id)
        form = {'amount': amount or '', 'method': method or '', 'reference': reference or ''}

        def fail(message):
            return request.render('spa_portal.spa_my_pay', self._spa_pay_values(invoice, error=message, form=form))

        if invoice.amount_residual <= 0 or invoice.payment_state in ('paid', 'reversed', 'in_payment'):
            return request.redirect('/my/spa/pay/%s?msg=paid' % invoice.id)
        if method not in PORTAL_PAY_METHODS:
            return fail(_('Elige cómo pagaste: QR o transferencia.'))
        try:
            value = parse_amount(amount)
        except ValueError:
            return fail(_('Escribe el monto pagado, por ejemplo 890.00.'))
        currency = invoice.currency_id
        if currency.compare_amounts(value, 0.0) <= 0:
            return fail(_('El monto pagado debe ser mayor que cero.'))
        if currency.compare_amounts(value, invoice.amount_residual) > 0:
            return fail(_('El monto (%(amount)s) supera tu saldo pendiente (%(due)s).',
                          amount=currency.format(value), due=currency.format(invoice.amount_residual)))
        pending = sum(request.env['spa.payment.request'].sudo().search([
            ('invoice_id', '=', invoice.id), ('state', '=', 'pending')]).mapped('amount'))
        if pending and currency.compare_amounts(pending + value, invoice.amount_residual) > 0:
            return fail(_('Ya informaste %(pending)s que caja está validando; con este pago superarías tu saldo '
                          'pendiente (%(due)s). Espera la validación o comunícate con recepción.',
                          pending=currency.format(pending), due=currency.format(invoice.amount_residual)))
        reference = (reference or '').strip()[:MAX_NAME]
        data, filename = b'', False
        if receipt is not None and hasattr(receipt, 'read'):
            max_bytes = self._spa_receipt_max_bytes()
            data = receipt.read(max_bytes + 1)
            if len(data) > max_bytes:
                return fail(_('El comprobante pesa más de %s MB. Envía una foto más liviana o un PDF.',
                              '%g' % (max_bytes / (1024 * 1024))))
            if data:
                mimetype = guess_mimetype(data, default='application/octet-stream')
                if not (mimetype == 'application/pdf'
                        or (mimetype.startswith('image/') and 'svg' not in mimetype)):
                    return fail(_('El comprobante debe ser una imagen (foto o captura) o un PDF.'))
                # Nombre sin ruta (algunos navegadores envían la ruta completa de Windows).
                filename = re.split(r'[\\/]', receipt.filename or '')[-1].strip()[:MAX_NAME] or _('comprobante')
        if not data and not reference:
            return fail(_('Adjunta la foto o PDF del comprobante, o escribe el número de transacción.'))
        request.env['spa.payment.request'].sudo().with_context(mail_create_nosubscribe=True).create({
            'partner_id': invoice.partner_id.id,
            'membership_id': invoice.spa_membership_id.id,
            'invoice_id': invoice.id,
            'company_id': invoice.company_id.id,
            'amount': value,
            'method': method,
            'reference': reference or False,
            'receipt': base64.b64encode(data) if data else False,
            'receipt_filename': filename,
            'channel': 'portal',
        })
        return request.redirect('/my/spa/pay/%s?msg=received' % invoice.id)
