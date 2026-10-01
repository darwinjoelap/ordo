"""
Equipo de una empresa: agregar personas, cambiar rol, desactivar, restablecer contraseña.

Reglas:
- Nadie modifica su propia membresía (evita quedarse sin acceso por error).
- Solo un Dueño puede asignar el rol Dueño o modificar a otro Dueño.
- Siempre queda al menos un Dueño activo.
- Cada empresa tiene sus propios usuarios (Usuario.empresa_cuenta): solo se restablece la clave de cuentas
  de ESTA empresa, nunca de cuentas de plataforma u otras empresas.
"""
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Membresia, Rol

ALFABETO = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class ErrorEquipo(Exception):
    pass


def clave_temporal():
    return 'Ordo-' + ''.join(secrets.choice(ALFABETO) for _ in range(10))


def roles_asignables(actor):
    return [(v, n) for v, n in Rol.choices if v != Rol.DUENO or actor.rol == Rol.DUENO]


def puede_gestionar(actor, objetivo):
    if actor.pk is not None and actor.pk == objetivo.pk:
        return False
    if objetivo.rol == Rol.DUENO and actor.rol != Rol.DUENO:
        return False
    return True


def solo_en_esta_empresa(usuario, empresa):
    return not usuario.is_superuser and usuario.empresa_cuenta_id == empresa.pk


def _validar_rol(actor, rol):
    if rol not in Rol.values:
        raise ErrorEquipo('Rol inválido.')
    if rol == Rol.DUENO and actor.rol != Rol.DUENO:
        raise ErrorEquipo('Solo un Dueño puede asignar el rol Dueño.')


def _validar_limite(empresa, excluir_pk=None):
    if empresa.limite_usuarios is None:
        return
    activos = (Membresia.objects.filter(empresa=empresa, activa=True, usuario__is_superuser=False)
               .exclude(pk=excluir_pk).count())
    if activos >= empresa.limite_usuarios:
        raise ErrorEquipo(f'Tu plan permite {empresa.limite_usuarios} usuarios activos. '
                          'Desactiva a alguien o pide ampliar el plan.')


def _quedaria_sin_dueno(m, nuevo_rol, nueva_activa):
    if m.rol != Rol.DUENO or (nuevo_rol == Rol.DUENO and nueva_activa):
        return False
    otros = Membresia.objects.filter(empresa=m.empresa, rol=Rol.DUENO, activa=True,
                                     usuario__is_superuser=False).exclude(pk=m.pk)
    return not otros.exists()


@transaction.atomic
def agregar(empresa, actor, username, nombre, apellido, rol, email=''):
    """Crea un usuario propio de la empresa con clave temporal. Devuelve (membresia, clave_temporal)."""
    from apps.usuarios.models import normalizar_usuario
    _validar_rol(actor, rol)
    username = normalizar_usuario(username)
    U = get_user_model()
    if U.objects.filter(empresa_cuenta=empresa, username=username).exists():
        raise ErrorEquipo(f'Ya existe el usuario "{username}" en esta empresa. Si está inactivo, reactívalo.')
    _validar_limite(empresa)
    clave = clave_temporal()
    usuario = U.objects.create_user(username, clave, empresa_cuenta=empresa, email=email or '',
                                    first_name=nombre.strip(), last_name=apellido.strip(), debe_cambiar_clave=True)
    m = Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol)
    return m, clave


@transaction.atomic
def actualizar(actor, m, rol, activa):
    m = Membresia.objects.select_for_update().get(pk=m.pk)
    if not puede_gestionar(actor, m):
        raise ErrorEquipo('No puedes modificar esta membresía.')
    _validar_rol(actor, rol)
    if _quedaria_sin_dueno(m, rol, activa):
        raise ErrorEquipo('La empresa debe conservar al menos un Dueño activo.')
    if activa and not m.activa:
        _validar_limite(m.empresa, excluir_pk=m.pk)
    m.rol, m.activa = rol, activa
    m.save(update_fields=['rol', 'activa'])
    return m


@transaction.atomic
def restablecer_clave(actor, m):
    if not puede_gestionar(actor, m):
        raise ErrorEquipo('No puedes modificar esta membresía.')
    if not solo_en_esta_empresa(m.usuario, m.empresa):
        raise ErrorEquipo('Esta persona también trabaja en otra empresa: debe cambiar su contraseña ella misma '
                          'desde "Mi perfil".')
    clave = clave_temporal()
    u = m.usuario
    u.set_password(clave)
    u.debe_cambiar_clave = True
    u.save(update_fields=['password', 'debe_cambiar_clave'])
    return clave
