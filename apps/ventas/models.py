"""
Presupuestos y ventas.

Un Presupuesto recorre estos estados (la "venta" es el mismo documento validado):

  BORRADOR → EMITIDO → APARTADO → [POR_PAGAR →] POR_VALIDAR → VALIDADA
  (POR_PAGAR solo con «validar ventas» activo: confirmada sin pago registrado; a POR_VALIDAR entra SOLO pagada)
                 ↘         ↘            ↘ RECHAZADA (con motivo; vuelve a APARTADO o se libera)
                  CANCELADO  VENCIDO (apartado sin confirmar a tiempo)

  VALIDADA → (devoluciones parciales: sigue VALIDADA con `devuelto_usd`) → DEVUELTA (se devolvió todo)

- APARTADO reserva stock por lote (FEFO) en `Reserva`.
- VALIDADA descuenta el stock y es lo único que cuenta en reportes y comisiones.
- Si la empresa no exige validación, confirmar pasa directo a VALIDADA.
- Una Devolucion (DV-AAAA-00001) revierte unidades de una venta validada: el stock vuelve al lote
  (si se elige), la comisión recibe un ajuste negativo y puede registrarse el reembolso.
- Los totales se guardan en columnas (snapshot) al cambiar los ítems: reportes rápidos con Sum().
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.tenancy import EmpresaModel

D2 = Decimal('0.01')


def redondear(valor):
    return Decimal(valor).quantize(D2, rounding=ROUND_HALF_UP)


def desglose_bs(p, items):
    """
    Montos en Bs como se facturan (igual que BioLifeVentas): el precio unitario en Bs se redondea primero y
    los subtotales, descuento, IVA y total salen de esos precios. Así la tabla del PDF y los totales cuadran.
    """
    if not p.tasa_bs:
        return None
    lineas = {i.pk: redondear(redondear(i.precio_usd * p.tasa_bs) * i.cantidad) for i in items}
    subtotal = sum(lineas.values(), Decimal('0'))
    m = partir_iva(subtotal, sum((lineas[i.pk] for i in items if i.exento_iva), Decimal('0')), p.descuento_pct, p.iva_pct)
    return {'lineas': lineas, 'subtotal': subtotal, **m}


def partir_iva(subtotal, subtotal_exento, descuento_pct, iva_pct):
    """
    Reparte un subtotal entre lo exento (E) y la base imponible. El descuento se aplica por igual a ambos.
    El IVA se calcula SOLO sobre la base imponible. Sirve para USD y para Bs.
    """
    descuento = redondear(subtotal * descuento_pct / 100)
    base = subtotal - descuento
    exento = min(redondear(subtotal_exento * (100 - descuento_pct) / 100), base)
    gravable = base - exento
    iva = redondear(gravable * iva_pct / 100)
    return {'descuento': descuento, 'base': base, 'exento': exento, 'gravable': gravable, 'iva': iva,
            'total': base + iva}


class Presupuesto(EmpresaModel):
    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        EMITIDO = 'EMITIDO', 'Emitido'
        APARTADO = 'APARTADO', 'Apartado'
        POR_PAGAR = 'POR_PAGAR', 'Por cobrar'      # confirmada, sin pago registrado (con «validar ventas» activo)
        POR_VALIDAR = 'POR_VALIDAR', 'Por validar'
        VALIDADA = 'VALIDADA', 'Venta validada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'
        VENCIDO = 'VENCIDO', 'Apartado vencido'
        CANCELADO = 'CANCELADO', 'Cancelado'
        DEVUELTA = 'DEVUELTA', 'Devuelta'

    class MetodoPago(models.TextChoices):
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferencia'
        PAGO_MOVIL = 'PAGO_MOVIL', 'Pago móvil'
        EFECTIVO_USD = 'EFECTIVO_USD', 'Efectivo USD'
        EFECTIVO_BS = 'EFECTIVO_BS', 'Efectivo Bs'
        ZELLE = 'ZELLE', 'Zelle'
        PUNTO = 'PUNTO', 'Punto de venta'
        MIXTO = 'MIXTO', 'Mixto'
        CREDITO = 'CREDITO', 'Crédito'

    # Vacío mientras es un borrador sin guardar: el número se asigna al guardar, emitir, apartar o confirmar
    numero = models.CharField('Número', max_length=30, blank=True, default='')
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, related_name='presupuestos')
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    estado = models.CharField('Estado', max_length=12, choices=Estado.choices, default=Estado.BORRADOR)

    fecha = models.DateField('Fecha', default=timezone.localdate)
    valido_hasta = models.DateField('Válido hasta')
    tasa_bs = models.DecimalField('Tasa Bs/USD', max_digits=14, decimal_places=4, null=True, blank=True,
                                  help_text='Tasa BCV al emitir. Se congela para este documento.')
    iva_pct = models.DecimalField('IVA (%)', max_digits=5, decimal_places=2, default=Decimal('16.00'))
    descuento_pct = models.DecimalField('Descuento (%)', max_digits=5, decimal_places=2, default=Decimal('0.00'))

    # Totales guardados (se recalculan con recalcular_totales)
    subtotal_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    descuento_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    base_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    iva_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Parte de base_usd que corresponde a productos exentos de IVA (E). base_usd − exento_usd = base imponible
    exento_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    requiere_revision = models.BooleanField('Precio fuera de rango', default=False)
    devuelto_usd = models.DecimalField('Devuelto', max_digits=14, decimal_places=2, default=0)

    apartado_hasta = models.DateTimeField('Apartado hasta', null=True, blank=True)
    confirmado_en = models.DateTimeField(null=True, blank=True)
    validado_en = models.DateTimeField(null=True, blank=True)
    validado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='+')
    motivo_rechazo = models.CharField('Motivo del rechazo', max_length=250, blank=True)

    pagado = models.BooleanField('Pagado', default=False)
    fecha_pago = models.DateField('Fecha de pago', null=True, blank=True)
    metodo_pago = models.CharField('Método de pago', max_length=15, choices=MetodoPago.choices, blank=True)
    banco_pago = models.CharField('Banco emisor', max_length=60, blank=True)
    referencia_pago = models.CharField('Referencia', max_length=40, blank=True)
    # Lo que realmente se recibió, si se quiere dejar constancia (puede diferir del total de la venta)
    monto_pago = models.DecimalField('Monto recibido', max_digits=18, decimal_places=2, null=True, blank=True)
    moneda_pago = models.CharField('Moneda del pago', max_length=3, blank=True,
                                   choices=[('USD', 'USD'), ('BS', 'Bs')])
    pago_registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                            related_name='+', verbose_name='Pago registrado por')
    pago_registrado_en = models.DateTimeField('Pago registrado el', null=True, blank=True)
    entregado = models.BooleanField('Entregado', default=False)
    fecha_entrega = models.DateField('Fecha de entrega', null=True, blank=True)

    # Facturación fiscal (la factura se emite fuera de Ordo; aquí se registran sus datos)
    facturado = models.BooleanField('Facturado', default=False)
    numero_factura = models.CharField('N° de factura', max_length=50, blank=True)
    numero_control = models.CharField('N° de control', max_length=50, blank=True)
    fecha_facturacion = models.DateField('Fecha de facturación', null=True, blank=True)

    notas = models.TextField('Notas internas', blank=True)
    condiciones = models.TextField('Condiciones (PDF)', blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Presupuesto / venta'
        verbose_name_plural = 'Presupuestos y ventas'
        ordering = ['-creado_en', '-pk']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'numero'], condition=~models.Q(numero=''),
                                               name='presupuesto_numero_unico')]
        indexes = [
            models.Index(fields=['empresa', 'estado', 'validado_en'], name='venta_estado_fecha'),
            models.Index(fields=['empresa', 'vendedor', 'estado'], name='venta_vendedor_estado'),
            models.Index(fields=['empresa', 'facturado'], name='venta_facturado'),
        ]

    def __str__(self):
        return f'{self.numero_visible} · {self.cliente}'

    @property
    def numero_visible(self):
        return self.numero or 'Borrador sin número'

    # ── Estado ────────────────────────────────────────────────────────────────
    E = Estado

    @property
    def editable(self):
        return self.estado in (self.E.BORRADOR, self.E.EMITIDO)

    CONFIRMADAS = ('POR_PAGAR', 'POR_VALIDAR', 'VALIDADA')

    @property
    def confirmada(self):
        """Venta confirmada: desde aquí corren dos flujos independientes, cobro (finanzas) y entrega (logística)."""
        return self.estado in self.CONFIRMADAS

    @property
    def por_cobrar(self):
        return self.estado == self.E.POR_PAGAR or (self.estado == self.E.VALIDADA and not self.pagado)

    @property
    def por_entregar(self):
        return self.confirmada and not self.entregado

    @property
    def despachable(self):
        """Se puede emitir la nota de despacho: la mercancía ya está apartada o vendida."""
        return self.estado in (self.E.APARTADO, *self.CONFIRMADAS)

    @property
    def es_venta(self):
        """Fue venta validada (aunque luego se haya devuelto)."""
        return self.estado in (self.E.VALIDADA, self.E.DEVUELTA)

    @property
    def neto_usd(self):
        return self.total_usd - self.devuelto_usd

    @property
    def diferencia_pago(self):
        """Recibido − por pagar, en la moneda del pago. None si no se anotó el monto (o es en Bs y no hay tasa)."""
        if self.monto_pago is None:
            return None
        if self.moneda_pago == 'BS':
            return self.monto_pago - self.total_bs if self.total_bs else None
        return self.monto_pago - self.neto_usd

    @property
    def css_estado(self):
        return {'BORRADOR': 'secondary', 'EMITIDO': 'primary', 'APARTADO': 'warning', 'POR_PAGAR': 'warning',
                'POR_VALIDAR': 'info',
                'VALIDADA': 'success', 'RECHAZADA': 'danger', 'VENCIDO': 'dark', 'CANCELADO': 'dark',
                'DEVUELTA': 'secondary'}[self.estado]

    @property
    def apartado_vencido(self):
        return self.estado == self.E.APARTADO and self.apartado_hasta and self.apartado_hasta < timezone.now()


class ItemPresupuesto(EmpresaModel):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='items')
    producto = models.ForeignKey('inventario.Producto', on_delete=models.PROTECT, related_name='+')
    cantidad = models.PositiveIntegerField('Cantidad')
    precio_base_usd = models.DecimalField('Precio de lista', max_digits=12, decimal_places=2)
    precio_usd = models.DecimalField('Precio', max_digits=12, decimal_places=2)
    costo_usd = models.DecimalField('Costo de referencia', max_digits=12, decimal_places=2, default=0)
    fuera_de_rango = models.BooleanField(default=False)
    exento_iva = models.BooleanField('Exento de IVA', default=False)   # copia del producto al agregarlo
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Ítem'
        verbose_name_plural = 'Ítems'
        ordering = ['orden', 'pk']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.producto} × {self.cantidad}'

    @property
    def subtotal_usd(self):
        return redondear(self.cantidad * self.precio_usd)


class Reserva(EmpresaModel):
    """Cuánto de cada lote tiene apartado un ítem (FEFO)."""
    item = models.ForeignKey(ItemPresupuesto, on_delete=models.CASCADE, related_name='reservas')
    lote = models.ForeignKey('inventario.Lote', on_delete=models.PROTECT, related_name='+')
    cantidad = models.PositiveIntegerField()

    class Meta:
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.item.producto.codigo} · {self.lote} · {self.cantidad}'


class Despacho(EmpresaModel):
    """
    Nota de despacho de un presupuesto apartado o de una venta: quién transporta la mercancía y en qué vehículo.
    Una por documento; lleva su mismo número. No es un documento fiscal.
    """
    presupuesto = models.OneToOneField(Presupuesto, on_delete=models.CASCADE, related_name='despacho')
    fecha = models.DateField('Fecha de despacho', default=timezone.localdate)
    direccion_entrega = models.TextField('Dirección de entrega', blank=True)
    transportista = models.CharField('Nombre del transportista', max_length=120)
    cedula = models.CharField('Cédula', max_length=20, blank=True)
    telefono = models.CharField('Teléfono', max_length=30, blank=True)
    empresa_transporte = models.CharField('Empresa de transporte', max_length=120, blank=True)
    vehiculo = models.CharField('Vehículo (marca, modelo, color)', max_length=120, blank=True)
    placa = models.CharField('Placa', max_length=15)
    observaciones = models.TextField('Observaciones', blank=True)
    con_precios = models.BooleanField('Mostrar precios y totales', default=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Nota de despacho'
        verbose_name_plural = 'Notas de despacho'
        base_manager_name = 'todos'

    def __str__(self):
        return f'Despacho {self.presupuesto.numero}'


class Devolucion(EmpresaModel):
    """Devolución (total o parcial) de una venta validada. Los montos usan el precio, descuento, IVA y tasa de la venta."""
    numero = models.CharField('Número', max_length=30)
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.PROTECT, related_name='devoluciones')
    fecha = models.DateField('Fecha', default=timezone.localdate)
    motivo = models.CharField('Motivo', max_length=250)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creada_en = models.DateTimeField(auto_now_add=True)

    subtotal_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    descuento_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    base_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    iva_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_bs = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    reembolsado = models.BooleanField('Reembolsado', default=False)
    reembolso_usd = models.DecimalField('Monto reembolsado (USD)', max_digits=14, decimal_places=2, null=True,
                                        blank=True)
    reembolso_metodo = models.CharField('Método', max_length=15, choices=Presupuesto.MetodoPago.choices, blank=True)
    reembolso_fecha = models.DateField('Fecha del reembolso', null=True, blank=True)
    reembolso_referencia = models.CharField('Referencia', max_length=80, blank=True)

    class Meta:
        verbose_name = 'Devolución'
        verbose_name_plural = 'Devoluciones'
        ordering = ['-creada_en', '-pk']
        base_manager_name = 'todos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'numero'], name='devolucion_numero_unico')]

    def __str__(self):
        return f'{self.numero} · {self.presupuesto.numero}'

    @property
    def reembolso_bs(self):
        if self.reembolso_usd and self.presupuesto.tasa_bs:
            return redondear(self.reembolso_usd * self.presupuesto.tasa_bs)
        return None


class ItemDevolucion(EmpresaModel):
    """Unidades devueltas de un ítem, por lote. `reingresa` = vuelven al inventario (si no, quedan fuera: dañadas)."""
    devolucion = models.ForeignKey(Devolucion, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(ItemPresupuesto, on_delete=models.PROTECT, related_name='devoluciones')
    lote = models.ForeignKey('inventario.Lote', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    cantidad = models.PositiveIntegerField('Cantidad')
    reingresa = models.BooleanField('Vuelve al inventario', default=True)
    subtotal_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Ítem devuelto'
        verbose_name_plural = 'Ítems devueltos'
        ordering = ['pk']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.item.producto} × {self.cantidad}'
