from django.core.management.base import BaseCommand

from apps.tasas import servicios


class Command(BaseCommand):
    help = 'Consulta la tasa USD del BCV y la registra para hoy.'

    def handle(self, *args, **opciones):
        try:
            tasa = servicios.actualizar_desde_bcv()
        except Exception as e:  # el cron no debe caerse: registra y avisa (Sentry lo captura)
            servicios.log.error('No se pudo actualizar la tasa BCV: %s', e)
            self.stderr.write(self.style.ERROR(f'Tasa BCV no actualizada: {e}'))
            return
        self.stdout.write(self.style.SUCCESS(f'Tasa BCV registrada: {tasa}'))
