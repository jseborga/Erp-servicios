# Part of ERP Servicios Spa. License LGPL-3.
"""Base común de las pruebas de punta a punta («un mes de negocio»).

* Fechas fijas: el mes empieza el martes 2 de marzo de 2027 a las 09:00 de La Paz
  (UTC-4, sin horario de verano) = 13:00 UTC. Las pruebas congelan la hora con
  ``freeze_time`` y la avanzan con ``self._at(...)`` para correr los procesos diarios.
* Usuarios reales por rol: cada operación se ejecuta ``with_user(...)`` con el usuario
  que la haría en el spa, para ejercitar permisos y reglas de registro.
"""
import base64
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from odoo import Command, fields
from odoo.tests import freeze_time, new_test_user

from odoo.addons.l10n_bo_purchase.tools import siat

# PNG de 1x1 px: QR de cobro de la empresa y fotos de comprobantes.
PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
PNG_B64 = base64.b64encode(PNG_1PX)

LA_PAZ_OFFSET = timedelta(hours=4)  # America/La_Paz = UTC-4 todo el año
DAY0 = date(2027, 3, 2)  # martes


def utc_at(day, hour, minute=0):
    """Hora local de La Paz -> datetime UTC naïve (lo que guarda Odoo)."""
    return datetime.combine(day, time(hour, minute)) + LA_PAZ_OFFSET


START = utc_at(DAY0, 9)  # 2027-03-02 13:00:00 UTC

# Grupos de cada rol (xmlid separados por coma, formato de new_test_user).
ROLES = {
    # Dueño: gerente del spa + Ajustes + Contabilidad + Empleados (alta de masajistas) + Compras (aprobación).
    'owner': 'base.group_user,base.group_system,spa_base.group_spa_manager,account.group_account_manager,'
             'l10n_bo_purchase.group_spa_accountant,hr.group_hr_user,purchase.group_purchase_manager',
    'manager': 'base.group_user,spa_base.group_spa_manager',
    'reception': 'base.group_user,spa_base.group_spa_reception',
    'cashier': 'base.group_user,spa_base.group_spa_cashier',
    'therapist': 'base.group_user,spa_base.group_spa_therapist',
    'marketing': 'base.group_user,spa_base.group_spa_marketing',
    'buyer': 'base.group_user,l10n_bo_purchase.group_spa_buyer',
    'accountant': 'base.group_user,l10n_bo_purchase.group_spa_accountant',
    'custodian': 'base.group_user,l10n_bo_petty_cash.group_petty_cash_custodian',
    'waiter': 'base.group_user,point_of_sale.group_pos_user',
}


