"""
Punto de equilibrio mensual.

- CostoFijo: lo que se paga venda o no venda (alquiler, nómina, servicios). Rige desde un mes (`desde`) hasta
  otro (`hasta`, vacío = sigue vigente). Un costo de un solo mes tiene desde == hasta. Ambas fechas son día 1.
- Deduccion: porcentaje que se descuenta de cada venta (impuestos, comisiones bancarias). Es costo VARIABLE:
  crece con lo vendido. Se aplica sobre la venta neta o sobre la utilidad bruta (venta − costo de lo vendido).
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.tenancy import EmpresaModel


class CostoFijo(EmpresaModel):
    nombre = models.CharField('Concepto', max_length=80)
    monto_usd = models.DecimalField('Monto mensual (USD)', max_digits=12, decimal_places=2,
                                    validators=[MinValueValidator(Decimal('0.01'))])
    desde = models.DateField('Desde el mes')
    hasta = models.DateField('Hasta el mes', null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Costo fijo'
        verbose_name_plural = 'Costos fijos'
        ordering = ['nombre', 'pk']
        base_manager_name = 'todos'
        indexes = [models.Index(fields=['empresa', 'desde', 'hasta'], name='costofijo_vigencia')]

    def __str__(self):
        return f'{self.nombre} · {self.monto_usd}'

    @property
    def recurrente(self):
        return self.hasta is None or self.hasta != self.desde


class Deduccion(EmpresaModel):
    class Base(models.TextChoices):
        VENTA = 'VENTA', 'Sobre la venta'
        UTILIDAD = 'UTILIDAD', 'Sobre la utilidad bruta'

    nombre = models.CharField('Concepto', max_length=80)
    porcentaje = models.DecimalField('Porcentaje (%)', max_digits=5, decimal_places=2,
                                     validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('100'))])
    base = models.CharField('Se aplica', max_length=8, choices=Base.choices, default=Base.VENTA)
    activa = models.BooleanField('Activa', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Deducción'
        verbose_name_plural = 'Deducciones'
        ordering = ['nombre', 'pk']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.nombre} · {self.porcentaje} %'
