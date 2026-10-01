"""
Tasa oficial BCV (Bs por USD).
- TasaCambio es GLOBAL: la consulta el cron cada día (o la carga a mano la plataforma).
- TasaEmpresa: la empresa puede cargar su propia tasa del día si el BCV no respondió; solo la afecta a ella.
La que se usa es la más reciente de las dos (`servicios.tasa_vigente(empresa)`).
"""
from django.conf import settings
from django.db import models

from apps.core.tenancy import EmpresaModel


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


class TasaEmpresa(EmpresaModel):
    """
    Tasa cargada a mano por una empresa para un día (cuando el BCV no respondió o la empresa usa otra).
    Solo afecta a esa empresa. Manda sobre la tasa global del mismo día; una tasa global más reciente la reemplaza.
    """
    fecha = models.DateField('Fecha')
    bs_por_usd = models.DecimalField('Bs por USD', max_digits=14, decimal_places=4)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    actualizado_en = models.DateTimeField(auto_now=True)

    fuente = 'EMPRESA'

    class Meta:
        verbose_name = 'Tasa de la empresa'
        verbose_name_plural = 'Tasas de las empresas'
        ordering = ['-fecha']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'fecha'], name='tasa_empresa_fecha_unica')]

    def __str__(self):
        return f'{self.fecha:%d/%m/%Y}: Bs {self.bs_por_usd} (empresa)'

    def get_fuente_display(self):
        return 'Carga manual de la empresa'
