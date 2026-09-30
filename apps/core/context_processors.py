from django.conf import settings


def ordo(request):
    """Datos globales para todas las plantillas."""
    return {
        'ORDO_VERSION': settings.ORDO_VERSION,
    }
