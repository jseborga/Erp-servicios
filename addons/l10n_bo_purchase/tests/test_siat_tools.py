# Part of ERP Servicios Spa. License LGPL-3.
from datetime import date, datetime

from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_bo_purchase.tools import siat

# CUF real del ambiente piloto del SIN (pruebas de la librería abierta go-siat).
PILOT_CUF = 'D5340CCDF031F2596FC03311F6F76AB5334D0A86A626F497FCE6AAF74'


@tagged('post_install', '-at_install', 'spa')
class TestSiatTools(TransactionCase):

    def test_decode_pilot_cuf(self):
        data = siat.decode_cuf(PILOT_CUF)
        self.assertEqual(data['nit'], '3115970018')
        self.assertEqual(data['emission'], datetime(2026, 3, 18, 19, 36, 19, 975000))
        self.assertEqual(data['number'], '1')
        self.assertEqual(data['sector'], 10)
        self.assertEqual(data['modality'], 2)
        self.assertEqual(data['control_code'], '26F497FCE6AAF74')

    def test_encode_matches_pilot_cuf(self):
        cuf = siat.encode_cuf(3115970018, datetime(2026, 3, 18, 19, 36, 19, 975000),
                              0, 2, 1, 2, 10, 1, 0, '26F497FCE6AAF74')
        self.assertEqual(cuf, PILOT_CUF)

    def test_decode_rejects_altered_cuf(self):
        altered = PILOT_CUF[:10] + ('0' if PILOT_CUF[10] != '0' else '1') + PILOT_CUF[11:]
        self.assertIsNone(siat.decode_cuf(altered))
        self.assertIsNone(siat.decode_cuf('NOT-HEX'))

    def test_parse_legacy_qr(self):
        data = siat.parse_invoice_qr('2326639019|50|29040011007|12/11/2014|275.00|275.00|73-55-84-AC|163874028|0|0|0|0')
        self.assertEqual(data['doc_type'], 'dosificacion')
        self.assertEqual(data['nit'], '2326639019')
        self.assertEqual(data['number'], '50')
        self.assertEqual(data['auth_number'], '29040011007')
        self.assertEqual(data['date'], date(2014, 11, 12))
        self.assertEqual(data['amount_total'], 275.0)
        self.assertEqual(data['control_code'], '73-55-84-AC')
        self.assertEqual(data['buyer_nit'], '163874028')

    def test_parse_legacy_qr_without_control_code_is_manual(self):
        data = siat.parse_invoice_qr('2326639019|51|29040011007|12/11/2014|100|100|0|0')
        self.assertEqual(data['doc_type'], 'manual')
        self.assertFalse(data['control_code'])

    def test_parse_siat_url_qr(self):
        url = 'https://pilotosiat.impuestos.gob.bo/consulta/QR?nit=3115970018&cuf=%s&numero=1&t=1' % PILOT_CUF
        data = siat.parse_invoice_qr(url)
        self.assertEqual(data['doc_type'], 'siat_online')
        self.assertEqual(data['nit'], '3115970018')
        self.assertEqual(data['number'], '1')
        self.assertEqual(data['cuf'], PILOT_CUF)
        self.assertEqual(data['date'], date(2026, 3, 18))
        self.assertIsNone(data['amount_total'])

    def test_parse_unknown_qr(self):
        self.assertIsNone(siat.parse_invoice_qr('hola'))
        self.assertIsNone(siat.parse_invoice_qr(''))

    def test_normalizers(self):
        self.assertEqual(siat.normalize_control_code('7bf348a8'), '7B-F3-48-A8')
        self.assertTrue(siat.is_valid_control_code('6A-DC-53-05-14'))
        self.assertFalse(siat.is_valid_control_code('6A-DC'))
        self.assertEqual(siat.normalize_nit(' 1.020.703-023 '), '1020703023')
        self.assertEqual(siat.normalize_number('000123'), '123')
