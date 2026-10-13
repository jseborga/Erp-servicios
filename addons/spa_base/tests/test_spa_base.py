# Part of ERP Servicios Spa. License LGPL-3.
from datetime import date

from odoo.tests import TransactionCase, freeze_time, new_test_user, tagged

WED = date(2027, 3, 10)


@tagged('post_install', '-at_install', 'spa')
@freeze_time('2027-03-08 13:00:00')
class TestSpaBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tools = cls.env['spa.tools']
        cls.massage = cls.env.ref('spa_base.service_massage')
        cls.therapist = cls.env.ref('spa_base.employee_massage_therapist')
        cls.reception = new_test_user(cls.env, login='spa_base_reception', groups='spa_base.group_spa_reception')

    def test_reception_finds_qualified_staff(self):
        """Recepción (sin permisos de Empleados) obtiene el personal con la especialidad y su turno."""
        service = self.massage.with_user(self.reception)
        self.env.invalidate_all()
        employees = service._qualified_employees()
        self.assertIn(self.therapist, employees)
        self.assertEqual(employees.env.uid, self.reception.id, 'Se devuelven en el entorno de quien llama')
        self.assertFalse(employees.env.su)
        employee = employees.filtered(lambda e: e == self.therapist)
        # Turno 09:00-18:00 (hora de La Paz)
        self.assertTrue(employee._spa_is_working(self.tools.local_combine(WED, 10.0),
                                                 self.tools.local_combine(WED, 11.0)))
        self.assertFalse(employee._spa_is_working(self.tools.local_combine(WED, 18.0),
                                                  self.tools.local_combine(WED, 19.0)))

    def test_reception_creates_member_contact(self):
        partner = self.env['res.partner'].with_user(self.reception).create(
            {'name': 'Socio nuevo en recepción', 'phone': '+591 70000177'})
        partner.with_user(self.reception).write({'email': 'nuevo@example.com'})
        self.assertEqual(partner.email, 'nuevo@example.com')

    def test_find_partner_by_phone(self):
        Partner = self.env['res.partner']
        first = Partner.create({'name': 'Luis Rojas', 'phone': '+591 700-11122'})
        Partner.create({'name': 'Luis Rojas (duplicado)', 'phone': '70011122'})
        Partner.create({'name': 'Archivado', 'phone': '70011199', 'active': False})
        for typed in ('70011122', '+59170011122', '00591 700 111 22', '(591) 7001-1122'):
            self.assertEqual(Partner._spa_find_by_phone(typed), first, typed)
        self.assertFalse(Partner._spa_find_by_phone('70011199'), 'No devuelve contactos archivados')
        self.assertFalse(Partner._spa_find_by_phone('22'))
        self.assertFalse(Partner._spa_find_by_phone(False))
        self.assertFalse(Partner._spa_find_by_phone('70099999'))
