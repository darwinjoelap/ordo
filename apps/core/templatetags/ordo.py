from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def usd(valor):
    """1234.5 → '$ 1.234,50' (formato venezolano)."""
    try:
        numero = Decimal(valor or 0).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return valor
    entero, decimales = f'{abs(numero):,.2f}'.split('.')
    texto = f"{entero.replace(',', '.')},{decimales}"
    return f"{'-' if numero < 0 else ''}$ {texto}"


@register.filter
def miles(valor):
    """1234 → '1.234'."""
    try:
        return f'{int(valor):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return valor


@register.simple_tag
def url_pagina(querystring, numero):
    return f'?{querystring}&page={numero}' if querystring else f'?page={numero}'


@register.filter
def abs_valor(valor):
    """Valor absoluto (para mostrar diferencias sin signo)."""
    try:
        return abs(valor)
    except TypeError:
        return valor
