from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.empresas.models import Empresa

from .models import UNIDADES_INICIALES, Unidad


@receiver(post_save, sender=Empresa)
def unidades_iniciales(sender, instance, created, **kwargs):
    """Cada empresa nueva arranca con unidades de medida comunes (editables)."""
    if created:
        Unidad.todos.bulk_create(
            [Unidad(empresa=instance, nombre=n, abreviatura=a) for n, a in UNIDADES_INICIALES],
            ignore_conflicts=True,
        )
