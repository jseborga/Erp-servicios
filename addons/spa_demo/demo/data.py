# Part of ERP Servicios Spa. License LGPL-3.
"""Elenco FICTICIO de la demo: personal, socios, prospectos, proveedores y clientes de eventos.

Todos los nombres empiezan con «Demo –», los celulares son +591 7000xxxx y los correos
@demo.spa.bo. Los días son relativos a «hoy» (fecha local del spa al instalar).
"""

DEMO_PASSWORD = 'demo'
EMAIL_DOMAIN = 'demo.spa.bo'
DEMO_PARAM = 'spa_demo.loaded_on'
DAYS_BACK = 42       # semanas de operación simuladas
DAYS_AHEAD = 7       # reservas futuras
SEED = 19            # azar reproducible

# ----------------------------------------------------------------------
# Personal (usuario, nombre, rol, celular). Contraseña: «demo».
# ----------------------------------------------------------------------
ROLE_GROUPS = {
    # Dueño / gerente: Ajustes, gerente del spa, contabilidad, empleados y aprobación de compras.
    'owner': ['base.group_user', 'base.group_system', 'spa_base.group_spa_manager', 'account.group_account_manager',
              'l10n_bo_purchase.group_spa_accountant', 'hr.group_hr_user', 'purchase.group_purchase_manager'],
    'reception': ['base.group_user', 'spa_base.group_spa_reception'],
    'cashier': ['base.group_user', 'spa_base.group_spa_cashier'],
    'therapist': ['base.group_user', 'spa_base.group_spa_therapist'],
    'instructor': ['base.group_user', 'spa_base.group_spa_therapist'],
    'marketing': ['base.group_user', 'spa_base.group_spa_marketing'],
    'buyer': ['base.group_user', 'l10n_bo_purchase.group_spa_buyer'],
    'accountant': ['base.group_user', 'l10n_bo_purchase.group_spa_accountant'],
    'custodian': ['base.group_user', 'l10n_bo_petty_cash.group_petty_cash_custodian'],
    'waiter': ['base.group_user', 'point_of_sale.group_pos_user'],
}

STAFF = [
    # rol, usuario, nombre, celular
    ('owner', 'gerente.demo', 'Demo – Gabriel Rivas (gerente)', '+591 70008101'),
    ('reception', 'recepcion.demo', 'Demo – Patricia Lima (recepción)', '+591 70008102'),
    ('cashier', 'caja.demo', 'Demo – Ramiro Soto (caja)', '+591 70008103'),
    ('therapist', 'terapeuta.demo', 'Demo – Rosa Quispe (masajista)', '+591 70008104'),
    ('instructor', 'instructor.demo', 'Demo – Marco Alanoca (instructor)', '+591 70008105'),
    ('marketing', 'marketing.demo', 'Demo – Valentina Ruiz (marketing)', '+591 70008106'),
    ('buyer', 'compras.demo', 'Demo – Óscar Fuentes (compras)', '+591 70008107'),
    ('accountant', 'contador.demo', 'Demo – Teresa Medina (contadora)', '+591 70008108'),
    ('custodian', 'custodio.demo', 'Demo – Julia Ortega (custodia de caja chica)', '+591 70008109'),
    ('waiter', 'mesero.demo', 'Demo – Iván Torrico (mesero)', '+591 70008110'),
]

