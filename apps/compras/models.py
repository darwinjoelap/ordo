"""
Órdenes de compra: Borrador → Enviada → (Parcial) → Recibida · o Anulada.
Recibir mercancía crea lotes con `inventario.servicios.ingresar` (queda en el kardex).
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.tenancy import EmpresaModel


class OrdenCompra(EmpresaModel):
    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        ENVIADA = 'ENVIADA', 'Enviada al proveedor'
        PARCIAL = 'PARCIAL', 'Recibida parcialmente'
        RECIBIDA = 'RECIBIDA', 'Recibida'
        ANULADA = 'ANULADA', 'Anulada'

    numero = models.CharField('Número', max_length=30)
    proveedor = models.ForeignKey('proveedores.Proveedor', on_delete=models.PROTECT, related_name='ordenes',
                                  verbose_name='Proveedor')
    estado = models.CharField('Estado', max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    fecha = models.DateField('Fecha', auto_now_add=True)
    fecha_envio = models.DateTimeField('Enviada el', null=True, blank=True)
    notas = models.TextField('Notas para el proveedor', blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Orden de compra'
        verbose_name_plural = 'Órdenes de compra'
        ordering = ['-creado_en', '-pk']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'numero'], name='orden_compra_numero_unico')]

    def __str__(self):
        return f'{self.numero} · {self.proveedor}'

    @property
    def editable(self):
        return self.estado == self.Estado.BORRADOR

    @property
    def recibible(self):
        return self.estado in (self.Estado.ENVIADA, self.Estado.PARCIAL)

    @property
    def css_estado(self):
        return {'BORRADOR': 'secondary', 'ENVIADA': 'primary', 'PARCIAL': 'warning',
                'RECIBIDA': 'success', 'ANULADA': 'dark'}[self.estado]

    def total_usd(self):
        return sum((i.subtotal_usd for i in self.items.all()), Decimal('0'))


class ItemOrdenCompra(EmpresaModel):
    orden = models.ForeignKey(OrdenCompra, on_delete=models.CASCADE, related_name='items')
    producto = models.ForeignKey('inventario.Producto', on_delete=models.PROTECT, related_name='+')
    cantidad_pedida = models.PositiveIntegerField('Cantidad pedida')
    cantidad_recibida = models.PositiveIntegerField('Cantidad recibida', default=0)
    costo_unitario_usd = models.DecimalField('Costo unitario (USD)', max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Ítem de orden de compra'
        verbose_name_plural = 'Ítems de orden de compra'
        ordering = ['producto__nombre']
        base_manager_name = 'todos'
        constraints = [
            models.UniqueConstraint(fields=['orden', 'producto'], name='item_oc_producto_unico'),
            models.CheckConstraint(condition=Q(cantidad_recibida__lte=F('cantidad_pedida')),
                                   name='item_oc_no_recibe_de_mas'),
        ]

    def __str__(self):
        return f'{self.producto} × {self.cantidad_pedida}'

    @property
    def pendiente(self):
        return self.cantidad_pedida - self.cantidad_recibida

    @property
    def subtotal_usd(self):
        return self.cantidad_pedida * self.costo_unitario_usd
