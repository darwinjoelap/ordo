from django.db import models

from .tenancy import EmpresaModel


class Secuencia(EmpresaModel):
    """Correlativos por empresa, tipo de documento y año (sin carreras: select_for_update)."""
    tipo = models.CharField('Tipo', max_length=10)
    anio = models.PositiveSmallIntegerField('Año')
    ultimo = models.PositiveIntegerField('Último número', default=0)

    class Meta:
        verbose_name = 'Secuencia'
        verbose_name_plural = 'Secuencias'
        constraints = [models.UniqueConstraint(fields=['empresa', 'tipo', 'anio'], name='secuencia_unica')]

    def __str__(self):
        return f'{self.tipo}-{self.anio}: {self.ultimo}'
