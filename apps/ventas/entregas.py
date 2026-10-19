"""
Despacho por almacén (Mi empresa → Comercial → «Gestión de despacho por almacén»).

Almacén ve las ventas confirmadas y registra cada entrega (total o parcial) con quién recibe. Si recibe el
vendedor, la mercancía queda «en tránsito» hasta que él confirme la entrega al cliente. La venta queda
«entregada» cuando todo salió y nada sigue en tránsito.

El stock NO se mueve aquí: sale al validar la venta, como siempre. Esto es la logística y su bitácora.
"""
import base64
from collections import defaultdict

from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from .models import Entrega, ItemEntrega, ItemPresupuesto, Presupuesto
from .servicios import ErrorVenta, _bloquear

E = Presupuesto.Estado
MAX_FIRMA = 300_000          # caracteres del data URL (≈ 220 KB): una firma a mano pesa mucho menos


def activo(empresa):
    return bool(empresa and empresa.perfil.despacho_por_almacen)


def entregado_por_item(p):
    filas = ItemEntrega.objects.filter(entrega__presupuesto=p).values('item_id').annotate(n=Sum('cantidad'))
    return {f['item_id']: f['n'] for f in filas}


def pendientes(p):
    """[(item, entregado, pendiente)] en el orden del documento."""
    ya = entregado_por_item(p)
    salida = []
    for i in ItemPresupuesto.objects.filter(presupuesto=p, producto__tipo='PRODUCTO') \
            .select_related('producto__unidad', 'producto__marca') \
            .order_by('producto__nombre', 'pk'):
        hecho = ya.get(i.pk, 0)
        salida.append((i, hecho, max(i.cantidad - hecho, 0)))
    return salida


def estado(p):
    """PENDIENTE · PARCIAL · EN_TRANSITO · ENTREGADO (para mostrar)."""
    if p.entregado:
        return 'ENTREGADO'
    entregas = list(Entrega.objects.filter(presupuesto=p))
    if not entregas:
        return 'PENDIENTE'
    if all(pend == 0 for _, _, pend in pendientes(p)):
        return 'EN_TRANSITO'
    return 'PARCIAL'


ETIQUETAS = {'PENDIENTE': ('Por despachar', 'warning'), 'PARCIAL': ('Entrega parcial', 'info'),
             'EN_TRANSITO': ('En tránsito (vendedor)', 'primary'), 'ENTREGADO': ('Entregado', 'success')}


def _firma(texto):
    texto = (texto or '').strip()
    if not texto:
        return ''
    if not texto.startswith('data:image/png;base64,') or len(texto) > MAX_FIRMA:
        raise ErrorVenta('La firma no es válida. Vuelve a firmar.')
    try:
        base64.b64decode(texto.split(',', 1)[1], validate=True)
    except Exception:
        raise ErrorVenta('La firma no es válida. Vuelve a firmar.')
    return texto


def _actualizar(p):
    """La venta queda «entregada» si todo salió y nada sigue en tránsito."""
    todo = all(pend == 0 for _, _, pend in pendientes(p))
    transito = Entrega.objects.filter(presupuesto=p, recibe=Entrega.Recibe.VENDEDOR, cliente_en__isnull=True).exists()
    entregado = todo and not transito
    if entregado != p.entregado:
        ultima = Entrega.objects.filter(presupuesto=p).order_by('-entregado_en').first()
        fecha = None
        if entregado and ultima:
            fecha = timezone.localtime(ultima.cliente_en or ultima.entregado_en).date()
        p.entregado, p.fecha_entrega = entregado, fecha
        p.save(update_fields=['entregado', 'fecha_entrega'])
    return p


