from django.conf import settings

from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from .permisos import permisos_de, tiene_permiso


def _recordatorio_servicios(request, empresa):
    """Conteos para la insignia del menú (solo se consultan si la plantilla los usa)."""
    perfil = getattr(empresa, 'perfil', None) if empresa else None
    if not (perfil and perfil.maneja_servicios and perfil.recordatorio_servicios
            and tiene_permiso(request, 'servicios.gestionar')):
        return None

    def contar():
        from apps.ventas import agenda
        from apps.ventas.views import visibles
        return agenda.resumen(agenda.de_ventas(visibles(request)))
    return SimpleLazyObject(contar)


def ordo(request):
    """Datos globales para todas las plantillas."""
    membresia = getattr(request, 'membresia', None)
    empresa = getattr(request, 'empresa', None)
    tasa = None
    if getattr(request, 'user', None) is not None and request.user.is_authenticated:
        from apps.tasas.servicios import tasa_vigente
        tasa = tasa_vigente(empresa)
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
        'servicios_aviso': _recordatorio_servicios(request, empresa) if membresia else None,
    }
