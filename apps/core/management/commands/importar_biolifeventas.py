"""
python manage.py importar_biolifeventas biolifeventas_export.json --empresa biolife [--simular] [--vaciar]

Primero SIEMPRE con --simular: hace todo, muestra la verificación y no guarda nada.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.core.migracion_biolife import ErrorMigracion, Importador
from apps.empresas.models import Empresa


class Command(BaseCommand):
    help = 'Importa la exportación de BioLifeVentas (scripts/biolifeventas_exportar.py) en una empresa de Ordo.'

    def add_arguments(self, parser):
        parser.add_argument('archivo')
        parser.add_argument('--empresa', required=True, help='Enlace (slug) de la empresa en Ordo, p. ej. biolife')
        parser.add_argument('--simular', action='store_true', help='Hace todo y revierte: no guarda nada')
        parser.add_argument('--vaciar', action='store_true',
                            help='Borra antes los datos de negocio de la empresa (productos, clientes, documentos)')

    def handle(self, archivo, empresa, simular, vaciar, **opciones):
        e = Empresa.objects.filter(slug=empresa).first()
        if e is None:
            raise CommandError(f'No existe la empresa con enlace "{empresa}".')
        try:
            with open(archivo, encoding='utf-8') as f:
                datos = json.load(f)
        except (OSError, ValueError) as ex:
            raise CommandError(f'No se pudo leer {archivo}: {ex}')
        try:
            imp = Importador(datos, e).ejecutar(simular=simular, vaciar=vaciar)
        except ErrorMigracion as ex:
            raise CommandError(str(ex))

        self.stdout.write(self.style.MIGRATE_HEADING(f'\nMigración BioLifeVentas → {e.nombre}'
                                                     f'{" (SIMULACIÓN)" if simular else ""}'))
        for k, n in sorted(imp.conteo.items()):
            self.stdout.write(f'  {k}: {n}')
        self.stdout.write(self.style.MIGRATE_HEADING('\nVerificación (BioLifeVentas → Ordo)'))
        for nombre, antes, despues, ok in imp.verificacion:
            marca = self.style.SUCCESS('OK ') if ok else self.style.ERROR('DIF')
            self.stdout.write(f'  {marca} {nombre}: {antes} → {despues}')
        if imp.avisos:
            self.stdout.write(self.style.MIGRATE_HEADING('\nAvisos'))
            for a in imp.avisos:
                self.stdout.write(f'  - {a}')
        if imp.ok:
            self.stdout.write(self.style.SUCCESS('\nTodo cuadra.' + (' Ejecuta sin --simular para guardar.' if simular else '')))
        else:
            self.stdout.write(self.style.WARNING('\nHay diferencias: revísalas antes de migrar en producción.'))
