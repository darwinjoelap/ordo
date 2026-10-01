import logging
import os
import ssl
import tempfile
import warnings
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.core.cache import cache
from django.utils import timezone

from .models import TasaCambio, TasaEmpresa

log = logging.getLogger('apps.tasas')
URL_BCV = 'https://www.bcv.org.ve/'
CLAVE_CACHE = 'ordo:tasa_vigente'


def tasa_global():
    """Última tasa BCV/plataforma (cacheada 5 min). None si no hay ninguna."""
    tasa = cache.get(CLAVE_CACHE)
    if tasa is None:
        tasa = TasaCambio.objects.order_by('-fecha').first() or False
        cache.set(CLAVE_CACHE, tasa, 300)
    return tasa or None


def _clave_empresa(empresa_id):
    return f'{CLAVE_CACHE}:empresa:{empresa_id}'


def tasa_de_empresa(empresa):
    """Última tasa cargada a mano por la empresa (cacheada). None si no tiene."""
    clave = _clave_empresa(empresa.pk)
    tasa = cache.get(clave)
    if tasa is None:
        tasa = TasaEmpresa.todos.filter(empresa=empresa).order_by('-fecha').first() or False
        cache.set(clave, tasa, 300)
    return tasa or None


def tasa_vigente(empresa=None):
    """
    Tasa que usa la empresa: la más reciente entre la global y la suya; si son del mismo día, la suya.
    Sin empresa (plataforma, comandos), la global.
    """
    global_ = tasa_global()
    if empresa is None:
        return global_
    propia = tasa_de_empresa(empresa)
    if propia and (global_ is None or propia.fecha >= global_.fecha):
        return propia
    return global_


def registrar_de_empresa(empresa, valor, usuario, fecha=None):
    tasa, _ = TasaEmpresa.todos.update_or_create(
        empresa=empresa, fecha=fecha or timezone.localdate(),
        defaults={'bs_por_usd': valor, 'registrada_por': usuario})
    cache.delete(_clave_empresa(empresa.pk))
    return tasa


def borrar_de_empresa(empresa, fecha):
    TasaEmpresa.todos.filter(empresa=empresa, fecha=fecha).delete()
    cache.delete(_clave_empresa(empresa.pk))


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


def _cargar_certs(datos, url=''):
    """Certificados de una descarga AIA: DER, PEM o PKCS#7 (.p7c/.p7b), en DER o PEM."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs7
    intentos = (
        lambda d: [x509.load_der_x509_certificate(d)],
        lambda d: x509.load_pem_x509_certificates(d),
        lambda d: pkcs7.load_der_pkcs7_certificates(d),
        lambda d: pkcs7.load_pem_pkcs7_certificates(d),
    )
    for cargar in intentos:
        try:
            with warnings.catch_warnings():
                # El PKCS#7 del BCV viene en BER (no DER estricto); cryptography lo lee igual pero avisa.
                warnings.simplefilter('ignore', UserWarning)
                certs = cargar(datos)
            if certs:
                return certs
        except Exception:  # noqa: BLE001 - se prueba el siguiente formato
            continue
    muestra = datos[:40]
    raise ValueError(f'Formato de certificado no reconocido en {url} ({len(datos)} bytes, inicio {muestra!r}).')


def intermedios_por_aia(host, port=443, max_niveles=3):
    """PEM de los certificados intermedios del servidor, obtenidos por AIA (sin raíces autofirmadas)."""
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port), timeout=20).encode())
    intermedios, vistos = [], set()
    for _ in range(max_niveles):
        urls = _urls_ca_issuers(cert)
        if not urls:
            break
        respuesta = requests.get(urls[0], timeout=20, headers={'User-Agent': 'Mozilla/5.0 (Ordo)'})
        respuesta.raise_for_status()
        siguiente = None
        for c in _cargar_certs(respuesta.content, urls[0]):
            if c.issuer == c.subject or c.fingerprint(_sha256()) in vistos:
                continue                     # raíz: no se agrega, debe estar en certifi
            vistos.add(c.fingerprint(_sha256()))
            intermedios.append(_pem(c))
            if c.subject == cert.issuer:
                siguiente = c
        if siguiente is None:
            break
        cert = siguiente
    return intermedios


def _sha256():
    from cryptography.hazmat.primitives import hashes
    return hashes.SHA256()


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
