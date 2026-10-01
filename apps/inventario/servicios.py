"""
Único punto de entrada para mover inventario.

Cada función:
  - corre dentro de transaction.atomic()
  - bloquea las filas de los lotes con select_for_update() (en PostgreSQL)
  - actualiza cantidades con F() (sin leer-modificar-escribir)
  - registra el movimiento en el kardex con el saldo resultante
Las restricciones CHECK de Lote son la última barrera contra el stock negativo.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Lote, MovimientoInventario, Producto

Tipo = MovimientoInventario.Tipo


class ErrorInventario(Exception):
    """Error de negocio con mensaje para el usuario."""


class StockInsuficiente(ErrorInventario):
    pass


class LoteExistente(ErrorInventario):
    def __init__(self, lote):
        self.lote = lote
        super().__init__(f'El lote "{lote.numero_lote}" ya existe con {lote.cantidad_actual} unidades.')


@dataclass
class Reserva:
    lote: Lote
    cantidad: int


def _registrar(lote, tipo, cantidad, usuario, referencia_tipo='', referencia_id=None, motivo=''):
    lote.refresh_from_db(fields=['cantidad_actual', 'cantidad_apartada'])
    return MovimientoInventario.objects.create(
        empresa_id=lote.empresa_id, lote=lote, tipo=tipo, cantidad=cantidad,
        saldo_actual=lote.cantidad_actual, saldo_apartado=lote.cantidad_apartada,
        usuario=usuario, referencia_tipo=referencia_tipo, referencia_id=referencia_id, motivo=motivo[:250],
    )


def _bloquear(lote):
    return Lote.objects.select_for_update().get(pk=lote.pk)


# ── Entradas ──────────────────────────────────────────────────────────────────

@transaction.atomic
def ingresar(producto, cantidad, costo_unitario, usuario, *, numero_lote='', fecha_vencimiento=None,
             proveedor=None, notas='', sumar_a_existente=False):
    """
    Ingreso de mercancía. Si el número de lote ya existe para el producto:
      - sin `sumar_a_existente` → LoteExistente (la vista pide confirmación)
      - con `sumar_a_existente` → suma al lote existente
    """
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    if producto.maneja_lotes and not numero_lote:
        raise ErrorInventario('Este producto requiere número de lote.')
    if producto.maneja_vencimiento and not fecha_vencimiento:
        raise ErrorInventario('Este producto requiere fecha de vencimiento.')

    numero_lote = (numero_lote or '').strip()
    existente = None
    if numero_lote:
        existente = Lote.objects.select_for_update().filter(producto=producto, numero_lote=numero_lote).first()

    if existente and not sumar_a_existente:
        raise LoteExistente(existente)

    if existente:
        Lote.objects.filter(pk=existente.pk).update(
            cantidad_actual=F('cantidad_actual') + cantidad, costo_unitario_usd=costo_unitario)
        lote = existente
        motivo = f'Suma a lote existente. {notas}'.strip()
    else:
        lote = Lote.objects.create(
            producto=producto, numero_lote=numero_lote, fecha_vencimiento=fecha_vencimiento,
            cantidad_inicial=cantidad, cantidad_actual=cantidad, costo_unitario_usd=costo_unitario,
            proveedor=proveedor, notas=notas,
        )
        motivo = notas

    Producto.objects.filter(pk=producto.pk).update(precio_costo_usd=costo_unitario)
    _registrar(lote, Tipo.INGRESO, cantidad, usuario, 'Ingreso', lote.pk, motivo)
    return lote


# ── Ajustes ───────────────────────────────────────────────────────────────────

@transaction.atomic
def ajustar(lote, tipo, cantidad, usuario, motivo):
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    if not (motivo or '').strip():
        raise ErrorInventario('El motivo es obligatorio.')
    lote = _bloquear(lote)
    if tipo == Tipo.AJUSTE_POS:
        delta = cantidad
    elif tipo in (Tipo.AJUSTE_NEG, Tipo.BAJA_VENC):
        if cantidad > lote.cantidad_disponible:
            raise StockInsuficiente(
                f'Solo hay {lote.cantidad_disponible} disponibles en el lote '
                f'({lote.cantidad_apartada} están apartadas).')
        delta = -cantidad
    else:
        raise ErrorInventario('Tipo de ajuste no válido.')
    Lote.objects.filter(pk=lote.pk).update(cantidad_actual=F('cantidad_actual') + delta)
    return _registrar(lote, tipo, delta, usuario, 'Ajuste', None, motivo)


# ── Reservas y ventas (usadas por presupuestos en la Fase 4) ──────────────────

@transaction.atomic
def apartar_fefo(producto, cantidad, usuario, *, referencia_tipo='', referencia_id=None, motivo=''):
    """
    Aparta `cantidad` tomando primero los lotes que vencen antes (FEFO; sin fecha al final).
    Devuelve la lista de Reserva(lote, cantidad). Todo o nada.
    """
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    lotes = list(
        Lote.objects.select_for_update()
        .filter(producto=producto, cantidad_actual__gt=F('cantidad_apartada'))
        .order_by(F('fecha_vencimiento').asc(nulls_last=True), 'fecha_ingreso', 'pk')
    )
    disponible = sum(l.cantidad_disponible for l in lotes)
    if disponible < cantidad:
        raise StockInsuficiente(f'"{producto.nombre}": se piden {cantidad}, hay {disponible} disponibles.')

    reservas, pendiente = [], cantidad
    for lote in lotes:
        if pendiente == 0:
            break
        tomar = min(pendiente, lote.cantidad_disponible)
        Lote.objects.filter(pk=lote.pk).update(cantidad_apartada=F('cantidad_apartada') + tomar)
        _registrar(lote, Tipo.APARTADO, -tomar, usuario, referencia_tipo, referencia_id, motivo)
        reservas.append(Reserva(lote, tomar))
        pendiente -= tomar
    return reservas


@transaction.atomic
def liberar(lote, cantidad, usuario, *, referencia_tipo='', referencia_id=None, motivo=''):
    lote = _bloquear(lote)
    cantidad = min(cantidad, lote.cantidad_apartada)
    if cantidad <= 0:
        return None
    Lote.objects.filter(pk=lote.pk).update(cantidad_apartada=F('cantidad_apartada') - cantidad)
    return _registrar(lote, Tipo.LIBERACION, cantidad, usuario, referencia_tipo, referencia_id, motivo)


@transaction.atomic
def descontar_apartado(lote, cantidad, usuario, *, referencia_tipo='', referencia_id=None, motivo=''):
    """Venta validada: sale del stock lo que estaba apartado."""
    lote = _bloquear(lote)
    if cantidad > lote.cantidad_apartada:
        raise StockInsuficiente(f'El lote solo tiene {lote.cantidad_apartada} apartadas.')
    Lote.objects.filter(pk=lote.pk).update(
        cantidad_actual=F('cantidad_actual') - cantidad,
        cantidad_apartada=F('cantidad_apartada') - cantidad,
    )
    return _registrar(lote, Tipo.VENTA, -cantidad, usuario, referencia_tipo, referencia_id, motivo)


@transaction.atomic
def reingresar_devolucion(lote, cantidad, usuario, *, referencia_tipo='Devolucion', referencia_id=None, motivo=''):
    """Devolución de cliente: las unidades vuelven al lote (kardex DEVOLUCION, positivo)."""
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    lote = _bloquear(lote)
    Lote.objects.filter(pk=lote.pk).update(cantidad_actual=F('cantidad_actual') + cantidad)
    return _registrar(lote, Tipo.DEVOLUCION, cantidad, usuario, referencia_tipo, referencia_id, motivo)


def costo_promedio(producto):
    """Costo promedio ponderado del stock actual (para márgenes)."""
    lotes = Lote.objects.filter(producto=producto, cantidad_actual__gt=0)
    total = sum(l.cantidad_actual for l in lotes)
    if not total:
        return producto.precio_costo_usd
    return (sum(l.cantidad_actual * l.costo_unitario_usd for l in lotes) / total).quantize(Decimal('0.01'))
