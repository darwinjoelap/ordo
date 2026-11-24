from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.secuencias import siguiente_numero
from apps.core.tenancy import usando_empresa
from apps.empresas.models import PerfilEmpresa
from apps.ventas.models import ItemDevolucion, ItemPresupuesto, Presupuesto, redondear

from .models import (AjusteComision, Comision, LineaComision, Liquidacion, MovimientoComision,
                     PorcentajeCategoria, PorcentajeVendedor)

CIEN = Decimal('100')
CERO = Decimal('0')
MODO = PerfilEmpresa.ModalidadComision


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
        presupuesto=p, vendedor=p.vendedor, fecha=timezone.localtime(p.validado_en or p.confirmado_en).date(),
        base_usd=sum((l[1] for l in lineas), Decimal('0')), monto_usd=sum((l[4] for l in lineas), Decimal('0')))
    LineaComision.objects.bulk_create([
        LineaComision(empresa=p.empresa, comision=comision, item=i, base_usd=b, porcentaje=pct, origen=o, monto_usd=m)
        for i, b, pct, o, m in lineas])
    return comision


def al_validar_venta(sender, presupuesto, usuario, **kwargs):
    if presupuesto.modalidad_comision == MODO.PROPORCIONAL:
        return
    with usando_empresa(presupuesto.empresa):
        registrar(presupuesto)


def actualizar_proporcional(p, origen, fecha):
    """Registra el cambio acumulado bajo el bloqueo de la venta que tomó el servicio llamante."""
    if p.modalidad_comision != MODO.PROPORCIONAL:
        return
    comision = Comision.objects.get(presupuesto=p)
    movimientos = MovimientoComision.objects.filter(comision=comision)
    if movimientos.filter(origen=origen).exists():
        return
    cantidades = dict(ItemDevolucion.objects.filter(devolucion__presupuesto=p)
                      .values('item_id').annotate(n=Sum('cantidad')).values_list('item_id', 'n'))
    cuota = min(p.abonado_usd / p.neto_usd, Decimal('1')) if p.neto_usd > 0 else CERO
    base_total = monto_total = CERO
    for linea in LineaComision.objects.filter(comision=comision).select_related('item'):
        quedan = linea.item.cantidad - cantidades.get(linea.item_id, 0)
        base = redondear(linea.base_usd * quedan / linea.item.cantidad)
        base_total += base
        monto_total += redondear(base * linea.porcentaje / CIEN)
    acumulado = movimientos.aggregate(base=Sum('base_usd'), monto=Sum('monto_usd'))
    base = redondear(base_total * cuota) - redondear(acumulado['base'] or CERO)
    monto = redondear(monto_total * cuota) - redondear(acumulado['monto'] or CERO)
    if base or monto:
        MovimientoComision.objects.create(comision=comision, origen=origen, fecha=fecha,
                                          base_usd=base, monto_usd=monto)


@transaction.atomic
def registrar_ajuste(dev):
    """Ajuste negativo por una devolución. Usa el % congelado de cada línea. Idempotente."""
    from apps.ventas.models import ItemDevolucion
    existente = AjusteComision.todos.filter(devolucion=dev).first()
    if existente:
        return existente
    p = dev.presupuesto
    if p.modalidad_comision == MODO.PROPORCIONAL:
        actualizar_proporcional(p, f'devolucion:{dev.pk}', dev.fecha)
        return None
    comision = Comision.todos.filter(presupuesto=p).first()
    if comision is None:
        return None
    if p.estado == 'DEVUELTA':          # se devolvió todo: anula exactamente lo que quedaba
        previo = AjusteComision.todos.filter(comision=comision).aggregate(t=Sum('monto_usd'))['t'] or Decimal('0')
        monto = -(comision.monto_usd + previo)
    else:
        pct = dict(LineaComision.todos.filter(comision=comision).values_list('item_id', 'porcentaje'))
        factor = 1 - p.descuento_pct / CIEN
        monto = Decimal('0')
        for linea in ItemDevolucion.todos.filter(devolucion=dev):
            base = redondear(linea.cantidad * linea.item.precio_usd * factor)
            monto += redondear(base * pct.get(linea.item_id, Decimal('0')) / CIEN)
        monto = -monto
    if not monto:
        return None
    return AjusteComision.objects.create(comision=comision, devolucion=dev, vendedor=comision.vendedor,
                                         fecha=dev.fecha, monto_usd=monto)


def al_devolver_venta(sender, devolucion, usuario, **kwargs):
    with usando_empresa(devolucion.empresa):
        registrar_ajuste(devolucion)


