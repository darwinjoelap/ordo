"""
Panel de pedido: cuánto comprar de cada producto para cubrir N días.

Consumo diario = ventas de los últimos 90 días / 90   (si hay ventas)
               = 1 / factor_venta_dias                (si no hay historial)
Sugerido = max(consumo × días de cobertura, stock mínimo) − disponible − en camino
"""
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

from apps.inventario.models import MovimientoInventario, Producto

from .models import ItemOrdenCompra, OrdenCompra

DIAS_HISTORIAL = 90


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
    def costo_estimado(self):
        return self.sugerido * self.producto.precio_costo_usd


def calcular(dias_cobertura=30, proveedor_id=None, solo_necesarios=True):
    desde = timezone.now() - timedelta(days=DIAS_HISTORIAL)
    ventas = {
        r['lote__producto']: -r['t'] for r in
        MovimientoInventario.objects.filter(tipo=MovimientoInventario.Tipo.VENTA, fecha__gte=desde)
        .values('lote__producto').annotate(t=Sum('cantidad'))
    }
    en_camino = {
        r['producto']: r['t'] for r in
        ItemOrdenCompra.objects.filter(orden__estado__in=[OrdenCompra.Estado.BORRADOR, OrdenCompra.Estado.ENVIADA,
                                                          OrdenCompra.Estado.PARCIAL])
        .values('producto').annotate(t=Sum(F('cantidad_pedida') - F('cantidad_recibida')))
    }
    productos = (Producto.objects.filter(activo=True).con_stock()
                 .select_related('proveedor_habitual', 'unidad').order_by('nombre'))
    if proveedor_id == 'ninguno':
        productos = productos.filter(proveedor_habitual__isnull=True)
    elif proveedor_id:
        productos = productos.filter(proveedor_habitual_id=proveedor_id)

    grupos = OrderedDict()
    for p in productos:
        vendidas = ventas.get(p.pk, 0)
        if vendidas > 0:
            consumo, fuente = vendidas / DIAS_HISTORIAL, 'ventas'
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
        s = Sugerencia(p, disponible, camino, round(consumo, 2), dias, sugerido, fuente)
        grupos.setdefault(p.proveedor_habitual, []).append(s)
    # Proveedores por nombre; "sin proveedor" al final
    return OrderedDict(sorted(grupos.items(), key=lambda kv: (kv[0] is None, kv[0].nombre if kv[0] else '')))
