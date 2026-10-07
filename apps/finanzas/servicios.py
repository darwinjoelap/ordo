"""
Cálculo del punto de equilibrio de un mes.

  Ingreso neto      = ventas validadas (sin IVA) − devoluciones          → por día, en la fecha de validación
  Costos variables  = costo de lo vendido + comisiones + deducciones (%)
  Margen            = ingreso neto − costos variables
  Punto de equilibrio = primer día en que el margen ACUMULADO del mes cubre los costos fijos del mes
  Utilidad          = margen acumulado − costos fijos

El costo de lo vendido es el costo del producto guardado en cada línea al venderla. Las unidades devueltas que
vuelven al inventario restan su costo; las que no vuelven (dañadas) no, porque ese costo se perdió.
"""
import calendar
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import CostoFijo, Deduccion

CERO = Decimal('0')
CIEN = Decimal('100')
DOS = Decimal('0.01')


def primer_dia(anio, mes):
    return date(anio, mes, 1)


def mes_anterior(d):
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def mes_siguiente(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def costos_del_mes(mes):
    """Costos fijos vigentes en ese mes (mes = día 1)."""
    return CostoFijo.objects.filter(desde__lte=mes).filter(Q(hasta__isnull=True) | Q(hasta__gte=mes))


def agregar_costo(nombre, monto, mes, recurrente):
    return CostoFijo.objects.create(nombre=nombre.strip()[:80], monto_usd=monto, desde=mes,
                                    hasta=None if recurrente else mes)


def quitar_costo(costo, mes):
    """
    Quita el costo DESDE ese mes. Los meses anteriores conservan su cálculo: si el costo ya regía antes,
    solo se le pone fecha de fin. Devuelve True si se borró por completo.
    """
    if costo.desde >= mes:
        costo.delete()
        return True
    costo.hasta = mes_anterior(mes)
    costo.save(update_fields=['hasta'])
    return False


def calcular(anio, mes, hoy=None):
    from apps.comisiones.models import AjusteComision, Comision
    from apps.ventas.models import Devolucion, ItemDevolucion, ItemPresupuesto, Presupuesto

    hoy = hoy or timezone.localdate()
    inicio = primer_dia(anio, mes)
    dias = calendar.monthrange(anio, mes)[1]
    fin = inicio.replace(day=dias)
    if inicio > hoy:
        limite, en_curso = 0, False
    elif (hoy.year, hoy.month) == (anio, mes):
        limite, en_curso = hoy.day, True
    else:
        limite, en_curso = dias, False

    ingreso, costo, comision = defaultdict(lambda: CERO), defaultdict(lambda: CERO), defaultdict(lambda: CERO)

    zona = timezone.get_current_timezone()
    desde_dt = timezone.make_aware(datetime.combine(inicio, time.min), zona)
    hasta_dt = timezone.make_aware(datetime.combine(mes_siguiente(inicio), time.min), zona)
    E = Presupuesto.Estado
    ventas = list(Presupuesto.objects.filter(estado__in=[E.VALIDADA, E.DEVUELTA], validado_en__gte=desde_dt,
                                             validado_en__lt=hasta_dt).values('pk', 'validado_en', 'base_usd'))
    dia_de = {v['pk']: timezone.localtime(v['validado_en']).day for v in ventas}
    for v in ventas:
        ingreso[dia_de[v['pk']]] += v['base_usd']
    for fila in (ItemPresupuesto.objects.filter(presupuesto_id__in=dia_de).values('presupuesto_id')
                 .annotate(c=Sum(F('cantidad') * F('costo_usd')))):
        costo[dia_de[fila['presupuesto_id']]] += fila['c'] or CERO

    devoluciones = {d['pk']: d for d in Devolucion.objects.filter(fecha__gte=inicio, fecha__lte=fin)
                    .values('pk', 'fecha', 'base_usd')}
    for d in devoluciones.values():
        ingreso[d['fecha'].day] -= d['base_usd']
    for fila in (ItemDevolucion.objects.filter(devolucion_id__in=devoluciones, reingresa=True)
                 .values('devolucion_id').annotate(c=Sum(F('cantidad') * F('item__costo_usd')))):
        costo[devoluciones[fila['devolucion_id']]['fecha'].day] -= fila['c'] or CERO

    for modelo in (Comision, AjusteComision):       # los ajustes por devolución son negativos
        for fila in modelo.objects.filter(fecha__gte=inicio, fecha__lte=fin).values('fecha').annotate(t=Sum('monto_usd')):
            comision[fila['fecha'].day] += fila['t'] or CERO

    deducciones = list(Deduccion.objects.filter(activa=True))
    pct_venta = sum((d.porcentaje for d in deducciones if d.base == Deduccion.Base.VENTA), CERO) / CIEN
    pct_utilidad = sum((d.porcentaje for d in deducciones if d.base == Deduccion.Base.UTILIDAD), CERO) / CIEN

    costos = list(costos_del_mes(inicio))
    fijos = sum((c.monto_usd for c in costos), CERO)

    serie, acumulado, equilibrio_dia = [], CERO, None
    tot = {'ingreso': CERO, 'costo': CERO, 'comision': CERO, 'deducciones': CERO, 'margen': CERO}
    for d in range(1, limite + 1):
        ded = (ingreso[d] * pct_venta + (ingreso[d] - costo[d]) * pct_utilidad).quantize(DOS)
        margen = ingreso[d] - costo[d] - comision[d] - ded
        acumulado += margen
        if equilibrio_dia is None and fijos > 0 and acumulado >= fijos:
            equilibrio_dia = d
        serie.append({'dia': d, 'ingreso': ingreso[d], 'costo': costo[d], 'comision': comision[d],
                      'deducciones': ded, 'margen': margen, 'acumulado': acumulado, 'utilidad': acumulado - fijos})
        for clave, valor in (('ingreso', ingreso[d]), ('costo', costo[d]), ('comision', comision[d]),
                             ('deducciones', ded), ('margen', margen)):
            tot[clave] += valor

    razon = (tot['margen'] / tot['ingreso']) if tot['ingreso'] > 0 else None
    ventas_equilibrio = (fijos / razon).quantize(DOS) if razon and razon > 0 and fijos > 0 else None

    proyeccion = None
    if en_curso and limite and equilibrio_dia is None and fijos > 0:
        ritmo = acumulado / limite
        dia_estimado = math.ceil(fijos / ritmo) if ritmo > 0 else None
        proyeccion = {'ritmo': ritmo.quantize(DOS), 'fin_de_mes': (ritmo * dias).quantize(DOS),
                      'dia_estimado': dia_estimado if dia_estimado and dia_estimado <= dias else None}
    elif en_curso and limite:
        ritmo = acumulado / limite
        proyeccion = {'ritmo': ritmo.quantize(DOS), 'fin_de_mes': (ritmo * dias).quantize(DOS), 'dia_estimado': None}

    return {
        'inicio': inicio, 'dias': dias, 'limite': limite, 'en_curso': en_curso, 'futuro': inicio > hoy,
        'serie': serie, 'totales': tot, 'fijos': fijos, 'costos': costos, 'deducciones': deducciones,
        'acumulado': acumulado, 'utilidad': acumulado - fijos,
        'equilibrio_dia': equilibrio_dia,
        'equilibrio_fecha': inicio.replace(day=equilibrio_dia) if equilibrio_dia else None,
        'razon_margen': (razon * CIEN).quantize(Decimal('0.1')) if razon is not None else None,
        'ventas_equilibrio': ventas_equilibrio, 'proyeccion': proyeccion,
        'falta': max(fijos - acumulado, CERO), 'n_ventas': len(ventas),
    }
