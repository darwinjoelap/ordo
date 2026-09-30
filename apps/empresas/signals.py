from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Empresa, PerfilEmpresa


@receiver(post_save, sender=Empresa)
def crear_perfil(sender, instance, created, **kwargs):
    """Toda empresa nueva nace con su perfil de marca."""
    if created:
        PerfilEmpresa.objects.get_or_create(empresa=instance, defaults={'nombre_comercial': instance.nombre})
