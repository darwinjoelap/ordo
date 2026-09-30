"""
Reglas de negocio de presupuestos y ventas. Las vistas solo llaman a estas funciones.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from apps.core.secuencias import siguiente_numero
from apps.core.tenancy import usando_empresa
from apps.inventario import servicios as inventario
from apps.tasas.servicios import tasa_vigente

from .models import ItemPresupuesto, Presupuesto, Reserva, redondear

E = Presupuesto.Estado
CIEN = Decimal('100')

# Se emite cuando una venta queda validada (la Fase 5 genera la comisión aquí)
venta_validada = Signal()


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
    return Presupuesto.objects.create(
        numero=siguiente_numero('P', prefijo=perfil.prefijo_numeracion.upper()),
        cliente=cliente, vendedor=vendedor, fecha=hoy,
        valido_hasta=hoy + timedelta(days=perfil.dias_validez_presupuesto or 7),
        iva_pct=perfil.iva_porcentaje, condiciones=perfil.condiciones_presupuesto,
    )


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
def actualizar_items(p, cambios, quitar, perfil, puede_fijar_precio, descuento_pct=None):
    """cambios: {item_id: (cantidad, precio)} · quitar: [item_id]"""
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
    recalcular_totales(p)


def recalcular_totales(p):
    items = list(ItemPresupuesto.objects.filter(presupuesto=p))
    subtotal = sum((i.subtotal_usd for i in items), Decimal('0'))
    descuento = redondear(subtotal * p.descuento_pct / CIEN)
    base = subtotal - descuento
    iva = redondear(base * p.iva_pct / CIEN)
    total = base + iva
    p.subtotal_usd, p.descuento_usd, p.base_usd, p.iva_usd, p.total_usd = subtotal, descuento, base, iva, total
    p.total_bs = redondear(total * p.tasa_bs) if p.tasa_bs else Decimal('0')
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
    tasa = tasa_vigente()
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
    p.estado, p.confirmado_en, p.motivo_rechazo = E.POR_VALIDAR, timezone.now(), ''
    p.save(update_fields=['estado', 'confirmado_en', 'motivo_rechazo'])
    if not empresa.perfil.requiere_validacion:
        p = validar(p, usuario)
    return p


@transaction.atomic
def validar(p, usuario):
    """Administrador: la venta cuenta. Sale del stock lo apartado."""
    p = _bloquear(p)
    _exigir(p, E.POR_VALIDAR)
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
    _liberar_reservas(p, usuario, 'Cancelado')
    p.estado, p.apartado_hasta = E.CANCELADO, None
    p.save(update_fields=['estado', 'apartado_hasta'])
    return p


@transaction.atomic
def registrar_pago(p, pagado, metodo='', fecha=None):
    _exigir(p, E.POR_VALIDAR, E.VALIDADA)
    p.pagado = pagado
    p.metodo_pago = metodo if pagado else ''
    p.fecha_pago = (fecha or timezone.localdate()) if pagado else None
    p.save(update_fields=['pagado', 'metodo_pago', 'fecha_pago'])
    return p


@transaction.atomic
def registrar_entrega(p, entregado, fecha=None):
    _exigir(p, E.APARTADO, E.POR_VALIDAR, E.VALIDADA)
    p.entregado = entregado
    p.fecha_entrega = (fecha or timezone.localdate()) if entregado else None
    p.save(update_fields=['entregado', 'fecha_entrega'])
    return p


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
