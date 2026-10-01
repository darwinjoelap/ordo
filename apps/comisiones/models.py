"""
Comisiones de vendedores.

- El % sale de la tabla del vendedor; si la categoría del producto tiene % propio, manda el de la categoría.
- Base = subtotal del ítem menos el descuento del documento, SIN IVA.
- Se genera UNA Comision por venta al validarla (señal `venta_validada`), con el % congelado por línea.
- Está disponible para liquidar si no está liquidada y (la empresa no exige cobro o la venta está pagada).
- Una devolución de la venta genera un AjusteComision (negativo). Nunca se modifica lo ya liquidado:
  el ajuste se descuenta en la próxima liquidación del vendedor.
- Una Liquidacion agrupa comisiones disponibles de un vendedor hasta una fecha; al pagarla queda cerrada.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.tenancy import EmpresaModel


class PorcentajeVendedor(EmpresaModel):
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    porcentaje = models.DecimalField('Comisión (%)', max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = 'Porcentaje por vendedor'
        verbose_name_plural = 'Porcentajes por vendedor'
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'vendedor'], name='comision_pct_vendedor_unico')]

    def __str__(self):
        return f'{self.vendedor} · {self.porcentaje} %'


class PorcentajeCategoria(EmpresaModel):
    categoria = models.ForeignKey('inventario.Categoria', on_delete=models.CASCADE, related_name='+')
    porcentaje = models.DecimalField('Comisión (%)', max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = 'Excepción por categoría'
        verbose_name_plural = 'Excepciones por categoría'
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'categoria'], name='comision_pct_categoria_unico')]

    def __str__(self):
        return f'{self.categoria} · {self.porcentaje} %'


class Liquidacion(EmpresaModel):
    numero = models.CharField('Número', max_length=30)
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    hasta = models.DateField('Ventas validadas hasta')
    total_usd = models.DecimalField('Total', max_digits=14, decimal_places=2, default=0)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creada_en = models.DateTimeField(default=timezone.now)
    pagada = models.BooleanField('Pagada', default=False)
    anulada = models.BooleanField('Anulada', default=False)
    fecha_pago = models.DateField('Fecha de pago', null=True, blank=True)
    metodo_pago = models.CharField('Método de pago', max_length=40, blank=True)
    referencia = models.CharField('Referencia', max_length=80, blank=True)
    notas = models.TextField('Notas', blank=True)

    class Meta:
        verbose_name = 'Liquidación'
        verbose_name_plural = 'Liquidaciones'
        ordering = ['-creada_en', '-pk']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'numero'], name='liquidacion_numero_unico')]

    def __str__(self):
        return self.numero

    @property
    def estado(self):
        return 'Anulada' if self.anulada else 'Pagada' if self.pagada else 'Por pagar'

    @property
    def css_estado(self):
        return 'secondary' if self.anulada else 'success' if self.pagada else 'warning'


class Comision(EmpresaModel):
    presupuesto = models.OneToOneField('ventas.Presupuesto', on_delete=models.PROTECT, related_name='comision')
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    fecha = models.DateField('Fecha de la venta (validación)')
    base_usd = models.DecimalField('Base (sin IVA)', max_digits=14, decimal_places=2)
    monto_usd = models.DecimalField('Comisión', max_digits=14, decimal_places=2)
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='comisiones')
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Comisión'
        verbose_name_plural = 'Comisiones'
        ordering = ['-fecha', '-pk']
        base_manager_name = 'todos'
        indexes = [models.Index(fields=['empresa', 'vendedor', 'liquidacion'], name='comision_vendedor_liq')]

    def __str__(self):
        return f'{self.presupuesto.numero} · {self.monto_usd}'

    @property
    def porcentaje_efectivo(self):
        return (self.monto_usd / self.base_usd * 100) if self.base_usd else 0


class LineaComision(EmpresaModel):
    comision = models.ForeignKey(Comision, on_delete=models.CASCADE, related_name='lineas')
    item = models.ForeignKey('ventas.ItemPresupuesto', on_delete=models.PROTECT, related_name='+')
    base_usd = models.DecimalField(max_digits=14, decimal_places=2)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    origen = models.CharField(max_length=10, choices=[('VENDEDOR', 'Vendedor'), ('CATEGORIA', 'Categoría')])
    monto_usd = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        base_manager_name = 'todos'
        ordering = ['pk']


class AjusteComision(EmpresaModel):
    """Descuento de comisión por una devolución. Se liquida junto con las comisiones del vendedor."""
    comision = models.ForeignKey(Comision, on_delete=models.PROTECT, related_name='ajustes')
    devolucion = models.OneToOneField('ventas.Devolucion', on_delete=models.PROTECT, related_name='ajuste_comision')
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    fecha = models.DateField('Fecha de la devolución')
    monto_usd = models.DecimalField('Ajuste (negativo)', max_digits=14, decimal_places=2)
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='ajustes')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ajuste de comisión'
        verbose_name_plural = 'Ajustes de comisión'
        ordering = ['-fecha', '-pk']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.devolucion.numero} · {self.monto_usd}'
