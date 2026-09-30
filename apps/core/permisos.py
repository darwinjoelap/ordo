"""
Permisos por rol. Una sola tabla: rol → acciones.
Uso en vistas:     @requiere('empresa.configurar')
Uso en plantillas: {% if 'empresa.configurar' in permisos %}
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.empresas.models import Rol

TODOS = {Rol.DUENO, Rol.ADMIN, Rol.ALMACEN, Rol.VENDEDOR}
GESTION = {Rol.DUENO, Rol.ADMIN}

PERMISOS = {
    # Empresa y equipo
    'empresa.configurar': GESTION,
    'usuarios.gestionar': GESTION,
    # Inventario y compras (Fase 3)
    'inventario.ver': TODOS,
    'inventario.gestionar': GESTION | {Rol.ALMACEN},
    'inventario.ver_costos': GESTION | {Rol.ALMACEN},
    'proveedores.gestionar': GESTION | {Rol.ALMACEN},
    'compras.gestionar': GESTION | {Rol.ALMACEN},
    # Comercial (Fase 4)
    'clientes.gestionar': GESTION | {Rol.VENDEDOR},
    'presupuestos.crear': GESTION | {Rol.VENDEDOR},
    'presupuestos.ver_todos': GESTION,
    'ventas.validar': GESTION,
    'reportes.ver': GESTION,
    # Comisiones (Fase 5)
    'comisiones.ver_propias': {Rol.VENDEDOR} | GESTION,
    'comisiones.liquidar': GESTION,
}


def permisos_de(rol):
    return {codigo for codigo, roles in PERMISOS.items() if rol in roles}


def tiene_permiso(request, codigo):
    if codigo not in PERMISOS:
        raise ValueError(f'Permiso desconocido: {codigo}')
    membresia = getattr(request, 'membresia', None)
    return bool(membresia and membresia.rol in PERMISOS[codigo])


def requiere(codigo):
    """Decorador: 403 si el rol de la membresía activa no tiene el permiso."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not tiene_permiso(request, codigo):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
