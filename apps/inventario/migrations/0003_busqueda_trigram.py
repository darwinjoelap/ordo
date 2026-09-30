"""
Búsqueda rápida por nombre y código con pg_trgm (solo PostgreSQL).
En SQLite (desarrollo local) no hace nada.
"""
from django.db import migrations


def crear(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    schema_editor.execute('CREATE INDEX IF NOT EXISTS producto_nombre_trgm ON inventario_producto '
                          'USING gin (nombre gin_trgm_ops)')
    schema_editor.execute('CREATE INDEX IF NOT EXISTS producto_codigo_trgm ON inventario_producto '
                          'USING gin (codigo gin_trgm_ops)')


def borrar(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('DROP INDEX IF EXISTS producto_nombre_trgm')
    schema_editor.execute('DROP INDEX IF EXISTS producto_codigo_trgm')


class Migration(migrations.Migration):
    dependencies = [('inventario', '0002_initial')]
    operations = [migrations.RunPython(crear, borrar)]