# ----------------------------------------------------------------------
# Socios
#   start: día de alta (relativo a hoy)         end: vencimiento buscado (se calcula el alta)
#   usage: 0 sin uso · 1 bajo · 2 normal · 3 alto
#   story: historia especial (ver builder)      portal: usuario del portal (contraseña «demo»)
# ----------------------------------------------------------------------
MEMBERS = [
    dict(key='ana', name='Demo – Ana Rojas', plan='premium', months=1, end=-11, pay='cash', usage=3,
         portal='ana.demo', story='renew_portal'),
    dict(key='bruno', name='Demo – Bruno Salinas', plan='vip', months=3, start=-35, pay='transfer', usage=3,
         portal='bruno.demo'),
    dict(key='carla', name='Demo – Carla Méndez', plan='premium', months=12, start=-38, pay='transfer', usage=2,
         portal='carla.demo', story='installments'),
    dict(key='dario', name='Demo – Darío Flores', plan='basic', months=1, end=10, pay='cash', usage=2),
    dict(key='elena', name='Demo – Elena Vaca', plan='basic', months=3, start=-30, pay='qr', usage=2),
    dict(key='fernando', name='Demo – Fernando Paz', plan='premium', months=1, end=4, pay='cash', usage=1,
         story='downgrade'),
    dict(key='gabriela', name='Demo – Gabriela Torrez', plan='vip', months=12, start=-41, pay='transfer', usage=2,
         story='annual_discount'),
    dict(key='hugo', name='Demo – Hugo Quispe', plan='premium', months=1, end=15, pay='qr', usage=2,
         story='instagram'),
    dict(key='isabel', name='Demo – Isabel Choque', plan='basic', months=1, end=27, pay='cash', usage=1,
         story='guest_of_ana'),
    dict(key='jorge', name='Demo – Jorge Mamani', plan='premium', months=1, end=2, pay='cash', usage=2,
         story='upgrade'),
    dict(key='karen', name='Demo – Karen Gutiérrez', plan='basic', months=12, start=-33, pay='cash', usage=2),
    dict(key='lorena', name='Demo – Lorena Copa', plan='vip', months=3, start=-12, pay='qr', usage=2),
    dict(key='mariana', name='Demo – Mariana Soliz', plan='premium', months=1, end=21, pay='qr', usage=2),
    dict(key='nicolas', name='Demo – Nicolás Vargas', plan='vip', months=1, end=8, pay='transfer', usage=2),
    dict(key='olga', name='Demo – Olga Peña', plan='premium', months=3, start=-30, pay='qr', usage=2,
         story='freeze'),
    dict(key='pablo', name='Demo – Pablo Rocha', plan='basic', months=1, end=3, pay='cash', usage=1,
         story='renewal_pending'),
    dict(key='rosa', name='Demo – Rosa Aguilar', plan='premium', months=3, start=-41, pay='transfer', usage=0,
         story='low_usage'),
    dict(key='sergio', name='Demo – Sergio Limachi', plan='premium', months=1, end=-2, pay='cash', usage=2,
         story='grace'),
    dict(key='tatiana', name='Demo – Tatiana Ríos', plan='basic', months=1, end=-1, pay='qr', usage=1,
         story='grace'),
    dict(key='ulises', name='Demo – Ulises Calle', plan='premium', months=1, end=-9, pay='cash', usage=1,
         story='suspended'),
    dict(key='valeria', name='Demo – Valeria Montes', plan='vip', months=1, end=-16, pay='qr', usage=1,
         story='suspended'),
    dict(key='walter', name='Demo – Walter Cruz', plan='basic', months=1, end=-100, pay='cash', usage=0,
         story='expired'),
    dict(key='zacarias', name='Demo – Zacarías Luna', plan='basic', months=1, end=-6, pay='cash', usage=1,
         story='cancelled'),
    dict(key='yolanda', name='Demo – Yolanda Paredes', plan='premium', months=1, portal='yolanda.demo',
         story='web_signup'),
    dict(key='andres', name='Demo – Andrés Huanca', plan='premium', months=1, pay='cash', usage=1,
         story='today'),
]

# ----------------------------------------------------------------------
# Prospectos del CRM creados por marketing (fuente = xmlid de spa_crm.utm_source_*)
#   day: día de alta · stage: interested / visit / proposal / lost
# ----------------------------------------------------------------------
LEADS = [
    dict(key='camila', name='Demo – Camila Rivero', source='instagram', day=-10, stage='interested',
         note='Preguntó por el plan Premium en un comentario de Instagram.'),
    dict(key='diego', name='Demo – Diego Saavedra', source='facebook', day=-30, stage='lost',
         note='Consulta por Facebook: le pareció caro.'),
    dict(key='laura', name='Demo – Laura Gemio', source='member_referral', day=-8, stage='proposal',
         referrer='bruno', note='Amiga de Bruno Salinas: se le envió la propuesta del plan VIP.'),
    dict(key='monica', name='Demo – Mónica Céspedes', source='whatsapp', day=0, stage='interested',
         note='Escribió por WhatsApp preguntando horarios de piscina.'),
    dict(key='esteban', name='Demo – Esteban Prado', source='web', day=0, stage='interested',
         note='Formulario de contacto de la web.'),
    dict(key='gonzalo', name='Demo – Gonzalo Arias', source='tiktok', day=-17, stage='visit',
         note='Vio el video del jacuzzi en TikTok.'),
    dict(key='fabiola', name='Demo – Fabiola Nina', source='event', day=-24, stage='proposal',
         note='Se interesó en la feria de salud y bienestar.'),
]

