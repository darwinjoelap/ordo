"""
Tasa oficial BCV (Bs por USD). Es GLOBAL: la misma para todas las empresas.
Se actualiza sola con el comando `actualizar_tasa_bcv`; si falla, el admin de plataforma la carga a mano.
"""
from django.conf import settings
from django.db import models


class TasaCambio(models.Model):
    class Fuente(models.TextChoices):
        BCV = 'BCV', 'BCV automático'
        MANUAL = 'MANUAL', 'Carga manual'

    fecha = models.DateField('Fecha', unique=True)
    bs_por_usd = models.DecimalField('Bs por USD', max_digits=14, decimal_places=4)
    fuente = models.CharField('Fuente', max_length=8, choices=Fuente.choices, default=Fuente.BCV)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tasa de cambio'
        verbose_name_plural = 'Tasas de cambio'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.fecha:%d/%m/%Y}: Bs {self.bs_por_usd}'
