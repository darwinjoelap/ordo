"""Lectura tolerante de números escritos a mano (coma o punto decimal, separador de miles)."""
from decimal import Decimal, InvalidOperation


def numero(texto):
    """
    '12,50' · '12.50' · '1.234,50' · '1,234.50' · '$ 12' → Decimal; vacío o texto inválido → None.
    Con punto y coma a la vez, el último que aparece es el separador decimal.
    """
    t = (texto or '').replace(' ', '').replace('$', '')
    if not t:
        return None
    if ',' in t and '.' in t:
        miles, decimal = ('.', ',') if t.rfind(',') > t.rfind('.') else (',', '.')
        t = t.replace(miles, '').replace(decimal, '.')
    else:
        t = t.replace(',', '.')
    try:
        valor = Decimal(t)
    except InvalidOperation:
        return None
    return valor if valor.is_finite() else None


def leer_decimal(texto):
    """Como `numero`, pero vacío → None y texto inválido → InvalidOperation (para los `except` existentes)."""
    if not (texto or '').strip():
        return None
    valor = numero(texto)
    if valor is None:
        raise InvalidOperation(texto)
    return valor