class SpaE2EMixin:
    """Usuarios, configuración del dueño y ayudas de negocio compartidas.

    Se usa con ``TransactionCase`` y con ``HttpCase`` (las clases llaman a ``_e2e_setup``
    desde ``setUpClass`` con la hora ya congelada en ``START``).
    """

    @classmethod
    def _e2e_setup(cls):
        env = cls.env
        cls.company = env.company
        cls.tools = env['spa.tools']
        cls.chart = env['account.chart.template'].with_company(cls.company)
        icp = env['ir.config_parameter'].sudo()
        for key, value in {
            'spa.timezone': 'America/La_Paz',
            'spa.no_show_grace_minutes': '15',
            'spa_messaging.provider': 'wa_link',
            'spa_crm.guest_welcome': 'True',
            'spa_crm.followup_days': '1',
            'spa_crm.courtesy_monthly_limit': '0',
            'spa_crm.courtesy_validity_days': '15',
            'spa_crm.retention_low_usage_pct': '0',
            'spa_crm.retention_expiry_days': '0',
            'spa_portal.booking_days': '14',
        }.items():
            icp.set_param(key, value)

        # ---------------- Usuarios por rol ----------------
        cls.users = {}
        for role, groups in ROLES.items():
            cls.users[role] = new_test_user(
                env, login=f'e2e_{role}', groups=groups, name=f'{role.capitalize()} E2E',
                email=f'e2e.{role}@spa-e2e.example.com', tz='America/La_Paz',
                company_id=cls.company.id, company_ids=[cls.company.id])
        cls.owner = cls.users['owner']
        cls.manager = cls.users['manager']
        cls.reception = cls.users['reception']
        cls.cashier = cls.users['cashier']
        cls.therapist = cls.users['therapist']
        cls.marketing = cls.users['marketing']
        cls.buyer = cls.users['buyer']
        cls.accountant = cls.users['accountant']
        cls.custodian = cls.users['custodian']
        cls.waiter = cls.users['waiter']

        # ---------------- Datos entregados ----------------
        cls.space_pool = env.ref('spa_base.space_pool')
        cls.space_sauna = env.ref('spa_base.space_sauna')
        cls.space_jacuzzi = env.ref('spa_base.space_jacuzzi')
        cls.space_massage = env.ref('spa_base.space_massage_room')
        cls.pool = env.ref('spa_base.service_pool')
        cls.sauna = env.ref('spa_base.service_sauna')
        cls.jacuzzi = env.ref('spa_base.service_jacuzzi')
        cls.massage = env.ref('spa_base.service_massage')
        cls.plan_basic = env.ref('spa_membership.plan_basic')
        cls.plan_premium = env.ref('spa_membership.plan_premium')
        cls.plan_vip = env.ref('spa_membership.plan_vip')
        cls.policy_standard = env.ref('spa_membership.cancel_policy_standard')
        cls.policy_flexible = env.ref('spa_membership.cancel_policy_flexible')
        cls.area_pool = env.ref('l10n_bo_spa.analytic_area_piscina')
        cls.area_wet = env.ref('l10n_bo_spa.analytic_area_sauna_jacuzzi')
        cls.area_spa = env.ref('l10n_bo_spa.analytic_area_spa')
        cls.area_restaurant = env.ref('l10n_bo_spa.analytic_area_restaurante')
        cls.area_admin = env.ref('l10n_bo_spa.analytic_area_administracion')
        cls.therapist_employee = env.ref('spa_base.employee_massage_therapist')
        cls.team_acq = env.ref('spa_crm.team_acquisition')
        cls.team_ret = env.ref('spa_crm.team_retention')
        (cls.plan_basic | cls.plan_premium | cls.plan_vip).write({'website_published': True, 'active': True})

        # ---------------- 1. Configuración del dueño ----------------
        Journal = env['account.journal'].with_user(cls.owner)
        cls.bank_journal = Journal.create({'name': 'Banco Unión – QR y transferencias', 'code': 'BQR',
                                           'type': 'bank', 'company_id': cls.company.id})
        cls.cash_journal = Journal.create({'name': 'Caja recepción', 'code': 'CREC', 'type': 'cash',
                                           'company_id': cls.company.id})
        cls.company.with_user(cls.owner).write({
            'spa_payment_qr': base64.b64encode(PNG_1PX),
            'spa_bank_account_text': 'Banco Unión · Cta. 1-2345678 · Spa VIP S.R.L.',
            'spa_payment_instructions': 'Paga con el QR desde tu app bancaria y envía el comprobante.',
            'spa_payment_journal_id': cls.bank_journal.id,
            'spa_cash_journal_id': cls.cash_journal.id,
            'spa_renewal_days': 5,
        })
        # Aviso de reserva confirmada por WhatsApp (viene desactivado): el dueño lo activa.
        env.ref('spa_messaging.tpl_booking_confirmed').with_user(cls.owner).active = True
        # El masajista entregado: se le da nombre y su usuario (ve su agenda).
        cls.therapist_employee.with_user(cls.owner).write({'name': 'Rosa Quispe (masajista)',
                                                           'user_id': cls.therapist.id})

    # ------------------------------------------------------------------
    # Aserciones
    # ------------------------------------------------------------------
    @contextmanager
    def _raises(self, exception, text=None):
        """assertRaises (con punto de guardado de Odoo) que además verifica el texto del mensaje."""
        with self.assertRaises(exception) as capture:
            yield capture
        if text:
            self.assertIn(text, str(capture.exception))

    # ------------------------------------------------------------------
    # Tiempo
    # ------------------------------------------------------------------
    @contextmanager
    def _at(self, day, hour, minute=0):
        """Congela la hora en ``day hour:minute`` de La Paz."""
        with freeze_time(utc_at(day, hour, minute)):
            yield

    def _dt(self, day, hour, minute=0):
        return utc_at(day, hour, minute)

    # ------------------------------------------------------------------
    # Socios
    # ------------------------------------------------------------------
    @classmethod
    def _partner(cls, name, phone, email=None):
        # Contacto creado con superusuario: recepción no puede crear contactos (ver test_bug_reception_*).
        return cls.env['res.partner'].create({'name': name, 'phone': phone, 'email': email})

    @classmethod
    def _portal_member(cls, login, name, phone=None):
        return new_test_user(cls.env, login=login, groups='base.group_portal', name=name,
                             email=f'{login}@socios.example.com', phone=phone,
                             company_id=cls.company.id, company_ids=[cls.company.id])

    @classmethod
    def _period(cls, plan, months):
        return plan.period_ids.filtered(lambda p: p.months == months)

    @classmethod
    def _enroll(cls, partner, plan, months=1, offer=None, amount=None, method='cash'):
        """Alta presencial: recepción crea la membresía; caja factura, registra el pago y lo valida.

        Devuelve la membresía (entorno superusuario, para verificar). Recepción no puede facturar
        ni registrar el pago desde la membresía (lee ``account.move``): ver
        ``test_bug_reception_cannot_invoice_or_register_payment``.
        """
        cls.env.invalidate_all()
        membership = cls.env['spa.membership'].with_user(cls.reception).create({
            'partner_id': partner.id, 'plan_id': plan.id, 'period_id': cls._period(plan, months).id})
        cls.env.invalidate_all()
        membership.with_user(cls.cashier).action_create_invoice(offer=offer)
        request = cls._register_payment(membership, amount=amount, method=method)
        cls.env.invalidate_all()
        request.with_user(cls.cashier).action_validate()
        return membership.sudo()

    @classmethod
    def _register_payment(cls, membership, amount=None, method='cash', reference='REC-E2E', user=None):
        """Pago informado desde la membresía (queda «por validar» en caja)."""
        user = user or cls.cashier
        cls.env.invalidate_all()  # como en una petición nueva: sin datos leídos por otro usuario
        action = membership.with_user(user).action_register_payment_request()
        values = {'method': method, 'reference': reference}
        if amount is not None:
            values['amount'] = amount
        return cls.env['spa.payment.request'].with_user(user).with_context(**action['context']).create(values)

    # ------------------------------------------------------------------
    # Reservas y accesos
    # ------------------------------------------------------------------
    def _book(self, partner, service, day, hour, user=None, guests=(), channel='reception', minute=0,
              payment_mode='membership', confirm=True):
        membership = partner.spa_membership_id if payment_mode == 'membership' else self.env['spa.membership']
        self.env.invalidate_all()  # como en una petición nueva
        booking = self.env['spa.booking'].with_user(user or self.reception).create({
            'partner_id': partner.id,
            'membership_id': membership.id,
            'payment_mode': payment_mode,
            'service_id': service.id,
            'start': self._dt(day, hour, minute),
            'channel': channel,
            'guest_ids': [Command.create(dict(guest)) for guest in guests],
        })
        if confirm:
            # Servicios con personal: recepción no puede buscar empleados por especialidad
            # (hr.employee.public no tiene spa_skill_ids), se confirma con sudo como lo hace la web.
            # Ver test_bug_reception_cannot_book_massage.
            (booking.sudo() if service.requires_staff else booking).action_confirm()
        return booking.sudo()

    def _check_in(self, space, membership=None, token=None, user=None, guests=0):
        Log = self.env['spa.access.log'].with_user(user or self.reception)
        return Log.do_check_in(space, token=token or membership.qr_token, guests=guests).sudo()

    def _remaining(self, membership, service, day):
        return membership._entitlement_for(service, day).remaining

    # ------------------------------------------------------------------
    # Mensajes, CRM, contabilidad
    # ------------------------------------------------------------------
    def _messages(self, partner, code):
        return self.env['spa.message'].search([('partner_id', '=', partner.id), ('template_id.code', '=', code)])

    def _charges_invoice(self, partner):
        return self.env['account.move'].search([('partner_id', '=', partner.id), ('spa_invoice_kind', '=', 'charges')])

    def _acc(self, xmlid):
        return self.chart.ref(xmlid)

    def _balance(self, account, domain=None):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id), ('company_id', '=', self.company.id),
            ('parent_state', '=', 'posted')] + (domain or []))
        return round(sum(lines.mapped('balance')), 2)

    def _area_amount(self, move_lines, area):
        column = area.plan_id._column_name()
        analytic = self.env['account.analytic.line'].search([('move_line_id', 'in', move_lines.ids)])
        return round(sum(analytic.filtered(lambda line: line[column] == area).mapped('amount')), 2)

    @staticmethod
    def _cuf(nit, number, when=None):
        """CUF válido (módulo 11) con NIT y número embebidos, como el de una factura SIAT real."""
        return siat.encode_cuf(nit, when or datetime(2027, 3, 1, 10, 15, 0, 125000),
                               0, 1, 1, 1, 1, number, 0, '67A75AC82F24C74')

    # ------------------------------------------------------------------
    # POS
    # ------------------------------------------------------------------
    def _pos_open(self, config, user=None):
        config = config.with_user(user or self.waiter)
        if not config.current_session_id:
            config.open_ui()
            config.current_session_id.set_opening_control(0, None)
        return config.current_session_id

    def _pos_pricelist(self, config, partner):
        """Lista de precios que la interfaz del POS asigna al elegir al cliente."""
        if partner and partner.property_product_pricelist in config.available_pricelist_ids:
            return partner.property_product_pricelist
        return config.pricelist_id

    def _pos_order(self, config, lines, partner=None, payments=None, user=None):
        """Pago de una orden en la interfaz del POS (misma llamada ``sync_from_ui``)."""
        user = user or self.waiter
        session = self._pos_open(config, user)
        currency = session.currency_id
        pricelist = self._pos_pricelist(config, partner)
        order_lines, total, untaxed = [], 0.0, 0.0
        for product, qty in lines:
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
        if payments is None:
            payments = [(config.payment_method_ids.filtered('is_cash_count')[:1], total)]
        payments = [(method, total if amount is None else amount) for method, amount in payments]
        now = fields.Datetime.to_string(fields.Datetime.now())
        data = {
            'uuid': str(uuid4()),
            'session_id': session.id,
            'user_id': user.id,
            'partner_id': partner.id if partner else False,
            'pricelist_id': pricelist.id if pricelist else False,
            'fiscal_position_id': False,
            'date_order': now,
            'lines': order_lines,
            'payment_ids': [Command.create({'amount': amount, 'name': now, 'payment_method_id': method.id})
                            for method, amount in payments],
            'amount_total': total,
            'amount_tax': total - untaxed,
            'amount_paid': sum(amount for _method, amount in payments),
            'amount_return': 0.0,
            'to_invoice': False,
            'last_order_preparation_change': '{}',
        }
        result = self.env['pos.order'].with_user(user).sync_from_ui([data])
        return self.env['pos.order'].browse(result['pos.order'][0]['id'])

    def _pos_close(self, session, user=None):
        session = session.with_user(user or self.waiter)
        cash = session.order_ids.payment_ids.filtered(lambda p: p.payment_method_id.is_cash_count)
        session.post_closing_cash_details(sum(cash.mapped('amount')))
        result = session.close_session_from_ui()
        self.assertTrue(result.get('successful'), result)
        return session.sudo().move_id

    # ------------------------------------------------------------------
    # Contabilidad: verificaciones
    # ------------------------------------------------------------------
    def _assert_balanced(self, moves):
        for move in moves:
            self.assertEqual(move.state, 'posted', move.display_name)
            self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')),
                                   places=2, msg='Asiento descuadrado: %s' % move.display_name)
