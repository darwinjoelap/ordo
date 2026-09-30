from django.conf import settings

from django.utils import timezone

from .permisos import permisos_de


def ordo(request):
    """Datos globales para todas las plantillas."""
    membresia = getattr(request, 'membresia', None)
    empresa = getattr(request, 'empresa', None)
    tasa = None
    if getattr(request, 'user', None) is not None and request.user.is_authenticated:
        from apps.tasas.servicios import tasa_vigente
        tasa = tasa_vigente()
    aviso = None
    if empresa and membresia and membresia.rol in ('DUENO', 'ADMIN'):
        dias = empresa.dias_para_vencer
        if dias is not None and 0 <= dias <= 7:
            aviso = dias
    return {
        'aviso_vencimiento': aviso,
        'tasa': tasa,
        'tasa_desactualizada': bool(tasa and tasa.fecha < timezone.localdate()),
        'ORDO_VERSION': settings.ORDO_VERSION,
        'empresa': empresa,
        'perfil': getattr(empresa, 'perfil', None) if empresa else None,
        'membresia': membresia,
        'membresias': getattr(request, 'membresias', []),
        'permisos': permisos_de(membresia.rol) if membresia else set(),
    }
