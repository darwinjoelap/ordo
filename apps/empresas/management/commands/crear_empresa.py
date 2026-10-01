"""
Alta rápida de una empresa con su Dueño (usuario propio de la empresa).

    python manage.py crear_empresa "BioLife Diagnostics" darwin --password clave [--enlace biolife]
"""
from django.core.management.base import BaseCommand, CommandError

from apps.empresas import plataforma
from apps.empresas.models import Empresa


class Command(BaseCommand):
    help = 'Crea una empresa y su usuario Dueño.'

    def add_arguments(self, parser):
        parser.add_argument('nombre')
        parser.add_argument('usuario_dueno')
        parser.add_argument('--password', help='Clave del Dueño (si no se indica, se genera una temporal).')
        parser.add_argument('--enlace', help='Enlace de la empresa (/enlace/). Por defecto se genera del nombre.')

    def handle(self, nombre, usuario_dueno, password=None, enlace=None, **opciones):
        from django.utils.text import slugify
        from django.core.exceptions import ValidationError
        slug = enlace or slugify(nombre)[:40]
        try:
            slug = plataforma.validar_enlace(slug)
        except ValidationError as e:
            raise CommandError(e.messages[0])
        empresa, dueno, clave = plataforma.crear_empresa({
            'nombre_comercial': nombre, 'slug': slug, 'plan': Empresa.Plan.PRUEBA, 'usuario_dueno': usuario_dueno})
        if password:
            dueno.set_password(password)
            dueno.debe_cambiar_clave = False
            dueno.save(update_fields=['password', 'debe_cambiar_clave'])
            self.stdout.write(f'Usuario creado: {dueno.username}')
        else:
            self.stdout.write(f'Usuario creado: {dueno.username} · clave temporal: {clave}')
        self.stdout.write(self.style.SUCCESS(
            f'Empresa "{empresa}" ({empresa.slug}) creada con dueño {dueno.username}. Enlace: /{empresa.slug}/'))
