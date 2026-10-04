from django.db import migrations, models


def a_por_pagar(apps, schema_editor):
    """Las ventas que estaban «Por validar» SIN pago registrado pasan a «Por pagar» (ya no van en la cola de validar)."""
    Presupuesto = apps.get_model('ventas', 'Presupuesto')
    Presupuesto._base_manager.filter(estado='POR_VALIDAR', pagado=False).update(estado='POR_PAGAR')


def a_por_validar(apps, schema_editor):
    Presupuesto = apps.get_model('ventas', 'Presupuesto')
    Presupuesto._base_manager.filter(estado='POR_PAGAR').update(estado='POR_VALIDAR')


class Migration(migrations.Migration):

    dependencies = [('ventas', '0005_datos_del_pago')]

    operations = [
        migrations.AlterField(
            model_name='presupuesto',
            name='estado',
            field=models.CharField(
                choices=[('BORRADOR', 'Borrador'), ('EMITIDO', 'Emitido'), ('APARTADO', 'Apartado'),
                         ('POR_PAGAR', 'Por pagar'), ('POR_VALIDAR', 'Por validar'), ('VALIDADA', 'Venta validada'),
                         ('RECHAZADA', 'Rechazada'), ('VENCIDO', 'Apartado vencido'), ('CANCELADO', 'Cancelado'),
                         ('DEVUELTA', 'Devuelta')],
                default='BORRADOR', max_length=12, verbose_name='Estado'),
        ),
        migrations.RunPython(a_por_pagar, a_por_validar),
    ]
