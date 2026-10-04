"""
Reglas de negocio de presupuestos y ventas. Las vistas solo llaman a estas funciones.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from apps.core.secuencias import liberar_numero_presupuesto, siguiente_numero, siguiente_numero_presupuesto
from apps.core.tenancy import usando_empresa
from apps.inventario import servicios as inventario
from apps.tasas.servicios import tasa_vigente

from .models import Devolucion, ItemDevolucion, ItemPresupuesto, Presupuesto, Reserva, desglose_bs, redondear

E = Presupuesto.Estado
CIEN = Decimal('100')

# Se emite cuando una venta queda validada (la Fase 5 genera la comisión aquí)
venta_validada = Signal()
# Se emite al registrar una devolución (comisiones crea el ajuste negativo)
venta_devuelta = Signal()


class ErrorVenta(Exception):
    pass


def _exigir(p, *estados):
    if p.estado not in estados:
        permitidos = ', '.join(E(e).label for e in estados)
        raise ErrorVenta(f'El documento está "{p.get_estado_display()}"; esta acción requiere: {permitidos}.')


def _bloquear(p):
    return Presupuesto.objects.select_for_update().get(pk=p.pk)


# ── Precios ───────────────────────────────────────────────────────────────────

def rango_precio(perfil, producto):
    """(mínimo, máximo) permitidos para el vendedor en modo RANGO. None = sin límite."""
    costo = producto.precio_costo_usd or Decimal('0')
    if perfil.modo_precio != 'RANGO' or costo <= 0:
        return None, None
    minimo = redondear(costo * (1 + perfil.margen_minimo_pct / CIEN))
    maximo = redondear(costo * (1 + perfil.margen_maximo_pct / CIEN)) if perfil.margen_maximo_pct is not None else None
    return minimo, maximo


def resolver_precio(perfil, producto, precio_pedido, puede_fijar_precio):
    """
    Devuelve (precio, fuera_de_rango) según el modo de precios de la empresa.
      FIJO  → el vendedor no puede cambiarlo (se usa el precio de lista).
      LIBRE → cualquier precio ≥ 0.
      RANGO → se acepta, pero si sale del rango queda marcado para revisión.
    Dueño/Administrador (`puede_fijar_precio`) siempre pueden poner cualquier precio.
    """
    base = producto.precio_venta_usd
    if precio_pedido is None or precio_pedido == '':
        return base, False
    precio = redondear(precio_pedido)
    if precio < 0:
        raise ErrorVenta('El precio no puede ser negativo.')
    if perfil.modo_precio == 'FIJO' and not puede_fijar_precio:
        return base, False
    if perfil.modo_precio == 'RANGO' and not puede_fijar_precio:
        minimo, maximo = rango_precio(perfil, producto)
        fuera = (minimo is not None and precio < minimo) or (maximo is not None and precio > maximo)
        return precio, bool(fuera)
    return precio, False


# ── Creación y edición ────────────────────────────────────────────────────────

def crear(cliente, vendedor, empresa):
    perfil = empresa.perfil
    hoy = timezone.localdate()
    # Sin número: se asigna al guardar, emitir, apartar o confirmar (asignar_numero). Así un borrador que se
    # abandona o se queda sin productos no gasta un número del correlativo.
    return Presupuesto.objects.create(
        cliente=cliente, vendedor=vendedor, fecha=hoy,
        valido_hasta=hoy + timedelta(days=perfil.dias_validez_presupuesto or 7),
        iva_pct=perfil.iva_porcentaje, condiciones=perfil.condiciones_presupuesto,
    )


def asignar_numero(p):
    """Da número al presupuesto si aún no lo tiene. Exige productos: un presupuesto vacío no gasta número."""
    if p.numero:
        return p
    if not ItemPresupuesto.objects.filter(presupuesto=p).exists():
        raise ErrorVenta('Agrega al menos un producto antes de guardar el presupuesto.')
    p.numero = siguiente_numero_presupuesto(p.empresa.perfil)
    p.save(update_fields=['numero'])
    return p


@transaction.atomic
def guardar(p):
    """Botón «Guardar»: el borrador con productos recibe su número."""
    p = _bloquear(p)
    _exigir(p, E.BORRADOR, E.EMITIDO)
    return asignar_numero(p)


@transaction.atomic
def eliminar(p):
    """
    Borra por completo un BORRADOR (nunca emitido). Si ya tenía número y era el último de la serie, el número
    se libera para el siguiente presupuesto. Devuelve (número que tenía, quedó_libre).
    """
    p = _bloquear(p)
    _exigir(p, E.BORRADOR)
    numero = p.numero
    libre = liberar_numero_presupuesto(numero) if numero else True
    p.delete()
    return numero, libre


def limpiar_borradores_vacios(horas=24):
    """Cron: borra borradores sin número y sin productos que llevan más de `horas` abandonados (todas las empresas)."""
    limite = timezone.now() - timedelta(hours=horas)
    qs = Presupuesto.todos.filter(estado=E.BORRADOR, numero='', creado_en__lt=limite, items__isnull=True)
    n = qs.count()
    qs.delete()
    return n


@transaction.atomic
def agregar_item(p, producto, cantidad, precio, perfil, puede_fijar_precio):
    _exigir(p, E.BORRADOR, E.EMITIDO)
    if cantidad <= 0:
        raise ErrorVenta('La cantidad debe ser mayor que cero.')
    precio, fuera = resolver_precio(perfil, producto, precio, puede_fijar_precio)
    item = ItemPresupuesto.objects.filter(presupuesto=p, producto=producto).first()
    if item:
        item.cantidad += cantidad
        item.precio_usd, item.fuera_de_rango = precio, fuera
        item.save(update_fields=['cantidad', 'precio_usd', 'fuera_de_rango'])
    else:
        item = ItemPresupuesto.objects.create(
            presupuesto=p, producto=producto, cantidad=cantidad, precio_base_usd=producto.precio_venta_usd,
            precio_usd=precio, costo_usd=producto.precio_costo_usd, fuera_de_rango=fuera,
            orden=ItemPresupuesto.objects.filter(presupuesto=p).count())
    recalcular_totales(p)
    return item


@transaction.atomic
def actualizar_items(p, cambios, quitar, perfil, puede_fijar_precio, descuento_pct=None, sin_iva=None):
    """cambios: {item_id: (cantidad, precio)} · quitar: [item_id] · sin_iva: True = venta exenta, False = IVA de la empresa"""
    _exigir(p, E.BORRADOR, E.EMITIDO)
    for item in ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto'):
        if item.pk in quitar:
            item.delete()
            continue
        if item.pk in cambios:
            cantidad, precio = cambios[item.pk]
            if cantidad <= 0:
                raise ErrorVenta(f'{item.producto.nombre}: la cantidad debe ser mayor que cero.')
            item.precio_usd, item.fuera_de_rango = resolver_precio(perfil, item.producto, precio, puede_fijar_precio)
            item.cantidad = cantidad
            item.save(update_fields=['cantidad', 'precio_usd', 'fuera_de_rango'])
    if descuento_pct is not None:
        if not (0 <= descuento_pct <= 100):
            raise ErrorVenta('El descuento debe estar entre 0 y 100 %.')
        p.descuento_pct = descuento_pct
        p.save(update_fields=['descuento_pct'])
    if sin_iva is not None:
        p.iva_pct = Decimal('0') if sin_iva else perfil.iva_porcentaje
        p.save(update_fields=['iva_pct'])
    recalcular_totales(p)


def recalcular_totales(p):
    items = list(ItemPresupuesto.objects.filter(presupuesto=p))
    subtotal = sum((i.subtotal_usd for i in items), Decimal('0'))
    descuento = redondear(subtotal * p.descuento_pct / CIEN)
    base = subtotal - descuento
    iva = redondear(base * p.iva_pct / CIEN)
    total = base + iva
    p.subtotal_usd, p.descuento_usd, p.base_usd, p.iva_usd, p.total_usd = subtotal, descuento, base, iva, total
    bs = desglose_bs(p, items)
    p.total_bs = bs['total'] if bs else Decimal('0')
    p.requiere_revision = any(i.fuera_de_rango for i in items)
    p.save(update_fields=['subtotal_usd', 'descuento_usd', 'base_usd', 'iva_usd', 'total_usd', 'total_bs',
                          'requiere_revision', 'actualizado_en'])


# ── Flujo ─────────────────────────────────────────────────────────────────────

@transaction.atomic
def emitir(p):
    p = _bloquear(p)
    _exigir(p, E.BORRADOR, E.EMITIDO)
    if not ItemPresupuesto.objects.filter(presupuesto=p).exists():
        raise ErrorVenta('Agrega al menos un producto.')
    asignar_numero(p)
    tasa = tasa_vigente(p.empresa)
    p.tasa_bs = tasa.bs_por_usd if tasa else None
    p.fecha = timezone.localdate()
    p.estado = E.EMITIDO
    p.save(update_fields=['tasa_bs', 'fecha', 'estado'])
    recalcular_totales(p)
    return p


@transaction.atomic
def apartar(p, usuario, empresa):
    """Reserva el stock de todos los ítems (FEFO). Todo o nada."""
    p = _bloquear(p)
    _exigir(p, E.BORRADOR, E.EMITIDO)
    if p.estado == E.BORRADOR:
        p = emitir(p)
    errores = []
    for item in ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto'):
        try:
            for r in inventario.apartar_fefo(item.producto, item.cantidad, usuario, referencia_tipo='Presupuesto',
                                             referencia_id=p.pk, motivo=f'Apartado {p.numero}'):
                Reserva.objects.create(item=item, lote=r.lote, cantidad=r.cantidad)
        except inventario.StockInsuficiente as e:
            errores.append(str(e))
    if errores:
        raise ErrorVenta('No hay stock suficiente: ' + ' · '.join(errores))
    p.estado = E.APARTADO
    p.apartado_hasta = timezone.now() + timedelta(days=empresa.perfil.dias_apartado or 15)
    p.save(update_fields=['estado', 'apartado_hasta'])
    return p


def _liberar_reservas(p, usuario, motivo):
    for r in Reserva.objects.filter(item__presupuesto=p).select_related('lote'):
        inventario.liberar(r.lote, r.cantidad, usuario, referencia_tipo='Presupuesto', referencia_id=p.pk,
                           motivo=f'{motivo} {p.numero}')
    Reserva.objects.filter(item__presupuesto=p).delete()


@transaction.atomic
def desapartar(p, usuario):
    p = _bloquear(p)
    _exigir(p, E.APARTADO)
    _liberar_reservas(p, usuario, 'Desapartado')
    p.estado, p.apartado_hasta = E.EMITIDO, None
    p.save(update_fields=['estado', 'apartado_hasta'])
    return p


@transaction.atomic
def confirmar(p, usuario, empresa):
    """El vendedor confirma la venta. Si hace falta, primero aparta el stock."""
    p = _bloquear(p)
    if p.estado in (E.BORRADOR, E.EMITIDO):
        p = apartar(p, usuario, empresa)
    _exigir(p, E.APARTADO)
    p.confirmado_en, p.motivo_rechazo = timezone.now(), ''
    if not empresa.perfil.requiere_validacion:
        # Sin validación: la venta cuenta de una vez y queda por cobrar hasta registrar el pago
        p.estado = E.POR_VALIDAR
        p.save(update_fields=['estado', 'confirmado_en', 'motivo_rechazo'])
        return validar(p, usuario, exigir_pago=False)
    # Con validación: a la cola de «Por validar» entra SOLO con el pago registrado; si no, queda «Por pagar»
    p.estado = E.POR_VALIDAR if p.pagado else E.POR_PAGAR
    p.save(update_fields=['estado', 'confirmado_en', 'motivo_rechazo'])
    return p


@transaction.atomic
def desconfirmar(p, usuario, empresa):
    """Una venta «Por pagar» que no se va a cobrar vuelve a Apartado (desde ahí se puede liberar o cancelar)."""
    p = _bloquear(p)
    _exigir(p, E.POR_PAGAR)
    if p.entregado:
        raise ErrorVenta('Ya está marcada como entregada: desmarca la entrega antes de devolverla a apartado.')
    p.estado = E.APARTADO
    p.apartado_hasta = timezone.now() + timedelta(days=empresa.perfil.dias_apartado or 15)
    p.save(update_fields=['estado', 'apartado_hasta'])
    return p


@transaction.atomic
def validar(p, usuario, exigir_pago=True):
    """Administrador: la venta cuenta. Sale del stock lo apartado. Solo se valida una venta con pago registrado."""
    p = _bloquear(p)
    if p.estado == E.POR_PAGAR:
        raise ErrorVenta('Esta venta está por pagar: registra el pago antes de validarla.')
    _exigir(p, E.POR_VALIDAR)
    if exigir_pago and not p.pagado:
        raise ErrorVenta('Registra el pago antes de validar la venta.')
    for r in Reserva.objects.filter(item__presupuesto=p).select_related('lote'):
        inventario.descontar_apartado(r.lote, r.cantidad, usuario, referencia_tipo='Venta', referencia_id=p.pk,
                                      motivo=f'Venta {p.numero}')
    p.estado, p.validado_en, p.validado_por = E.VALIDADA, timezone.now(), usuario
    p.save(update_fields=['estado', 'validado_en', 'validado_por'])
    venta_validada.send(sender=Presupuesto, presupuesto=p, usuario=usuario)
    return p


@transaction.atomic
def rechazar(p, usuario, motivo, devolver_a_apartado=True, empresa=None):
    p = _bloquear(p)
    _exigir(p, E.POR_VALIDAR)
    if not (motivo or '').strip():
        raise ErrorVenta('Indica el motivo del rechazo.')
    p.motivo_rechazo = motivo.strip()[:250]
    if devolver_a_apartado:
        p.estado = E.APARTADO
        dias = empresa.perfil.dias_apartado if empresa else 15
        p.apartado_hasta = timezone.now() + timedelta(days=dias)
    else:
        _liberar_reservas(p, usuario, 'Rechazada')
        p.estado, p.apartado_hasta = E.RECHAZADA, None
    p.save(update_fields=['estado', 'motivo_rechazo', 'apartado_hasta'])
    return p


@transaction.atomic
def cancelar(p, usuario):
    p = _bloquear(p)
    _exigir(p, E.BORRADOR, E.EMITIDO, E.APARTADO, E.RECHAZADA)
    if not p.numero:
        raise ErrorVenta('Este borrador aún no tiene número: elimínalo en lugar de cancelarlo.')
    _liberar_reservas(p, usuario, 'Cancelado')
    p.estado, p.apartado_hasta = E.CANCELADO, None
    p.save(update_fields=['estado', 'apartado_hasta'])
    return p


@transaction.atomic
def registrar_pago(p, pagado, metodo='', fecha=None, banco='', referencia='', monto=None, moneda='', usuario=None):
    """
    Marca la venta como pagada (o no). banco, referencia y monto recibido son opcionales: sirven para dejar
    constancia del pago; el monto puede diferir del total y la diferencia queda a la vista.
    """
    p = _bloquear(p)
    _exigir(p, E.POR_PAGAR, E.POR_VALIDAR, E.VALIDADA)
    if pagado and monto is not None:
        if monto <= 0:
            raise ErrorVenta('El monto recibido debe ser mayor que cero.')
        if moneda not in ('USD', 'BS'):
            raise ErrorVenta('Indica si el monto recibido es en USD o en Bs.')
    p.pagado = pagado
    p.metodo_pago = metodo if pagado else ''
    p.fecha_pago = (fecha or timezone.localdate()) if pagado else None
    p.banco_pago = (banco or '').strip()[:60] if pagado else ''
    p.referencia_pago = (referencia or '').strip()[:40] if pagado else ''
    p.monto_pago = redondear(monto) if pagado and monto is not None else None
    p.moneda_pago = moneda if pagado and monto is not None else ''
    p.pago_registrado_por = usuario if pagado else None
    p.pago_registrado_en = timezone.now() if pagado else None
    # El pago mueve la venta entre bandejas: pagada → «Por validar»; se quita el pago → vuelve a «Por pagar»
    if p.estado == E.POR_PAGAR and pagado:
        p.estado = E.POR_VALIDAR
    elif p.estado == E.POR_VALIDAR and not pagado:
        p.estado = E.POR_PAGAR
    p.save(update_fields=['pagado', 'metodo_pago', 'fecha_pago', 'banco_pago', 'referencia_pago', 'monto_pago',
                          'moneda_pago', 'estado', 'pago_registrado_por', 'pago_registrado_en'])
    # Si la empresa ya no exige validación, una venta que quedó «Por pagar» se valida sola al cobrarla
    if p.estado == E.POR_VALIDAR and usuario is not None and not p.empresa.perfil.requiere_validacion:
        p = validar(p, usuario)
    return p


@transaction.atomic
def registrar_entrega(p, entregado, fecha=None):
    _exigir(p, E.APARTADO, E.POR_PAGAR, E.POR_VALIDAR, E.VALIDADA)     # entregar no cambia la bandeja
    p.entregado = entregado
    p.fecha_entrega = (fecha or timezone.localdate()) if entregado else None
    p.save(update_fields=['entregado', 'fecha_entrega'])
    return p


@transaction.atomic
def registrar_facturacion(p, facturado, numero_factura='', numero_control='', fecha=None):
    """Datos de la factura fiscal de una venta validada (o devuelta, para consulta y corrección)."""
    p = _bloquear(p)
    _exigir(p, E.VALIDADA, E.DEVUELTA)
    numero_factura, numero_control = (numero_factura or '').strip()[:50], (numero_control or '').strip()[:50]
    if facturado:
        if not numero_factura:
            raise ErrorVenta('Indica el número de factura.')
        repetida = (Presupuesto.objects.filter(facturado=True, numero_factura__iexact=numero_factura)
                    .exclude(pk=p.pk).first())
        if repetida:
            raise ErrorVenta(f'La factura {numero_factura} ya está registrada en la venta {repetida.numero}.')
        p.facturado, p.numero_factura, p.numero_control = True, numero_factura, numero_control
        p.fecha_facturacion = fecha or timezone.localdate()
    else:
        p.facturado, p.numero_factura, p.numero_control, p.fecha_facturacion = False, '', '', None
    p.save(update_fields=['facturado', 'numero_factura', 'numero_control', 'fecha_facturacion'])
    return p


# ── Devoluciones ──────────────────────────────────────────────────────────────

def devuelto_por_item(p):
    """{item_id: unidades ya devueltas} de una venta."""
    from django.db.models import Sum
    return {r['item_id']: r['t'] for r in
            ItemDevolucion.objects.filter(item__presupuesto=p).values('item_id').annotate(t=Sum('cantidad'))}


def _lotes_para_devolver(item, cantidad):
    """
    Reparte `cantidad` entre los lotes de donde salió el ítem (empieza por el último que se tomó).
    Ventas sin reservas (p. ej. migradas): todo al lote más reciente del producto, o None si no tiene lotes.
    """
    from django.db.models import Sum
    from apps.inventario.models import Lote
    previas = {r['lote_id']: r['t'] for r in
               ItemDevolucion.objects.filter(item=item).values('lote_id').annotate(t=Sum('cantidad'))}
    reparto, pendiente = [], cantidad
    for r in Reserva.objects.filter(item=item).select_related('lote').order_by('-pk'):
        libre = r.cantidad - previas.get(r.lote_id, 0)
        tomar = min(libre, pendiente)
        if tomar > 0:
            reparto.append((r.lote, tomar))
            pendiente -= tomar
        if not pendiente:
            break
    if pendiente:
        lote = Lote.objects.filter(producto=item.producto).order_by('-fecha_ingreso', '-pk').first()
        reparto.append((lote, pendiente))
    return reparto


def _totales_devolucion(p, subtotal, completa):
    """Montos de la devolución con el descuento, IVA y tasa de la venta. Si completa la venta, cierra al centavo."""
    if completa:
        from django.db.models import Sum
        previas = Devolucion.objects.filter(presupuesto=p).aggregate(
            s=Sum('subtotal_usd'), d=Sum('descuento_usd'), b=Sum('base_usd'), i=Sum('iva_usd'), t=Sum('total_usd'),
            bs=Sum('total_bs'))
        cero = Decimal('0')
        return {'subtotal_usd': p.subtotal_usd - (previas['s'] or cero),
                'descuento_usd': p.descuento_usd - (previas['d'] or cero),
                'base_usd': p.base_usd - (previas['b'] or cero), 'iva_usd': p.iva_usd - (previas['i'] or cero),
                'total_usd': p.total_usd - (previas['t'] or cero), 'total_bs': p.total_bs - (previas['bs'] or cero)}
    descuento = redondear(subtotal * p.descuento_pct / CIEN)
    base = subtotal - descuento
    iva = redondear(base * p.iva_pct / CIEN)
    total = base + iva
    return {'subtotal_usd': subtotal, 'descuento_usd': descuento, 'base_usd': base, 'iva_usd': iva,
            'total_usd': total, 'total_bs': redondear(total * p.tasa_bs) if p.tasa_bs else Decimal('0')}


def _validar_reembolso(reembolso, total):
    if not reembolso:
        return {}
    monto = reembolso.get('monto_usd')
    monto = total if monto in (None, '') else Decimal(monto)
    if monto <= 0:
        raise ErrorVenta('El monto del reembolso debe ser mayor que cero.')
    if monto > total:
        raise ErrorVenta(f'El reembolso no puede superar el total devuelto ({total} USD).')
    if not reembolso.get('metodo'):
        raise ErrorVenta('Indica el método del reembolso.')
    return {'reembolsado': True, 'reembolso_usd': monto, 'reembolso_metodo': reembolso['metodo'],
            'reembolso_fecha': reembolso.get('fecha') or timezone.localdate(),
            'reembolso_referencia': (reembolso.get('referencia') or '')[:80]}


@transaction.atomic
def devolver(p, usuario, lineas, motivo, fecha=None, reembolso=None):
    """
    Devolución total o parcial de una venta validada.
      lineas: {item_id: (cantidad, reingresa)}  ·  reembolso: {'monto_usd', 'metodo', 'fecha', 'referencia'} o None
    El stock vuelve al lote de donde salió (si reingresa). Si se devuelve todo, la venta queda DEVUELTA.
    """
    p = _bloquear(p)
    _exigir(p, E.VALIDADA)
    motivo = (motivo or '').strip()
    if not motivo:
        raise ErrorVenta('Indica el motivo de la devolución.')
    items = {i.pk: i for i in ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto')}
    ya = devuelto_por_item(p)
    pedidas = {}
    for item_id, (cantidad, reingresa) in lineas.items():
        item = items.get(int(item_id))
        if item is None or not cantidad:
            continue
        if cantidad < 0:
            raise ErrorVenta('Las cantidades no pueden ser negativas.')
        maximo = item.cantidad - ya.get(item.pk, 0)
        if cantidad > maximo:
            raise ErrorVenta(f'"{item.producto.nombre}": se pueden devolver como máximo {maximo}.')
        pedidas[item.pk] = (cantidad, bool(reingresa))
    if not pedidas:
        raise ErrorVenta('Indica al menos una cantidad a devolver.')

    completa = all(ya.get(i.pk, 0) + pedidas.get(i.pk, (0,))[0] == i.cantidad for i in items.values())
    subtotal = sum((redondear(cant * items[i].precio_usd) for i, (cant, _) in pedidas.items()), Decimal('0'))
    montos = _totales_devolucion(p, subtotal, completa)
    datos_reembolso = _validar_reembolso(reembolso, montos['total_usd'])

    perfil = p.empresa.perfil
    dev = Devolucion.objects.create(
        numero=siguiente_numero('DV', prefijo=(perfil.prefijo_numeracion or '').upper()),
        presupuesto=p, fecha=fecha or timezone.localdate(), motivo=motivo[:250], creada_por=usuario,
        **montos, **datos_reembolso)
    for item_id, (cantidad, reingresa) in pedidas.items():
        item = items[item_id]
        for lote, cant in _lotes_para_devolver(item, cantidad):
            if reingresa and lote is None:
                raise ErrorVenta(f'"{item.producto.nombre}" no tiene lotes: registra un ingreso o marca que no vuelve.')
            ItemDevolucion.objects.create(devolucion=dev, item=item, lote=lote, cantidad=cant, reingresa=reingresa,
                                          subtotal_usd=redondear(cant * item.precio_usd))
            if reingresa:
                inventario.reingresar_devolucion(lote, cant, usuario, referencia_tipo='Devolucion',
                                                 referencia_id=dev.pk, motivo=f'Devolución {dev.numero} ({p.numero})')
    p.devuelto_usd += montos['total_usd']
    campos = ['devuelto_usd']
    if completa:
        p.estado = E.DEVUELTA
        campos.append('estado')
    p.save(update_fields=campos)
    venta_devuelta.send(sender=Devolucion, devolucion=dev, usuario=usuario)
    return dev


@transaction.atomic
def registrar_reembolso(dev, monto_usd, metodo, fecha=None, referencia=''):
    """Reembolso registrado después de crear la devolución."""
    dev = Devolucion.objects.select_for_update().get(pk=dev.pk)
    if dev.reembolsado:
        raise ErrorVenta('Esta devolución ya tiene su reembolso registrado.')
    datos = _validar_reembolso({'monto_usd': monto_usd, 'metodo': metodo, 'fecha': fecha, 'referencia': referencia},
                               dev.total_usd)
    for campo, valor in datos.items():
        setattr(dev, campo, valor)
    dev.save(update_fields=list(datos))
    return dev


def vencer_apartados():
    """Tarea programada: libera los apartados vencidos de TODAS las empresas."""
    vencidos = Presupuesto.todos.filter(estado=E.APARTADO, apartado_hasta__lt=timezone.now()).select_related(
        'empresa', 'vendedor')
    total = 0
    for p in vencidos:
        with usando_empresa(p.empresa), transaction.atomic():
            p = _bloquear(p)
            if p.estado != E.APARTADO:
                continue
            _liberar_reservas(p, p.vendedor, 'Vencimiento de apartado')
            p.estado = E.VENCIDO
            p.save(update_fields=['estado'])
            total += 1
    return total
