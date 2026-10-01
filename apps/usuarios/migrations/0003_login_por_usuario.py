"""
Login por nombre de usuario (único por empresa) en vez de correo.

Datos existentes:
- username = parte del correo antes de la @ (sin repetir dentro de la misma empresa).
- empresa_cuenta = empresa de su primera membresía; los superusuarios quedan como cuentas de plataforma.
"""
import django.contrib.auth.validators
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def llenar(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    Membresia = apps.get_model('empresas', 'Membresia')
    usados = set()
    for u in Usuario.objects.order_by('pk'):
        empresa_id = None
        if not u.is_superuser:
            m = Membresia.objects.filter(usuario_id=u.pk).order_by('pk').first()
            empresa_id = m.empresa_id if m else None
        base = (u.email.split('@')[0] if u.email else f'usuario{u.pk}').strip().lower() or f'usuario{u.pk}'
        nombre, n = base, 2
        while (empresa_id, nombre) in usados:
            nombre, n = f'{base}{n}', n + 1
        usados.add((empresa_id, nombre))
        u.username, u.empresa_cuenta_id = nombre[:60], empresa_id
        u.save(update_fields=['username', 'empresa_cuenta'])


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0002_usuario_debe_cambiar_clave'),
        ('empresas', '0003_empresa_limite_usuarios_empresa_notas'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario', name='empresa_cuenta',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='cuentas', to='empresas.empresa',
                                    verbose_name='Empresa de la cuenta',
                                    help_text='Vacío = cuenta de plataforma (administración de Ordo).'),
        ),
        migrations.AddField(
            model_name='usuario', name='username',
            field=models.CharField(default='', max_length=60, verbose_name='Usuario'),
            preserve_default=False,
        ),
        migrations.RunPython(llenar, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='usuario', name='username',
            field=models.CharField(help_text='Letras, números y . _ - @ (sin espacios). Se guarda en minúsculas.',
                                   max_length=60, verbose_name='Usuario',
                                   validators=[django.contrib.auth.validators.UnicodeUsernameValidator()]),
        ),
        migrations.AlterField(
            model_name='usuario', name='email',
            field=models.EmailField(blank=True, max_length=254, verbose_name='Correo (opcional)'),
        ),
        migrations.AlterModelOptions(
            name='usuario',
            options={'ordering': ['first_name', 'last_name', 'username'], 'verbose_name': 'Usuario',
                     'verbose_name_plural': 'Usuarios'},
        ),
        migrations.AddConstraint(
            model_name='usuario',
            constraint=models.UniqueConstraint(fields=('empresa_cuenta', 'username'), name='usuario_unico_por_empresa'),
        ),
        migrations.AddConstraint(
            model_name='usuario',
            constraint=models.UniqueConstraint(condition=Q(empresa_cuenta__isnull=True), fields=('username',),
                                               name='usuario_plataforma_unico'),
        ),
    ]
