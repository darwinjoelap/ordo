"""
Alta rápida de una empresa con su Dueño.

    python manage.py crear_empresa "BioLife Diagnostics" dueno@correo.com --password clave
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.empresas.models import Empresa, Membresia, Rol


class Command(BaseCommand):
    help = 'Crea una empresa y asigna (o crea) su usuario Dueño.'

    def add_arguments(self, parser):
        parser.add_argument('nombre')
        parser.add_argument('email_dueno')
        parser.add_argument('--password', help='Solo si el usuario no existe todavía.')

    @transaction.atomic
    def handle(self, nombre, email_dueno, password=None, **opciones):
        Usuario = get_user_model()
        email = email_dueno.lower()
        usuario = Usuario.objects.filter(email=email).first()
        if usuario is None:
            if not password:
                raise CommandError('El usuario no existe: indica --password para crearlo.')
            usuario = Usuario.objects.create_user(email, password)
            self.stdout.write(f'Usuario creado: {email}')
        empresa = Empresa.objects.create(nombre=nombre)
        Membresia.objects.create(usuario=usuario, empresa=empresa, rol=Rol.DUENO)
        self.stdout.write(self.style.SUCCESS(f'Empresa "{empresa}" ({empresa.slug}) creada con dueño {email}.'))
