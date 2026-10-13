# Part of ERP Servicios Spa. License LGPL-3.
"""Ingresa como socio del portal en un servidor Odoo en marcha y abre /my/spa.

Uso: python verify_portal.py http://127.0.0.1:8069
"""
import re
import sys

import requests

MEMBERS = [('ana.demo', 'Ana Rojas'), ('bruno.demo', 'Bruno Salinas'), ('carla.demo', 'Carla Méndez'),
           ('yolanda.demo', 'Yolanda Paredes')]


def main(base):
    ok = True
    for login, name in MEMBERS:
        session = requests.Session()
        page = session.get(base + '/web/login', timeout=60)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        session.post(base + '/web/login', data={'login': login, 'password': 'demo', 'csrf_token': token,
                                                'redirect': '/my/spa'}, timeout=60)
        response = session.get(base + '/my/spa', timeout=60)
        passed = response.status_code == 200 and name in response.text and '/web/login' not in response.url
        ok = ok and passed
        print('%s login %s -> /my/spa %s (%s en la página: %s)' % (
            'OK  ' if passed else 'FAIL', login, response.status_code, name, name in response.text))
    print('RESULT', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8069'))
