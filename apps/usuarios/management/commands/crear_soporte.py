"""
Crea (o actualiza la contraseña de) la cuenta de SOPORTE de Ordo.

    python manage.py crear_soporte              # usuario «soporte»; pide la contraseña dos veces
    python manage.py crear_soporte --usuario ayuda

- Es una cuenta de plataforma (sin empresa), NO superusuario: no entra a /plataforma/ ni a /admin/.
- Entra por el enlace de cualquier empresa (<slug>.app.ordove.com o /<slug>/) en «Modo soporte», con permisos
  de Dueño y sin ser miembro: no sale en Equipo, vendedores ni en el límite de usuarios.
- La contraseña se escribe al ejecutar el comando; nunca va en el código ni en archivos.
"""
import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.usuarios.models import Usuario, normalizar_usuario


class Command(BaseCommand):
    help = 'Crea o actualiza la cuenta de soporte de Ordo (entra a cualquier empresa sin aparecer en su equipo).'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', default='soporte')
        parser.add_argument('--desactivar', action='store_true', help='Desactiva la cuenta (ya no puede entrar).')

    def handle(self, *args, usuario, desactivar, **opts):
        username = normalizar_usuario(usuario)
        cuenta = Usuario.objects.filter(username=username, empresa_cuenta__isnull=True).first()
        if cuenta and cuenta.is_superuser:
            raise CommandError(f'«{username}» es un superusuario: usa otro nombre para la cuenta de soporte.')
        if desactivar:
            if not cuenta:
                raise CommandError(f'No existe la cuenta de soporte «{username}».')
            cuenta.is_active = False
            cuenta.save(update_fields=['is_active'])
            self.stdout.write(self.style.WARNING(f'Cuenta de soporte «{username}» desactivada.'))
            return

        clave = getpass.getpass('Contraseña: ')
        if clave != getpass.getpass('Repite la contraseña: '):
            raise CommandError('Las contraseñas no coinciden.')
        nueva = cuenta is None
        if nueva:
            cuenta = Usuario(username=username, empresa_cuenta=None, first_name='Soporte', last_name='Ordo')
        try:
            validate_password(clave, cuenta)
        except ValidationError as e:
            raise CommandError(' '.join(e.messages))
        cuenta.set_password(clave)
        cuenta.es_soporte = True
        cuenta.is_active = True
        cuenta.is_staff = False
        cuenta.debe_cambiar_clave = False
        cuenta.save()
        if len(clave) < 12:
            self.stdout.write(self.style.WARNING('Aviso: con menos de 12 caracteres la contraseña es débil para una '
                                                 'cuenta que entra a todas las empresas.'))
        self.stdout.write(self.style.SUCCESS(
            f'Cuenta de soporte «{username}» {"creada" if nueva else "actualizada"}. '
            'Entra por el enlace de cualquier empresa con ese usuario.'))
