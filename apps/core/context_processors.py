from django.conf import settings

from .permisos import permisos_de


def ordo(request):
    """Datos globales para todas las plantillas."""
    membresia = getattr(request, 'membresia', None)
    empresa = getattr(request, 'empresa', None)
    return {
        'ORDO_VERSION': settings.ORDO_VERSION,
        'empresa': empresa,
        'perfil': getattr(empresa, 'perfil', None) if empresa else None,
        'membresia': membresia,
        'membresias': getattr(request, 'membresias', []),
        'permisos': permisos_de(membresia.rol) if membresia else set(),
    }
