from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.secuencias import siguiente_numero
from apps.inventario import servicios as inventario

from .models import ItemOrdenCompra, OrdenCompra

Estado = OrdenCompra.Estado


class ErrorCompra(Exception):
    pass


@transaction.atomic
def crear_orden(proveedor, usuario, items=(), notas=''):
    """items: [(producto, cantidad, costo)]"""
    orden = OrdenCompra.objects.create(numero=siguiente_numero('OC'), proveedor=proveedor, creado_por=usuario,
                                       notas=notas)
    for producto, cantidad, costo in items:
        agregar_item(orden, producto, cantidad, costo)
    return orden


def agregar_item(orden, producto, cantidad, costo):
    if not orden.editable:
        raise ErrorCompra('Solo se pueden modificar órdenes en borrador.')
    if cantidad <= 0:
        raise ErrorCompra('La cantidad debe ser mayor que cero.')
    item, creado = ItemOrdenCompra.objects.get_or_create(
        orden=orden, producto=producto, defaults={'cantidad_pedida': cantidad, 'costo_unitario_usd': costo})
    if not creado:
        item.cantidad_pedida += cantidad
        item.costo_unitario_usd = costo
        item.save(update_fields=['cantidad_pedida', 'costo_unitario_usd'])
    return item


def cambiar_estado(orden, nuevo):
    permitidos = {
        Estado.BORRADOR: {Estado.ENVIADA, Estado.ANULADA},
        Estado.ENVIADA: {Estado.BORRADOR, Estado.ANULADA},
        Estado.PARCIAL: {Estado.RECIBIDA},          # cerrar aunque falte mercancía
    }
    if nuevo not in permitidos.get(orden.estado, set()):
        raise ErrorCompra(f'No se puede pasar de "{orden.get_estado_display()}" a "{Estado(nuevo).label}".')
    if nuevo == Estado.ENVIADA and not orden.items.exists():
        raise ErrorCompra('Agrega al menos un producto antes de enviar la orden.')
    orden.estado = nuevo
    if nuevo == Estado.ENVIADA:
        orden.fecha_envio = timezone.now()
    orden.save(update_fields=['estado', 'fecha_envio'])


@transaction.atomic
def recibir(orden, recepciones, usuario):
    """
    recepciones: [{'item': ItemOrdenCompra, 'cantidad': int, 'numero_lote': str, 'fecha_vencimiento': date|None,
                   'costo': Decimal}]
    Crea un lote por recepción y actualiza lo recibido. Todo o nada.
    """
    orden = OrdenCompra.objects.select_for_update().get(pk=orden.pk)
    if not orden.recibible:
        raise ErrorCompra('Solo se reciben órdenes enviadas o parciales.')
    recibido = 0
    for r in recepciones:
        cantidad = r['cantidad']
        if not cantidad:
            continue
        item = ItemOrdenCompra.objects.select_for_update().get(pk=r['item'].pk, orden=orden)
        if cantidad > item.pendiente:
            raise ErrorCompra(f'{item.producto.nombre}: se piden recibir {cantidad} y solo faltan {item.pendiente}.')
        try:
            inventario.ingresar(item.producto, cantidad, r['costo'], usuario, numero_lote=r['numero_lote'],
                                fecha_vencimiento=r['fecha_vencimiento'], proveedor=orden.proveedor,
                                notas=f'Recepción {orden.numero}', sumar_a_existente=True)
        except inventario.ErrorInventario as e:
            raise ErrorCompra(f'{item.producto.nombre}: {e}')
        ItemOrdenCompra.objects.filter(pk=item.pk).update(cantidad_recibida=F('cantidad_recibida') + cantidad)
        recibido += cantidad
    if not recibido:
        raise ErrorCompra('Indica al menos una cantidad a recibir.')
    pendiente = sum(i.pendiente for i in ItemOrdenCompra.objects.filter(orden=orden))
    orden.estado = Estado.RECIBIDA if pendiente == 0 else Estado.PARCIAL
    orden.save(update_fields=['estado'])
    return orden
