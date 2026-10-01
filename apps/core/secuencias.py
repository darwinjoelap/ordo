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


@transaction.atomic
def siguiente_numero_presupuesto(perfil):
    """
    Número del próximo presupuesto según Mi empresa → Documentos:
      GUION   → 'P-2026-00001' (con el prefijo de la empresa)
      CORRIDO → '202600001' (año + correlativo, como BioLifeVentas); continúa después del mayor número
                existente de ese año, así los documentos migrados y los nuevos siguen una sola serie.
    """
    if perfil.formato_numero_presupuesto != 'CORRIDO':
        return siguiente_numero('P', prefijo=(perfil.prefijo_numeracion or '').upper())
    from apps.ventas.models import Presupuesto
    anio = timezone.localdate().year
    empresa = empresa_actual()
    Secuencia.objects.get_or_create(empresa=empresa, tipo='PC', anio=anio)
    sec = Secuencia.objects.select_for_update().get(tipo='PC', anio=anio)
    existentes = [int(n[4:]) for n in Presupuesto.objects.filter(numero__startswith=str(anio), numero__regex=r'^\d{9}$')
                  .order_by('-numero').values_list('numero', flat=True)[:1]]
    sec.ultimo = max([sec.ultimo] + existentes) + 1
    sec.save(update_fields=['ultimo'])
    return f'{anio}{sec.ultimo:05d}'