# ── Consultas ─────────────────────────────────────────────────────────────────

def disponibles(perfil, vendedor=None, hasta=None):
    """Comisiones sin liquidar que ya se pueden pagar."""
    qs = Comision.objects.filter(liquidacion__isnull=True).exclude(presupuesto__modalidad_comision=MODO.PROPORCIONAL)
    espera_pago = modalidades_cobradas(perfil)
    qs = qs.filter(~Q(presupuesto__modalidad_comision__in=espera_pago) | Q(presupuesto__pagado=True))
    if vendedor is not None:
        qs = qs.filter(vendedor=vendedor)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    return qs


def modalidades_cobradas(perfil):
    return [MODO.COBRADA, ''] if perfil.comision_requiere_pago else [MODO.COBRADA]


def movimientos_disponibles(vendedor=None, hasta=None):
    qs = MovimientoComision.objects.filter(liquidacion__isnull=True, comision__presupuesto__validado_en__isnull=False)
    if vendedor is not None:
        qs = qs.filter(comision__vendedor=vendedor)
    if hasta:
        qs = qs.filter(fecha__lte=hasta, comision__presupuesto__validado_en__date__lte=hasta)
    return qs


def ajustes_aplicables(perfil, vendedor=None, hasta=None):
    """
    Ajustes negativos sin liquidar que se descuentan ahora: los de comisiones ya liquidadas
    y los de comisiones que entran en esta misma liquidación.
    """
    qs = AjusteComision.objects.filter(liquidacion__isnull=True).filter(
        Q(comision__liquidacion__isnull=False) | Q(comision__in=disponibles(perfil, vendedor, hasta)))
    if vendedor is not None:
        qs = qs.filter(vendedor=vendedor)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    return qs


def saldo_disponible(perfil, vendedor, hasta=None):
    c = disponibles(perfil, vendedor, hasta).aggregate(t=Sum('monto_usd'))['t'] or Decimal('0')
    a = ajustes_aplicables(perfil, vendedor, hasta).aggregate(t=Sum('monto_usd'))['t'] or Decimal('0')
    m = movimientos_disponibles(vendedor, hasta).aggregate(t=Sum('monto_usd'))['t'] or CERO
    return redondear(c + a + m)


def pendientes_de_cobro(perfil):
    """Comisiones sin liquidar que esperan que se cobre la venta (solo si la empresa lo exige)."""
    return Comision.objects.filter(liquidacion__isnull=True, presupuesto__pagado=False,
                                  presupuesto__modalidad_comision__in=modalidades_cobradas(perfil))


