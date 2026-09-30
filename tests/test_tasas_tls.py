"""
El sitio del BCV no envía el certificado intermedio. Se completa la cadena por AIA sin desactivar la verificación.
"""
import datetime
from unittest import mock

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID
from django.test import SimpleTestCase

from apps.tasas import servicios

AHORA = datetime.datetime.now(datetime.timezone.utc)


def _cert(sujeto, emisor, clave, clave_emisor, ca, aia=None):
    nombre = lambda cn: x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])  # noqa: E731
    b = (x509.CertificateBuilder().subject_name(nombre(sujeto)).issuer_name(nombre(emisor))
         .public_key(clave.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(AHORA).not_valid_after(AHORA + datetime.timedelta(days=5))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if aia:
        b = b.add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(
            AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(aia))]), critical=False)
    return b.sign(clave_emisor, hashes.SHA256())


class CadenaBCVTests(SimpleTestCase):
    def setUp(self):
        kr, ki, kh = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
        self.raiz = _cert('Raiz', 'Raiz', kr, kr, True)
        self.inter = _cert('Intermedio', 'Raiz', ki, kr, True, aia='http://ca.ejemplo/raiz.cer')
        self.hoja = _cert('www.bcv.org.ve', 'Intermedio', kh, ki, False, aia='http://ca.ejemplo/inter.cer')
        der = lambda c: c.public_bytes(serialization.Encoding.DER)  # noqa: E731
        self.descargas = {'http://ca.ejemplo/inter.cer': der(self.inter), 'http://ca.ejemplo/raiz.cer': der(self.raiz)}

    def _get(self, url, **kw):
        return mock.Mock(content=self.descargas[url])

    def test_obtiene_intermedio_y_nunca_la_raiz(self):
        pem_hoja = self.hoja.public_bytes(serialization.Encoding.PEM).decode()
        with mock.patch('ssl.get_server_certificate', return_value=pem_hoja), \
                mock.patch.object(servicios.requests, 'get', side_effect=self._get):
            intermedios = servicios.intermedios_por_aia('www.bcv.org.ve')
        self.assertEqual(len(intermedios), 1)
        self.assertIn('BEGIN CERTIFICATE', intermedios[0])
        self.assertEqual(x509.load_pem_x509_certificate(intermedios[0].encode()).subject, self.inter.subject)

    def test_reintenta_verificando_con_el_bundle(self):
        llamadas = []

        def get(url, **kw):
            llamadas.append(kw.get('verify', True))
            if len(llamadas) == 1:
                raise requests.exceptions.SSLError('unable to get local issuer certificate')
            return mock.Mock(status_code=200, text='ok')
        with mock.patch.object(servicios.requests, 'get', side_effect=get), \
                mock.patch.object(servicios, 'bundle_con_intermedios', return_value='/tmp/ordo-ca-prueba.pem'), \
                mock.patch.object(servicios.os, 'remove'):
            r = servicios.descargar_bcv()
        self.assertEqual(r.text, 'ok')
        self.assertEqual(llamadas, [True, '/tmp/ordo-ca-prueba.pem'])   # nunca verify=False

    def test_acepta_pkcs7_como_publican_algunas_autoridades(self):
        from cryptography.hazmat.primitives.serialization import pkcs7
        p7 = pkcs7.serialize_certificates([self.inter], serialization.Encoding.DER)
        self.descargas['http://ca.ejemplo/inter.cer'] = p7
        pem_hoja = self.hoja.public_bytes(serialization.Encoding.PEM).decode()
        with mock.patch('ssl.get_server_certificate', return_value=pem_hoja), \
                mock.patch.object(servicios.requests, 'get', side_effect=self._get):
            self.assertEqual(len(servicios.intermedios_por_aia('www.bcv.org.ve')), 1)

    def test_descarga_que_no_es_certificado_da_error_claro(self):
        self.descargas['http://ca.ejemplo/inter.cer'] = b'<html>Moved</html>'
        pem_hoja = self.hoja.public_bytes(serialization.Encoding.PEM).decode()
        with mock.patch('ssl.get_server_certificate', return_value=pem_hoja), \
                mock.patch.object(servicios.requests, 'get', side_effect=self._get), \
                self.assertRaisesRegex(ValueError, 'ca.ejemplo/inter.cer'):
            servicios.intermedios_por_aia('www.bcv.org.ve')
