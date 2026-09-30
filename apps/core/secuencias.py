from django.db import transaction
from django.utils import timezone

from .models import Secuencia
from .tenancy import empresa_actual


@transaction.atomic
def siguiente_numero(tipo, prefijo=''):
    """
    Devuelve el próximo número del documento, p. ej. 'OC-2026-00001' o 'BLP-2026-00001'.
    Dos usuarios a la vez nunca reciben el mismo número.
    """
    anio = timezone.localdate().year
    empresa = empresa_actual()
    Secuencia.objects.get_or_create(empresa=empresa, tipo=tipo, anio=anio)
    sec = Secuencia.objects.select_for_update().get(tipo=tipo, anio=anio)
    sec.ultimo += 1
    sec.save(update_fields=['ultimo'])
    return f'{prefijo}{tipo}-{anio}-{sec.ultimo:05d}'
