import logging
from decimal import Decimal, InvalidOperation

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


def actualizar_desde_bcv():
    """Consulta el BCV y registra la tasa del día. Devuelve la TasaCambio o lanza excepción."""
    respuesta = requests.get(URL_BCV, timeout=20, headers={'User-Agent': 'Mozilla/5.0 (Ordo)'})
    respuesta.raise_for_status()
    valor = leer_tasa_html(respuesta.text)
    return registrar(valor, TasaCambio.Fuente.BCV)


def registrar(valor, fuente, usuario=None, fecha=None):
    tasa, _ = TasaCambio.objects.update_or_create(
        fecha=fecha or timezone.localdate(),
        defaults={'bs_por_usd': valor, 'fuente': fuente, 'registrada_por': usuario})
    limpiar_cache()
    return tasa
