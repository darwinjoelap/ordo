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
from django.utils import timezone

from .models import Almacen, ItemTraslado, Lote, MovimientoInventario, Producto, Traslado

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
             proveedor=None, notas='', sumar_a_existente=False, almacen=None):
    """
    Ingreso de mercancía. Si el número de lote ya existe para el producto:
      - sin `sumar_a_existente` → LoteExistente (la vista pide confirmación)
      - con `sumar_a_existente` → suma al lote existente
    """
    if producto.es_servicio:
        raise ErrorInventario('Un servicio no tiene inventario: no se le registran ingresos.')
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    if producto.maneja_lotes and not numero_lote:
        raise ErrorInventario('Este producto requiere número de lote.')
    if producto.maneja_vencimiento and not fecha_vencimiento:
        raise ErrorInventario('Este producto requiere fecha de vencimiento.')

    numero_lote = (numero_lote or '').strip()
    existente = None
    if numero_lote:
        existente = Lote.objects.select_for_update().filter(producto=producto, numero_lote=numero_lote,
                                                            almacen=almacen).first()

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
            proveedor=proveedor, notas=notas, almacen=almacen,
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
def apartar_fefo(producto, cantidad, usuario, *, referencia_tipo='', referencia_id=None, motivo='', almacen=None):
    """
    Aparta `cantidad` tomando primero los lotes que vencen antes (FEFO; sin fecha al final; nunca vencidos).
    almacen: si se indica, solo de ese almacén (multialmacén). Devuelve la lista de Reserva(lote, cantidad).
    Todo o nada.
    """
    if producto.es_servicio:          # un servicio no aparta nada: se vende sin stock
        return []
    if cantidad <= 0:
        raise ErrorInventario('La cantidad debe ser mayor que cero.')
    filtro = {'almacen': almacen} if almacen is not None else {}
    lotes = list(
        Lote.objects.select_for_update()
        .filter(producto=producto, cantidad_actual__gt=F('cantidad_apartada'), **filtro)
        .exclude(fecha_vencimiento__lt=timezone.localdate())          # nunca se aparta un lote vencido
        .order_by(F('fecha_vencimiento').asc(nulls_last=True), 'fecha_ingreso', 'pk')
    )
    disponible = sum(l.cantidad_disponible for l in lotes)
    if disponible < cantidad:
        donde = f' en {almacen.nombre}' if almacen is not None else ''
        raise StockInsuficiente(f'"{producto.nombre}": se piden {cantidad}, hay {disponible} disponibles{donde} '
                                '(sin contar lotes vencidos).')

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


# ── Traslados entre almacenes ─────────────────────────────────────────────────

def _lote_en(lote, destino, cantidad):
    """Lote equivalente (mismo producto, número, vencimiento y costo) en el destino; si no existe, se crea."""
    igual = Lote.objects.select_for_update().filter(
        producto_id=lote.producto_id, numero_lote=lote.numero_lote, fecha_vencimiento=lote.fecha_vencimiento,
        costo_unitario_usd=lote.costo_unitario_usd, almacen=destino).exclude(pk=lote.pk).first()
    if igual:
        Lote.objects.filter(pk=igual.pk).update(cantidad_actual=F('cantidad_actual') + cantidad)
        return igual
    return Lote.objects.create(
        producto_id=lote.producto_id, numero_lote=lote.numero_lote, fecha_vencimiento=lote.fecha_vencimiento,
        cantidad_inicial=cantidad, cantidad_actual=cantidad, costo_unitario_usd=lote.costo_unitario_usd,
        proveedor_id=lote.proveedor_id, fecha_ingreso=lote.fecha_ingreso, almacen=destino,
        notas=f'Traslado desde {lote.almacen.nombre if lote.almacen_id else "Sin almacén"}')