# Cortesías (además de las ligadas a prospectos): emitida, canjeada, vencida.
COURTESIES = [
    dict(key='paola', name='Demo – Paola Ibáñez', source='facebook', issue=-25, redeem=None, visits=1,
         reason='Sorteo de Facebook (ficticio)'),
    dict(key='ricardo', name='Demo – Ricardo Soria', source='tiktok', issue=-6, redeem=-4, visits=1,
         reason='Campaña TikTok (ficticia)'),
    dict(key='sofia', name='Demo – Sofía Antezana', source='instagram', issue=-2, redeem=None, visits=2,
         reason='Influencer local (ficticia)'),
]

# Invitados de socios (nombre, celular)
GUESTS = {
    'lucia': ('Demo – Lucía Paz (invitada)', '+591 70002001'),
    'isabel': ('Demo – Isabel Choque', '+591 70001009'),
    'mateo': ('Demo – Mateo Rocha (invitado)', '+591 70002003'),
    'diana': ('Demo – Diana Vela (invitada)', '+591 70002004'),
    'ernesto': ('Demo – Ernesto Gil (invitado)', '+591 70002005'),
    'carmen': ('Demo – Carmen Ortiz (invitada)', '+591 70002006'),
    'pedro': ('Demo – Pedro Luna (invitado)', '+591 70002007'),
}

# Visitantes sin membresía (entradas sueltas y pases diarios)
VISITORS = [
    ('Demo – Visitante Martín Ayala', '+591 70004001'),
    ('Demo – Visitante Silvia Rojas', '+591 70004002'),
    ('Demo – Visitante Tomás Herrera', '+591 70004003'),
    ('Demo – Visitante Noemí Cáceres', '+591 70004004'),
    ('Demo – Visitante Raúl Beltrán', '+591 70004005'),
    ('Demo – Visitante Wilma Suárez', '+591 70004006'),
]

# Alumnos de clases (sin membresía)
STUDENTS = [
    ('Demo – Luciana Arce (alumna)', '+591 70006001'),
    ('Demo – Tomás Rivera (alumno)', '+591 70006002'),
    ('Demo – Emilia Zurita (alumna)', '+591 70006003'),
]

# Clientes de eventos
EVENT_CUSTOMERS = {
    # nombre, celular, NIT/CI, tipo de documento SIAT (1 = CI, 5 = NIT)
    'birthday': ('Demo – Familia Gutiérrez Vaca', '+591 70005001', '8200001', '1'),
    'club': ('Demo – Club Acuático Delfines (ficticio)', '+591 70005002', '9990000081', '5'),
}

# Proveedores ficticios (NIT de 10 dígitos, solo números)
VENDORS = {
    'chemicals': ('Demo – Química Andina Ficticia S.R.L.', '9990000011'),
    'food': ('Demo – Distribuidora El Ceibo Ficticia', '9990000021'),
    'power': ('Demo – Electricidad Ficticia S.A.', '9990000031'),
    'water': ('Demo – Agua Potable Ficticia', '9990000041'),
    'spa_supplies': ('Demo – Aceites y Esencias Ficticia', '9990000051'),
    'laundry': ('Demo – Lavandería Ficticia', '9990000061'),
    'bookstore': ('Demo – Librería Ficticia', '9990000071'),
}
FREELANCERS = {
    'plumber': 'Demo – Juan Mamani (plomero, sin factura)',
    'designer': 'Demo – Carla Ruiz (diseñadora, sin factura)',
}
