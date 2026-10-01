"""
Catálogo e inventario de Ordo (multiempresa).

Basado en BioLifeVentas, con estos cambios:
- Todo hereda de EmpresaModel (aislamiento por empresa).
- Unidades configurables por empresa (antes: lista fija de laboratorio).
- Stock calculado en UNA consulta con `con_stock()` (antes: ~30 consultas por producto).
- Restricciones en BD: nunca stock negativo ni apartado mayor que el existente.
- Los movimientos solo se hacen desde `servicios.py` (con bloqueo de filas).
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Exists, F, IntegerField, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.functional import cached_property

from apps.core.tenancy import EmpresaManager, EmpresaModel, EmpresaQuerySet


class Categoria(EmpresaModel):
    nombre = models.CharField('Nombre', max_length=100)
    descripcion = models.TextField('Descripción', blank=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'nombre'], name='categoria_unica_por_empresa')]

    def __str__(self):
        return self.nombre


class Subcategoria(EmpresaModel):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='subcategorias',
                                  verbose_name='Categoría')
    nombre = models.CharField('Nombre', max_length=100)

    class Meta:
        verbose_name = 'Subcategoría'
        verbose_name_plural = 'Subcategorías'
        ordering = ['categoria__nombre', 'nombre']
        constraints = [models.UniqueConstraint(fields=['categoria', 'nombre'], name='subcategoria_unica')]

    def __str__(self):
        return f'{self.categoria.nombre} → {self.nombre}'


class Marca(EmpresaModel):
    nombre = models.CharField('Nombre', max_length=100)
    activa = models.BooleanField('Activa', default=True)

    class Meta:
        verbose_name = 'Marca'
        verbose_name_plural = 'Marcas'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'nombre'], name='marca_unica_por_empresa')]

    def __str__(self):
        return self.nombre


class Unidad(EmpresaModel):
    nombre = models.CharField('Nombre', max_length=40)
    abreviatura = models.CharField('Abreviatura', max_length=10)

    class Meta:
        verbose_name = 'Unidad de medida'
        verbose_name_plural = 'Unidades de medida'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'abreviatura'], name='unidad_unica_por_empresa')]

    def __str__(self):
        return self.nombre


UNIDADES_INICIALES = [
    ('Unidad', 'UN'), ('Caja', 'CAJA'), ('Kit', 'KIT'), ('Paquete', 'PAQ'),
    ('Frasco', 'FCO'), ('Kilogramo', 'KG'), ('Litro', 'L'), ('Metro', 'M'),
]


# ── Producto ──────────────────────────────────────────────────────────────────

class ProductoQuerySet(EmpresaQuerySet):
    def con_stock(self):
        """
        Anota en UNA consulta: anot_stock_total, anot_stock_apartado, anot_stock_vencido (libre en lotes
        vencidos), anot_stock_disponible (sin apartado ni vencido) y anot_tiene_vencidos.
        """
        hoy = timezone.localdate()
        vencidos = Lote.todos.filter(producto=OuterRef('pk'), fecha_vencimiento__lt=hoy, cantidad_actual__gt=0)
        return self.annotate(
            anot_stock_total=Coalesce(Sum('lotes__cantidad_actual'), Value(0), output_field=IntegerField()),
            anot_stock_apartado=Coalesce(Sum('lotes__cantidad_apartada'), Value(0), output_field=IntegerField()),
            anot_stock_vencido=Coalesce(
                Sum(F('lotes__cantidad_actual') - F('lotes__cantidad_apartada'),
                    filter=Q(lotes__fecha_vencimiento__lt=hoy)), Value(0), output_field=IntegerField()),
            anot_tiene_vencidos=Exists(vencidos),
        ).annotate(anot_stock_disponible=F('anot_stock_total') - F('anot_stock_apartado') - F('anot_stock_vencido'))

    def buscar(self, texto):
        texto = (texto or '').strip()
        if not texto:
            return self
        return self.filter(Q(nombre__icontains=texto) | Q(codigo__icontains=texto))


class ProductoManager(EmpresaManager.from_queryset(ProductoQuerySet)):
    pass


class Producto(EmpresaModel):
    codigo = models.CharField('Código', max_length=50)
    nombre = models.CharField('Nombre', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='productos',
                                  verbose_name='Categoría')
    subcategoria = models.ForeignKey(Subcategoria, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='productos', verbose_name='Subcategoría')
    marca = models.ForeignKey(Marca, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='productos', verbose_name='Marca')
    unidad = models.ForeignKey(Unidad, on_delete=models.PROTECT, related_name='productos', verbose_name='Unidad')
    proveedor_habitual = models.ForeignKey('proveedores.Proveedor', on_delete=models.SET_NULL, null=True,
                                           blank=True, related_name='productos', verbose_name='Proveedor habitual')
    maneja_lotes = models.BooleanField('Maneja número de lote', default=False)
    maneja_vencimiento = models.BooleanField('Maneja fecha de vencimiento', default=False)
    precio_costo_usd = models.DecimalField('Costo (USD)', max_digits=12, decimal_places=2, default=Decimal('0.00'))
    precio_venta_usd = models.DecimalField('Precio de venta (USD)', max_digits=12, decimal_places=2,
                                           default=Decimal('0.00'))
    stock_minimo = models.PositiveIntegerField('Stock mínimo', default=0)
    factor_venta_dias = models.DecimalField(
        'Días por unidad vendida', max_digits=8, decimal_places=2, default=Decimal('30.00'),
        help_text='Estimación de rotación: 30 = se vende 1 unidad cada 30 días; 0.5 = 2 unidades por día.')
    activo = models.BooleanField('Activo', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    objects = ProductoManager()

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['nombre']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='producto_codigo_unico_por_empresa')]
        indexes = [models.Index(fields=['empresa', 'activo', 'nombre'], name='producto_empresa_activo_nombre')]

    def __str__(self):
        return f'[{self.codigo}] {self.nombre}'

    # ── Stock: usa anotaciones o lotes precargados; consulta solo como último recurso ──

    def _lotes_precargados(self):
        return (getattr(self, '_prefetched_objects_cache', None) or {}).get('lotes')

    @cached_property
    def stock_total(self):
        if hasattr(self, 'anot_stock_total'):
            return self.anot_stock_total
        lotes = self._lotes_precargados()
        if lotes is not None:
            return sum(l.cantidad_actual for l in lotes)
        return self.lotes.aggregate(t=Sum('cantidad_actual'))['t'] or 0

    @cached_property
    def stock_apartado(self):
        if hasattr(self, 'anot_stock_apartado'):
            return self.anot_stock_apartado
        lotes = self._lotes_precargados()
        if lotes is not None:
            return sum(l.cantidad_apartada for l in lotes)
        return self.lotes.aggregate(t=Sum('cantidad_apartada'))['t'] or 0

    @cached_property
    def stock_vencido(self):
        """Unidades libres en lotes vencidos: no se pueden vender."""
        if hasattr(self, 'anot_stock_vencido'):
            return self.anot_stock_vencido
        hoy = timezone.localdate()
        lotes = self._lotes_precargados()
        if lotes is not None:
            return sum(l.cantidad_actual - l.cantidad_apartada for l in lotes
                       if l.fecha_vencimiento and l.fecha_vencimiento < hoy)
        return sum(l.cantidad_actual - l.cantidad_apartada
                   for l in self.lotes.filter(fecha_vencimiento__lt=hoy))

    @property
    def stock_disponible(self):
        """Lo que se puede vender: sin lo apartado ni lo que está en lotes vencidos."""
        return self.stock_total - self.stock_apartado - self.stock_vencido

    @property
    def alerta_stock_minimo(self):
        return self.stock_disponible <= self.stock_minimo

    @cached_property
    def tiene_lotes_vencidos(self):
        if hasattr(self, 'anot_tiene_vencidos'):
            return bool(self.anot_tiene_vencidos)
        hoy = timezone.localdate()
        lotes = self._lotes_precargados()
        if lotes is not None:
            return any(l.fecha_vencimiento and l.fecha_vencimiento < hoy and l.cantidad_actual > 0 for l in lotes)
        return self.lotes.filter(fecha_vencimiento__lt=hoy, cantidad_actual__gt=0).exists()

    @cached_property
    def dias_estimados(self):
        if self.factor_venta_dias and self.factor_venta_dias > 0:
            return int(Decimal(self.stock_disponible) * self.factor_venta_dias)
        return None

    @cached_property
    def semaforo(self):
        """danger (<15 días o agotado) · warning (15–30) · success (>30) · purple (vencidos)"""
        if self.stock_disponible <= 0:
            return 'danger'
        if self.tiene_lotes_vencidos:
            return 'purple'
        dias = self.dias_estimados
        if dias is None:
            return 'secondary'
        if dias < 15:
            return 'danger'
        if dias <= 30:
            return 'warning'
        return 'success'


# ── Lotes y kardex ────────────────────────────────────────────────────────────

class Lote(EmpresaModel):
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='lotes', verbose_name='Producto')
    numero_lote = models.CharField('Número de lote', max_length=50, blank=True)
    fecha_vencimiento = models.DateField('Vencimiento', null=True, blank=True)
    cantidad_inicial = models.PositiveIntegerField('Cantidad inicial')
    cantidad_actual = models.IntegerField('Cantidad actual')
    cantidad_apartada = models.IntegerField('Cantidad apartada', default=0)
    costo_unitario_usd = models.DecimalField('Costo unitario (USD)', max_digits=12, decimal_places=2)
    proveedor = models.ForeignKey('proveedores.Proveedor', on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='lotes', verbose_name='Proveedor')
    fecha_ingreso = models.DateField('Fecha de ingreso', default=timezone.localdate)
    notas = models.TextField('Notas', blank=True)

    class Meta:
        verbose_name = 'Lote'
        verbose_name_plural = 'Lotes'
        ordering = [F('fecha_vencimiento').asc(nulls_last=True), 'fecha_ingreso', 'pk']
        base_manager_name = 'todos'
        constraints = [
            models.CheckConstraint(condition=Q(cantidad_actual__gte=0), name='lote_actual_no_negativo'),
            models.CheckConstraint(condition=Q(cantidad_apartada__gte=0), name='lote_apartado_no_negativo'),
            models.CheckConstraint(condition=Q(cantidad_apartada__lte=F('cantidad_actual')),
                                   name='lote_apartado_no_supera_actual'),
        ]

    def __str__(self):
        lote = f'Lote {self.numero_lote}' if self.numero_lote else 'Sin lote'
        venc = f' · vence {self.fecha_vencimiento:%d/%m/%Y}' if self.fecha_vencimiento else ''
        return f'{lote}{venc} ({self.cantidad_disponible} disp.)'

    @property
    def cantidad_disponible(self):
        return self.cantidad_actual - self.cantidad_apartada

    @property
    def esta_vencido(self):
        return bool(self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate())

    @property
    def dias_para_vencer(self):
        if self.fecha_vencimiento:
            return (self.fecha_vencimiento - timezone.localdate()).days
        return None


class MovimientoInventario(EmpresaModel):
    """Kardex: toda entrada o salida queda registrada con el saldo resultante del lote."""

    class Tipo(models.TextChoices):
        INGRESO = 'INGRESO', 'Ingreso'
        AJUSTE_POS = 'AJUSTE_POS', 'Ajuste positivo'
        AJUSTE_NEG = 'AJUSTE_NEG', 'Ajuste negativo'
        BAJA_VENC = 'BAJA_VENC', 'Baja por vencimiento'
        APARTADO = 'APARTADO', 'Apartado'
        LIBERACION = 'LIBERACION', 'Liberación de apartado'
        VENTA = 'VENTA', 'Venta'
        DEVOLUCION = 'DEVOLUCION', 'Devolución de cliente'

    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name='movimientos', verbose_name='Lote')
    tipo = models.CharField('Tipo', max_length=12, choices=Tipo.choices)
    cantidad = models.IntegerField('Cantidad', help_text='Positivo = entra, negativo = sale.')
    saldo_actual = models.IntegerField('Saldo del lote')
    saldo_apartado = models.IntegerField('Apartado del lote')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                verbose_name='Usuario')
    referencia_tipo = models.CharField('Referencia', max_length=40, blank=True)
    referencia_id = models.PositiveBigIntegerField('ID de referencia', null=True, blank=True)
    motivo = models.CharField('Motivo', max_length=250, blank=True)
    fecha = models.DateTimeField('Fecha', auto_now_add=True)

    class Meta:
        verbose_name = 'Movimiento de inventario'
        verbose_name_plural = 'Movimientos de inventario'
        ordering = ['-fecha', '-pk']
        base_manager_name = 'todos'
        indexes = [models.Index(fields=['lote', '-fecha'], name='movimiento_lote_fecha')]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.cantidad:+d} · {self.lote.producto.codigo}'


class ImportacionProductos(EmpresaModel):
    """Archivo subido para importar productos: guarda el contenido entre 'validar' y 'confirmar', y deja historial."""

    class Estado(models.TextChoices):
        CON_ERRORES = 'ERRORES', 'Con errores'
        VALIDADA = 'VALIDADA', 'Lista para importar'
        APLICADA = 'APLICADA', 'Importada'

    nombre_archivo = models.CharField('Archivo', max_length=200)
    contenido = models.BinaryField('Contenido')
    estado = models.CharField('Estado', max_length=10, choices=Estado.choices)
    resumen = models.JSONField('Resumen', default=dict)
    errores = models.JSONField('Errores', default=list)
    avisos = models.JSONField('Avisos', default=list)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    aplicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Importación de productos'
        verbose_name_plural = 'Importaciones de productos'
        ordering = ['-creado_en']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.nombre_archivo} ({self.get_estado_display()})'
