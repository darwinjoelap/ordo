"""
createsuperuser de Ordo: crea cuentas de PLATAFORMA (sin empresa) y avisa si el usuario ya existe.

El campo `username` no es único global (es único por empresa), por eso el comando original de Django
no verificaba si ya existía y terminaba en un IntegrityError.
"""
from django.contrib.auth.management.commands.createsuperuser import Command as Base


class Command(Base):
    help = 'Crea un superusuario de plataforma (administración de Ordo).'
    username_is_unique = True      # entre cuentas de plataforma lo es: get_by_natural_key busca solo esas