@transaction.atomic
def trasladar(origen, destino, lineas, usuario, notas=''):
    """
    Mueve mercancía disponible (no apartada) de un almacén a otro. origen None = «Sin almacén».
    lineas: [(lote, cantidad)]. Todo o nada. Si se mueve un lote completo y sin apartados, el lote cambia de
    almacén (conserva su historia); si es una parte, se divide. Queda en el kardex como salida y entrada.
    """
    from apps.core.secuencias import siguiente_numero
    if destino is None:
        raise ErrorInventario('Elige el almacén destino.')
    if origen is not None and origen.pk == destino.pk:
        raise ErrorInventario('El origen y el destino son el mismo almacén.')
    lineas = [(l, c) for l, c in lineas if c]
    if not lineas:
        raise ErrorInventario('Indica al menos una cantidad a trasladar.')
    traslado = Traslado.objects.create(numero=siguiente_numero('TR'), origen=origen, destino=destino,
                                       usuario=usuario, notas=(notas or '').strip()[:250])
    for lote, cantidad in lineas:
        lote = _bloquear(lote)
        if lote.almacen_id != (origen.pk if origen else None):
            raise ErrorInventario(f'El lote {lote.numero_lote or lote.pk} no está en el almacén de origen.')
        if cantidad < 0 or cantidad > lote.cantidad_disponible:
            raise StockInsuficiente(f'"{lote.producto.nombre}": se pueden trasladar como máximo '
                                    f'{lote.cantidad_disponible} del lote {lote.numero_lote or "sin número"} '
                                    '(lo apartado no se mueve).')
        motivo = f'Traslado {traslado.numero} → {destino.nombre}'
        if cantidad == lote.cantidad_actual and lote.cantidad_apartada == 0:
            _registrar(lote, Tipo.TRASLADO_SAL, -cantidad, usuario, 'Traslado', traslado.pk, motivo)
            Lote.objects.filter(pk=lote.pk).update(almacen=destino)
            destino_lote = lote
            _registrar(destino_lote, Tipo.TRASLADO_ENT, cantidad, usuario, 'Traslado', traslado.pk,
                       f'Traslado {traslado.numero} desde {origen.nombre if origen else "Sin almacén"}')
        else:
            Lote.objects.filter(pk=lote.pk).update(cantidad_actual=F('cantidad_actual') - cantidad)
            _registrar(lote, Tipo.TRASLADO_SAL, -cantidad, usuario, 'Traslado', traslado.pk, motivo)
            destino_lote = _lote_en(lote, destino, cantidad)
            _registrar(destino_lote, Tipo.TRASLADO_ENT, cantidad, usuario, 'Traslado', traslado.pk,
                       f'Traslado {traslado.numero} desde {origen.nombre if origen else "Sin almacén"}')
        ItemTraslado.objects.create(traslado=traslado, producto_id=lote.producto_id, lote_origen=lote,
                                    lote_destino=destino_lote, cantidad=cantidad)
    return traslado


def lotes_trasladables(origen):
    """Lotes con algo disponible en el origen (None = sin almacén)."""
    return (Lote.objects.filter(almacen=origen, cantidad_actual__gt=F('cantidad_apartada'))
            .select_related('producto__unidad').order_by('producto__nombre', F('fecha_vencimiento').asc(nulls_last=True), 'pk'))


def trasladar_todo(origen, destino, usuario):
    """Ponerse a punto: mueve TODO lo disponible del origen (p. ej. «Sin almacén») al destino."""
    lineas = [(l, l.cantidad_disponible) for l in lotes_trasladables(origen)]
    if not lineas:
        raise ErrorInventario('No hay nada disponible para trasladar en el origen.')
    return trasladar(origen, destino, lineas, usuario, 'Traslado completo para poner a punto los almacenes')


def principal():
    return Almacen.objects.filter(activo=True).order_by('-principal', 'pk').first()


def costo_promedio(producto):
    """Costo promedio ponderado del stock actual (para márgenes)."""
    lotes = Lote.objects.filter(producto=producto, cantidad_actual__gt=0)
    total = sum(l.cantidad_actual for l in lotes)
    if not total:
        return producto.precio_costo_usd
    return (sum(l.cantidad_actual * l.costo_unitario_usd for l in lotes) / total).quantize(Decimal('0.01'))