@transaction.atomic
def registrar(p, usuario, cantidades, recibe, nombre='', cedula='', observaciones='', firma=''):
    """cantidades: {item_id: n}. Valida que no se entregue más de lo pendiente."""
    p = _bloquear(p)
    if p.estado not in Presupuesto.CONFIRMADAS:
        raise ErrorVenta('Solo se despachan ventas confirmadas.')
    if recibe not in Entrega.Recibe.values:
        raise ErrorVenta('Indica quién recibe.')
    pend = {i.pk: (i, n) for i, _, n in pendientes(p)}
    lineas = []
    for item_id, cantidad in cantidades.items():
        if not cantidad:
            continue
        if item_id not in pend:
            raise ErrorVenta('Hay un producto que no es de esta venta.')
        item, maximo = pend[item_id]
        if cantidad < 0 or cantidad > maximo:
            raise ErrorVenta(f'«{item.producto.nombre}»: se pueden entregar como máximo {maximo}.')
        lineas.append((item, cantidad))
    if not lineas:
        raise ErrorVenta('Indica al menos una cantidad a entregar.')
    recibe_usuario = None
    if recibe == Entrega.Recibe.VENDEDOR:
        recibe_usuario = p.vendedor
        nombre = nombre.strip() or p.vendedor.nombre_visible
    nombre, cedula = ' '.join(nombre.split())[:120], ' '.join(cedula.split()).upper()[:20]
    if not nombre:
        raise ErrorVenta('Escribe el nombre de quien recibe.')
    if recibe != Entrega.Recibe.VENDEDOR and not cedula:
        raise ErrorVenta('Escribe la cédula de quien recibe.')
    n = Entrega.objects.filter(presupuesto=p).count() + 1
    entrega = Entrega.objects.create(
        presupuesto=p, numero=f'{p.numero}-E{n}', entregado_por=usuario, recibe=recibe, recibe_usuario=recibe_usuario,
        recibe_nombre=nombre, recibe_cedula=cedula, recibe_firma=_firma(firma),
        observaciones=' '.join((observaciones or '').split())[:300])
    for item, cantidad in lineas:
        ItemEntrega.objects.create(entrega=entrega, item=item, cantidad=cantidad)
    _actualizar(p)
    return entrega


@transaction.atomic
def confirmar_cliente(entrega, usuario, nombre, cedula, firma=''):
    """El vendedor deja constancia de que entregó al cliente lo que recibió de almacén."""
    p = _bloquear(entrega.presupuesto)
    entrega = Entrega.objects.select_for_update().get(pk=entrega.pk)
    if not entrega.en_transito:
        raise ErrorVenta('Esta entrega no está en tránsito.')
    nombre, cedula = ' '.join((nombre or '').split())[:120], ' '.join((cedula or '').split()).upper()[:20]
    if not nombre or not cedula:
        raise ErrorVenta('Escribe el nombre y la cédula de quien recibió en el cliente.')
    entrega.cliente_en, entrega.cliente_nombre, entrega.cliente_cedula = timezone.now(), nombre, cedula
    entrega.cliente_firma, entrega.cliente_confirmado_por = _firma(firma), usuario
    entrega.save()
    _actualizar(p)
    return entrega


@transaction.atomic
def anular(entrega):
    """Corrige un registro equivocado (solo dueño/administrador): las cantidades vuelven a pendientes."""
    p = _bloquear(entrega.presupuesto)
    entrega.delete()
    return _actualizar(p)


def bandeja(qs):
    """Ventas confirmadas aún no entregadas, con su estado de despacho."""
    con_mercancia = ItemPresupuesto.objects.filter(presupuesto=OuterRef('pk'), producto__tipo='PRODUCTO')
    return qs.filter(estado__in=Presupuesto.CONFIRMADAS, entregado=False).filter(Exists(con_mercancia)) \
        .select_related('cliente', 'vendedor') \
        .order_by('confirmado_en', 'pk')


def transito_de(qs):
    return Entrega.objects.filter(presupuesto__in=qs, recibe=Entrega.Recibe.VENDEDOR, cliente_en__isnull=True) \
        .select_related('presupuesto__cliente', 'presupuesto__vendedor')


def resumen_items(entrega):
    agrupado = defaultdict(int)
    for li in ItemEntrega.objects.filter(entrega=entrega).select_related('item__producto__unidad'):
        agrupado[li.item] += li.cantidad
    return list(agrupado.items())
