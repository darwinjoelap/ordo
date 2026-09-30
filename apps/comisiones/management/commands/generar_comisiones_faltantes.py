from django.core.management.base import BaseCommand

from apps.comisiones.servicios import generar_faltantes


class Command(BaseCommand):
    help = 'Crea la comisión de las ventas validadas que no la tengan (con los porcentajes actuales).'

    def handle(self, *args, **opciones):
        self.stdout.write(self.style.SUCCESS(f'Comisiones creadas: {generar_faltantes()}'))
