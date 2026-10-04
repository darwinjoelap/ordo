"""
Tareas periódicas de Ordo. En Railway: servicio Cron con este comando.
  python manage.py tareas_programadas            → todo
  python manage.py tareas_programadas --solo tasa
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Vence apartados y actualiza la tasa BCV (para el cron de Railway).'

    def add_arguments(self, parser):
        parser.add_argument('--solo', choices=['apartados', 'tasa'])

    def handle(self, *args, solo=None, **opciones):
        if solo in (None, 'apartados'):
            from apps.ventas.servicios import vencer_apartados
            n = vencer_apartados()
            self.stdout.write(f'Apartados vencidos liberados: {n}')
            from apps.ventas.servicios import limpiar_borradores_vacios
            self.stdout.write(f'Borradores vacíos sin número eliminados: {limpiar_borradores_vacios()}')
        if solo in (None, 'tasa'):
            call_command('actualizar_tasa_bcv', stdout=self.stdout, stderr=self.stderr)
