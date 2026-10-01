"""
Panel de plataforma (solo superusuarios de Ordo): alta y control de empresas cliente.

El "enlace" de cada empresa es su slug: https://<dominio>/<slug>/
"""
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .equipo import clave_temporal
from .models import Empresa, Membresia, Rol

# Primeros segmentos de URL que usa Ordo: no pueden ser enlaces de empresa
RESERVADOS = {
    'admin', 'api', 'cuenta', 'empresa', 'empresas', 'inventario', 'proveedores', 'compras', 'clientes',
    'ventas', 'comisiones', 'plataforma', 'salud', 'offline', 'instalar', 'visor', 'static', 'media', 'favicon.ico',
    'manifest.webmanifest', 'sw.js', '__debug__', 'ordo', 'www', 'app', 'soporte', 'ayuda', 'login', 'entrar',
}
PATRON = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def validar_enlace(slug, excluir_pk=None):
    slug = (slug or '').strip().lower()
    if not 3 <= len(slug) <= 40 or not PATRON.match(slug):
        raise ValidationError('Usa de 3 a 40 letras minúsculas, números o guiones (ej. biolife).')
    if slug in RESERVADOS:
        raise ValidationError(f'"{slug}" está reservado por Ordo. Elige otro.')
    if Empresa.objects.filter(slug=slug).exclude(pk=excluir_pk).exists():
        raise ValidationError('Ese enlace ya lo usa otra empresa.')
    return slug


@transaction.atomic
def crear_empresa(datos):
    """
    datos: nombre_comercial, razon_social, rif, slug, plan, activa_hasta, limite_usuarios, notas,
           usuario_dueno, email_dueno, nombre_dueno, apellido_dueno.
    Devuelve (empresa, dueño, clave_temporal). El Dueño es un usuario propio de la empresa.
    """
    empresa = Empresa.objects.create(
        nombre=datos['nombre_comercial'], slug=datos['slug'], plan=datos['plan'],
        activa_hasta=datos.get('activa_hasta'), limite_usuarios=datos.get('limite_usuarios'),
        notas=datos.get('notas', ''))
    perfil = empresa.perfil
    perfil.nombre_comercial = datos['nombre_comercial']
    perfil.razon_social = datos.get('razon_social', '')
    perfil.rif = datos.get('rif', '')
    perfil.save()

    U = get_user_model()
    clave = clave_temporal()
    dueno = U.objects.create_user(datos['usuario_dueno'], clave, empresa_cuenta=empresa,
                                  email=datos.get('email_dueno') or '',
                                  first_name=(datos.get('nombre_dueno') or '').strip(),
                                  last_name=(datos.get('apellido_dueno') or '').strip(), debe_cambiar_clave=True)
    Membresia.objects.create(usuario=dueno, empresa=empresa, rol=Rol.DUENO)
    return empresa, dueno, clave


@transaction.atomic
def actualizar_empresa(empresa, datos):
    for campo in ('nombre', 'slug', 'plan', 'estado', 'activa_hasta', 'limite_usuarios', 'notas'):
        if campo in datos:
            setattr(empresa, campo, datos[campo])
    empresa.save()
    perfil = empresa.perfil
    for campo in ('razon_social', 'rif'):
        if campo in datos:
            setattr(perfil, campo, datos[campo])
    perfil.save(update_fields=['razon_social', 'rif', 'actualizado_en'])
    return empresa
