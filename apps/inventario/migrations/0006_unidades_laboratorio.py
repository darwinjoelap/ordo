"""Agrega a las empresas existentes las unidades de laboratorio (Vial, Mililitro, Test, Tubo, Rollo).
No modifica ni borra unidades: solo crea las que falten."""
from django.db import migrations

NUEVAS = [('Vial', 'VIAL'), ('Mililitro', 'ML'), ('Test', 'TEST'), ('Tubo', 'TUBO'), ('Rollo', 'ROLLO')]


def agregar(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    Unidad = apps.get_model('inventario', 'Unidad')
    for empresa_id in Empresa.objects.values_list('pk', flat=True):
        existentes = set(Unidad.objects.filter(empresa_id=empresa_id).values_list('abreviatura', flat=True))
        Unidad.objects.bulk_create([Unidad(empresa_id=empresa_id, nombre=n, abreviatura=a)
                                    for n, a in NUEVAS if a not in existentes])


class Migration(migrations.Migration):
    dependencies = [
        ('inventario', '0005_alter_movimientoinventario_tipo'),
        ('empresas', '0004_alter_membresia_options'),
    ]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
