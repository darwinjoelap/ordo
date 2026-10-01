"""Falla si algún cambio en los modelos no tiene su migración (evita desplegar con migraciones pendientes).

Se ejecuta en un proceso aparte: así no ve los modelos que definen los propios tests
(p. ej. NotaPrueba en test_fase2), que no deben tener migración.
"""
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class MigracionesTests(SimpleTestCase):
    def test_no_hay_migraciones_pendientes(self):
        r = subprocess.run(
            [sys.executable, 'manage.py', 'makemigrations', '--check', '--dry-run'],
            cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            self.fail('Hay cambios en modelos sin migración. Ejecuta: python manage.py makemigrations\n'
                      + r.stdout + r.stderr)