def resumen_por_vendedor(perfil, desde_mes):
    """Filas por vendedor: disponible, por cobrar, generado en el mes."""
    from django.contrib.auth import get_user_model
    filas = {}

    def fila(vid):
        return filas.setdefault(vid, {'vendedor_id': vid, 'disponible': Decimal('0'), 'n_disponible': 0,
                                      'por_cobrar': CERO, 'devengado_por_validar': CERO, 'mes': CERO})
    for r in disponibles(perfil).values('vendedor_id').annotate(t=Sum('monto_usd'), n=Count('pk')):
        f = fila(r['vendedor_id'])
        f['disponible'], f['n_disponible'] = r['t'] or 0, r['n']
    for r in pendientes_de_cobro(perfil).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['por_cobrar'] = r['t'] or 0
    for r in ajustes_aplicables(perfil).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['disponible'] += r['t'] or 0
    convencionales = Comision.objects.exclude(presupuesto__modalidad_comision=MODO.PROPORCIONAL)
    for r in convencionales.filter(fecha__gte=desde_mes).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['mes'] = r['t'] or 0
    for r in AjusteComision.objects.filter(fecha__gte=desde_mes).values('vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['vendedor_id'])['mes'] += r['t'] or 0
    for r in movimientos_disponibles().values('comision__vendedor_id').annotate(t=Sum('monto_usd'), n=Count('pk')):
        f = fila(r['comision__vendedor_id'])
        f['disponible'] += r['t'] or 0
        f['n_disponible'] += r['n']
    sin_validar = MovimientoComision.objects.filter(liquidacion__isnull=True,
                                                    comision__presupuesto__validado_en__isnull=True)
    for r in sin_validar.values('comision__vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['comision__vendedor_id'])['devengado_por_validar'] = redondear(r['t'] or CERO)
    movimientos = MovimientoComision.objects.filter(fecha__gte=desde_mes)
    for r in movimientos.values('comision__vendedor_id').annotate(t=Sum('monto_usd')):
        fila(r['comision__vendedor_id'])['mes'] += r['t'] or 0
    usuarios = get_user_model().objects.in_bulk(list(filas))
    for f in filas.values():
        f['vendedor'] = usuarios.get(f['vendedor_id'])
    return sorted(filas.values(), key=lambda f: -f['disponible'])


# ── Liquidación ───────────────────────────────────────────────────────────────

@transaction.atomic
def liquidar(perfil, vendedor, hasta, usuario, empresa):
    # Mismo orden de bloqueo que el flujo de cobro/devolución: primero la venta.
    ids = set(disponibles(perfil, vendedor, hasta).values_list('presupuesto_id', flat=True))
    ids.update(ajustes_aplicables(perfil, vendedor, hasta).values_list('comision__presupuesto_id', flat=True))
    ids.update(movimientos_disponibles(vendedor, hasta).values_list('comision__presupuesto_id', flat=True))
    ventas = list(Presupuesto.objects.select_for_update().filter(pk__in=ids).order_by('pk').values_list('pk', flat=True))
    comisiones = list(disponibles(perfil, vendedor, hasta).filter(presupuesto_id__in=ventas)
                      .select_for_update(of=('self',)).order_by('pk'))
    ajustes = list(ajustes_aplicables(perfil, vendedor, hasta).filter(comision__presupuesto_id__in=ventas)
                   .select_for_update(of=('self',)).order_by('pk'))
    movimientos = list(movimientos_disponibles(vendedor, hasta).filter(comision__presupuesto_id__in=ventas)
                       .select_for_update(of=('self',)).order_by('pk'))
    if not comisiones and not ajustes and not movimientos:
        raise ErrorComision('No hay comisiones disponibles para liquidar en ese período.')
    total = sum((c.monto_usd for c in comisiones + ajustes + movimientos), CERO)
    if total < 0:
        raise ErrorComision(f'El saldo del vendedor es negativo ({total} USD) por ajustes: '
                            'se descontará cuando tenga nuevas comisiones.')
    liq = Liquidacion.objects.create(
        numero=siguiente_numero('LQ', prefijo=(perfil.prefijo_numeracion or '').upper()),
        vendedor=vendedor, hasta=hasta, creada_por=usuario, total_usd=total)
    Comision.objects.filter(pk__in=[c.pk for c in comisiones]).update(liquidacion=liq)
    AjusteComision.objects.filter(pk__in=[a.pk for a in ajustes]).update(liquidacion=liq)
    MovimientoComision.objects.filter(pk__in=[m.pk for m in movimientos]).update(liquidacion=liq)
    return liq


@transaction.atomic
def marcar_pagada(liq, fecha=None, metodo='', referencia=''):
    ids = MovimientoComision.objects.filter(liquidacion=liq).values_list('comision__presupuesto_id', flat=True)
    ventas = list(Presupuesto.objects.filter(pk__in=ids).order_by('pk').select_for_update()
                  .values_list('pk', flat=True))
    liq = Liquidacion.objects.select_for_update().get(pk=liq.pk)
    if liq.pagada or liq.anulada:
        raise ErrorComision('La liquidación ya está pagada o anulada.')
    pendientes = (MovimientoComision.objects.filter(liquidacion__isnull=True, comision__presupuesto_id__in=ventas)
                  .values('comision_id').annotate(total=Sum('monto_usd')))
    if any(redondear(mov['total']) < CERO for mov in pendientes):
        raise ErrorComision('Hay correcciones pendientes. Anula la liquidación y vuelve a calcularla.')
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
    AjusteComision.objects.filter(liquidacion=liq).update(liquidacion=None)
    MovimientoComision.objects.filter(liquidacion=liq).update(liquidacion=None)
    liq.anulada = True
    liq.save(update_fields=['anulada'])
    return liq


def generar_faltantes():
    """Crea comisiones de ventas validadas que no la tengan (migración o ventas previas a la Fase 5)."""
    total = 0
    ventas = Presupuesto.todos.filter(estado='VALIDADA', comision__isnull=True)
    for p in ventas.exclude(modalidad_comision=MODO.PROPORCIONAL).select_related('empresa'):
        with usando_empresa(p.empresa):
            registrar(p)
            total += 1
    return total


def filtro_texto(q):
    return Q(presupuesto__numero__icontains=q) | Q(presupuesto__cliente__nombre__icontains=q)
