import logging
import os
import ssl
import tempfile
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
from django.utils import timezone

from .models import TasaCambio

log = logging.getLogger('apps.tasas')
URL_BCV = 'https://www.bcv.org.ve/'
CLAVE_CACHE = 'ordo:tasa_vigente'


def tasa_vigente():
    """Última tasa registrada (cacheada 5 min). None si no hay ninguna."""
    tasa = cache.get(CLAVE_CACHE)
    if tasa is None:
        tasa = TasaCambio.objects.order_by('-fecha').first() or False
        cache.set(CLAVE_CACHE, tasa, 300)
    return tasa or None


def limpiar_cache():
    cache.delete(CLAVE_CACHE)


def leer_tasa_html(html):
    """Extrae la tasa USD del HTML del BCV (bloque con id="dolar")."""
    soup = BeautifulSoup(html, 'lxml')
    bloque = soup.find(id='dolar')
    fuerte = bloque.find('strong') if bloque else None
    if not fuerte:
        raise ValueError('No se encontró el bloque del dólar en la página del BCV.')
    texto = fuerte.get_text(strip=True).replace('.', '').replace(',', '.')
    try:
        valor = Decimal(texto).quantize(Decimal('0.0001'))
    except InvalidOperation:
        raise ValueError(f'Valor de tasa no numérico: {texto!r}')
    if valor <= 0:
        raise ValueError('La tasa debe ser mayor que cero.')
    return valor


# ── Certificado incompleto del BCV ────────────────────────────────────────────
# El servidor del BCV no envía el certificado intermedio, así que la verificación TLS falla
# ("unable to get local issuer certificate"). No desactivamos la verificación: descargamos el
# intermedio desde la URL que el propio certificado declara (AIA "CA Issuers") y verificamos
# contra las raíces de certifi + ese intermedio. Nunca se agregan raíces descargadas.

def _pem(cert):
    from cryptography.hazmat.primitives.serialization import Encoding
    return cert.public_bytes(Encoding.PEM).decode()


def _urls_ca_issuers(cert):
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in aia if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]


def _cargar_cert(datos):
    from cryptography import x509
    try:
        return x509.load_der_x509_certificate(datos)
    except ValueError:
        return x509.load_pem_x509_certificate(datos)


def intermedios_por_aia(host, port=443, max_niveles=3):
    """PEM de los certificados intermedios del servidor, obtenidos por AIA (sin raíces autofirmadas)."""
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port), timeout=20).encode())
    intermedios = []
    for _ in range(max_niveles):
        urls = _urls_ca_issuers(cert)
        if not urls:
            break
        cert = _cargar_cert(requests.get(urls[0], timeout=20).content)
        if cert.issuer == cert.subject:      # raíz: no se agrega, debe estar en certifi
            break
        intermedios.append(_pem(cert))
    return intermedios


def bundle_con_intermedios(host, port=443):
    """Ruta a un archivo CA = certifi + intermedios del host."""
    import certifi
    intermedios = intermedios_por_aia(host, port)
    if not intermedios:
        raise ValueError(f'No se pudo obtener el certificado intermedio de {host}.')
    with open(certifi.where()) as f:
        base = f.read()
    fd, ruta = tempfile.mkstemp(prefix='ordo-ca-', suffix='.pem')
    with os.fdopen(fd, 'w') as f:
        f.write(base + '\n' + '\n'.join(intermedios))
    return ruta


def descargar_bcv(url=None):
    url = url or URL_BCV
    cabeceras = {'User-Agent': 'Mozilla/5.0 (Ordo)'}
    try:
        return requests.get(url, timeout=20, headers=cabeceras)
    except requests.exceptions.SSLError:
        log.info('BCV sin certificado intermedio: se completa la cadena por AIA.')
        u = urlparse(url)
        ruta = bundle_con_intermedios(u.hostname, u.port or 443)
        try:
            return requests.get(url, timeout=20, headers=cabeceras, verify=ruta)
        finally:
            os.remove(ruta)


def actualizar_desde_bcv():
    """Consulta el BCV y registra la tasa del día. Devuelve la TasaCambio o lanza excepción."""
    respuesta = descargar_bcv()
    respuesta.raise_for_status()
    valor = leer_tasa_html(respuesta.text)
    return registrar(valor, TasaCambio.Fuente.BCV)


def registrar(valor, fuente, usuario=None, fecha=None):
    tasa, _ = TasaCambio.objects.update_or_create(
        fecha=fecha or timezone.localdate(),
        defaults={'bs_por_usd': valor, 'fuente': fuente, 'registrada_por': usuario})
    limpiar_cache()
    return tasa
