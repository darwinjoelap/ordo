"""Qué clientes ve cada usuario."""
from apps.core.permisos import tiene_permiso

from .models import Cliente


def clientes_visibles(request):
    qs = Cliente.objects.all()
    if tiene_permiso(request, 'presupuestos.ver_todos'):
        return qs
    if request.empresa.perfil.vendedores_ven_todos_los_clientes:
        return qs
    return qs.filter(vendedor=request.user)
