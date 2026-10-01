"""
Panel de pedido: cuánto comprar de cada producto para cubrir N días.

Consumo diario = ventas netas de los últimos 90 días / días de historial   (si hay ventas)
                 días de historial = días desde la primera venta, entre 30 y 90
                 (un producto nuevo no se divide entre 90; uno con 1 semana de ventas no se dispara)
               = 1 / factor_venta_dias                                       (si no hay ventas)
Sugerido        = max(consumo × días de cobertura, stock mínimo) − disponible − en camino
Días            = disponible / consumo
Días con pedido = (disponible + en camino + pedido) / consumo
"""
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Min, Sum
from django.utils import timezone

from apps.inventario.models import MovimientoInventario, Producto

from .models import ItemOrdenCompra, OrdenCompra

DIAS_HISTORIAL = 90
DIAS_HISTORIAL_MINIMO = 30


@dataclass
class Sugerencia:
    producto: Producto
    disponible: int
    en_camino: int
    consumo_diario: float
    dias_restantes: int | None
    sugerido: int
    fuente: str          # 'ventas' | 'estimado'

    @property
    def dias_con_pedido(self):
        if not self.consumo_diario:
            return None
        return int((self.disponible + self.en_camino + self.sugerido) / self.consumo_diario)

    @property
    def clasificacion(self):
        """Categoría › Subcategoría (para agrupar y totalizar)."""
        p = self.producto
        return f'{p.categoria.nombre} › {p.subcategoria.nombre}' if p.subcategoria_id else p.categoria.nombre

    @property
    def costo_estimado(self):
        return self.sugerido * self.producto.precio_costo_usd


def calcular(dias_cobertura=30, proveedor_id=None, solo_necesarios=True, categoria_id=None, subcategoria_id=None,
             marca_id=None):
    desde = timezone.now() - timedelta(days=DIAS_HISTORIAL)
    ventas = {
        r['lote__producto']: -r['t'] for r in
        MovimientoInventario.objects.filter(tipo__in=[MovimientoInventario.Tipo.VENTA,
                                                  MovimientoInventario.Tipo.DEVOLUCION], fecha__gte=desde)
        .values('lote__producto').annotate(t=Sum('cantidad'))
    }
    primera_venta = dict(
        MovimientoInventario.objects.filter(tipo=MovimientoInventario.Tipo.VENTA)
        .values('lote__producto').annotate(f=Min('fecha')).values_list('lote__producto', 'f'))
    ahora = timezone.now()
    en_camino = {
        r['producto']: r['t'] for r in
        ItemOrdenCompra.objects.filter(orden__estado__in=[OrdenCompra.Estado.BORRADOR, OrdenCompra.Estado.ENVIADA,
                                                          OrdenCompra.Estado.PARCIAL])
        .values('producto').annotate(t=Sum(F('cantidad_pedida') - F('cantidad_recibida')))
    }
    productos = (Producto.objects.filter(activo=True).con_stock()
                 .select_related('proveedor_habitual', 'unidad', 'categoria', 'subcategoria').order_by('nombre'))
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
    if subcategoria_id:
        productos = productos.filter(subcategoria_id=subcategoria_id)
    if marca_id:
        productos = productos.filter(marca_id=marca_id)
    if proveedor_id == 'ninguno':
        productos = productos.filter(proveedor_habitual__isnull=True)
    elif proveedor_id:
        productos = productos.filter(proveedor_habitual_id=proveedor_id)

    grupos = OrderedDict()
    for p in productos:
        vendidas = ventas.get(p.pk, 0)
        if vendidas > 0:
            antiguedad = (ahora - primera_venta[p.pk]).days if p.pk in primera_venta else DIAS_HISTORIAL
            base = min(DIAS_HISTORIAL, max(DIAS_HISTORIAL_MINIMO, antiguedad))
            consumo, fuente = vendidas / base, 'ventas'
        elif p.factor_venta_dias and p.factor_venta_dias > 0:
            consumo, fuente = float(Decimal(1) / p.factor_venta_dias), 'estimado'
        else:
            consumo, fuente = 0.0, 'estimado'
        disponible = p.stock_disponible
        camino = en_camino.get(p.pk, 0) or 0
        objetivo = max(math.ceil(consumo * dias_cobertura), p.stock_minimo)
        sugerido = max(0, objetivo - disponible - camino)
        dias = int(disponible / consumo) if consumo > 0 else None
        if solo_necesarios and sugerido == 0:
            continue
        s = Sugerencia(p, disponible, camino, round(consumo, 4), dias, sugerido, fuente)
        grupos.setdefault(p.proveedor_habitual, []).append(s)
    # Dentro de cada proveedor: por clasificación (categoría › subcategoría) y nombre
    for lineas in grupos.values():
        lineas.sort(key=lambda s: _orden_clasificacion(s))
    # Proveedores por nombre; "sin proveedor" al final
    return OrderedDict(sorted(grupos.items(), key=lambda kv: (kv[0] is None, kv[0].nombre if kv[0] else '')))


def _orden_clasificacion(s):
    p = s.producto
    return (p.categoria.nombre.lower(), p.subcategoria.nombre.lower() if p.subcategoria_id else '', p.nombre.lower())


def por_clasificacion(grupos, cantidades=None):
    """
    Junta las líneas de todos los proveedores y las agrupa por clasificación, en orden alfabético.
    cantidades: {producto_id: cantidad} para usar lo que el usuario escribió en vez de lo sugerido
                (solo entran los productos indicados). Sin cantidades, entra todo lo que tenga sugerido > 0.
    Devuelve [(clasificación, [(Sugerencia, cantidad a pedir)], total de unidades)].
    """
    lineas = []
    for ls in grupos.values():
        for s in ls:
            cantidad = s.sugerido if cantidades is None else cantidades.get(s.producto.pk, 0)
            if cantidad > 0:
                lineas.append((s, cantidad))
    lineas.sort(key=lambda par: _orden_clasificacion(par[0]))
    salida = OrderedDict()
    for s, cantidad in lineas:
        salida.setdefault(s.clasificacion, []).append((s, cantidad))
    return [(clas, ls, sum(c for _, c in ls)) for clas, ls in salida.items()]
