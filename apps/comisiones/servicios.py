from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.secuencias import siguiente_numero
from apps.core.tenancy import usando_empresa
from apps.ventas.models import ItemPresupuesto, redondear

from .models import Comision, LineaComision, Liquidacion, PorcentajeCategoria, PorcentajeVendedor

CIEN = Decimal('100')


class ErrorComision(Exception):
    pass


def porcentajes(vendedor):
    """(% del vendedor, {categoria_id: %}) de la empresa activa."""
    fila = PorcentajeVendedor.objects.filter(vendedor=vendedor).first()
    por_categoria = dict(PorcentajeCategoria.objects.values_list('categoria_id', 'porcentaje'))
    return (fila.porcentaje if fila else Decimal('0')), por_categoria


def calcular(p):
    """Líneas de comisión de un presupuesto: [(item, base, pct, origen, monto)]. No guarda nada."""
    pct_vendedor, por_categoria = porcentajes(p.vendedor)
    factor = 1 - p.descuento_pct / CIEN
    lineas = []
    for item in ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto'):
        base = redondear(item.subtotal_usd * factor)
        cat = item.producto.categoria_id
        pct, origen = (por_categoria[cat], 'CATEGORIA') if cat in por_categoria else (pct_vendedor, 'VENDEDOR')
        lineas.append((item, base, pct, origen, redondear(base * pct / CIEN)))
    return lineas


@transaction.atomic
def registrar(p):
    """Crea la comisión de una venta validada. Idempotente."""
    existente = Comision.todos.filter(presupuesto=p).first()
    if existente:
        return existente
    lineas = calcular(p)
    comision = Comision.objects.create(
        presupuesto=p, vendedor=p.vendedor, fecha=timezone.localtime(p.validado_en).date(),
        base_usd=sum((l[1] for l in lineas), Decimal('0')), monto_usd=sum((l[4] for l in lineas), Decimal('0')))
    LineaComision.objects.bulk_create([
        LineaComision(empresa=p.empresa, comision=comision, item=i, base_usd=b, porcentaje=pct, origen=o, monto_usd=m)
        for i, b, pct, o, m in lineas])
    return comision


def al_validar_venta(sender, presupuesto, usuario, **kwargs):
    with usando_empresa(presupuesto.empresa):
        registrar(presupuesto)


# ── Consultas ─────────────────────────────────────────────────────────────────

def disponibles(perfil, vendedor=None, hasta=None):
    """Comisiones sin liquidar que ya se pueden pagar."""
    qs = Comision.objects.filter(liquidacion__isnull=True)
    if perfil.comision_requiere_pago:
        qs = qs.filter(presupuesto__pagado=True)
    if vendedor is not None:
        qs = qs.filter(vendedor=vendedor)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    return qs


def pendientes_de_cobro(perfil):
    """Comisiones sin liquidar que esperan que se cobre la venta (solo si la empresa lo exige)."""
    if not perfil.comision_requiere_pago:
        return Comision.objects.none()
    return Comision.objects.filter(liquidacion__isnull=True, presupuesto__pagado=False)


def resumen_por_vendedor(perfil, desde_mes):
    """Filas por vendedor: disponible, por cobrar, generado en el mes."""
    from django.contrib.auth import get_user_model
    filas = {}

    def fila(vid):
        return filas.setdefault(vid, {'vendedor_id': vid, 'disponible': Decimal('0'), 'n_disponible': 0,
                                      'por_cobrar': Decimal('0'), 'mes': Decimal('0')})
    for r in disponibles(perfil).values('vendedor_id').annotate(t=Sum('monto_usd'), n=Count('pk')):
        f = fila(r['vendedor_id'])
        f['disponible'], f['n_disponible'] = r['t'] or 0, r['n']
    for r in pendientes_de_cobro(perfil).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['por_cobrar'] = r['t'] or 0
    for r in Comision.objects.filter(fecha__gte=desde_mes).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['mes'] = r['t'] or 0
    usuarios = get_user_model().objects.in_bulk(list(filas))
    for f in filas.values():
        f['vendedor'] = usuarios.get(f['vendedor_id'])
    return sorted(filas.values(), key=lambda f: -f['disponible'])


# ── Liquidación ───────────────────────────────────────────────────────────────

@transaction.atomic
def liquidar(perfil, vendedor, hasta, usuario, empresa):
    ids = list(disponibles(perfil, vendedor, hasta).values_list('pk', flat=True))
    comisiones = list(Comision.objects.select_for_update().filter(pk__in=ids, liquidacion__isnull=True))
    if not comisiones:
        raise ErrorComision('No hay comisiones disponibles para liquidar en ese período.')
    liq = Liquidacion.objects.create(
        numero=siguiente_numero('LQ', prefijo=(perfil.prefijo_numeracion or '').upper()),
        vendedor=vendedor, hasta=hasta, creada_por=usuario,
        total_usd=sum((c.monto_usd for c in comisiones), Decimal('0')))
    Comision.objects.filter(pk__in=[c.pk for c in comisiones]).update(liquidacion=liq)
    return liq


@transaction.atomic
def marcar_pagada(liq, fecha=None, metodo='', referencia=''):
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.pagada or liq.anulada:
        raise ErrorComision('La liquidación ya está pagada o anulada.')
    liq.pagada, liq.fecha_pago = True, fecha or timezone.localdate()
    liq.metodo_pago, liq.referencia = metodo[:40], referencia[:80]
    liq.save(update_fields=['pagada', 'fecha_pago', 'metodo_pago', 'referencia'])
    return liq


@transaction.atomic
def anular(liq):
    """Anula una liquidación NO pagada: sus comisiones vuelven a estar disponibles. El número queda registrado."""
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.pagada:
        raise ErrorComision('Una liquidación pagada no se puede anular.')
    if liq.anulada:
        return liq
    Comision.objects.filter(liquidacion=liq).update(liquidacion=None)
    liq.anulada = True
    liq.save(update_fields=['anulada'])
    return liq


def generar_faltantes():
    """Crea comisiones de ventas validadas que no la tengan (migración o ventas previas a la Fase 5)."""
    from apps.ventas.models import Presupuesto
    total = 0
    for p in Presupuesto.todos.filter(estado='VALIDADA', comision__isnull=True).select_related('empresa'):
        with usando_empresa(p.empresa):
            registrar(p)
            total += 1
    return total


def filtro_texto(q):
    return Q(presupuesto__numero__icontains=q) | Q(presupuesto__cliente__nombre__icontains=q)
