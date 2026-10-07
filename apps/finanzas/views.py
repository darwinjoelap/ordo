from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere

from . import servicios
from .models import CostoFijo, Deduccion


def _mes(texto):
    """'2026-10' → date(2026, 10, 1); inválido o vacío → el mes actual."""
    try:
        anio, mes = (int(x) for x in (texto or '').split('-')[:2])
        return date(anio, mes, 1)
    except (ValueError, TypeError):
        return timezone.localdate().replace(day=1)


def _volver(mes):
    return redirect(f'{reverse("finanzas:equilibrio")}?mes={mes:%Y-%m}')


def _decimal(texto):
    return Decimal((texto or '').strip().replace(',', '.'))


@login_required
@requiere('finanzas.ver')
def equilibrio(request):
    mes = _mes(request.GET.get('mes'))
    actual = timezone.localdate().replace(day=1)
    r = servicios.calcular(mes.year, mes.month)
    grafica = {
        'dias': r['dias'], 'fijos': float(r['fijos']), 'equilibrio': r['equilibrio_dia'],
        'serie': [{'dia': s['dia'], 'acumulado': float(s['acumulado']), 'ingreso': float(s['ingreso']),
                   'margen': float(s['margen'])} for s in r['serie']],
        'proyeccion': float(r['proyeccion']['fin_de_mes']) if r['proyeccion'] else None,
        'mes': f'{mes:%m/%Y}',
    }
    return render(request, 'finanzas/equilibrio.html', {
        'titulo': 'Punto de equilibrio', 'r': r, 'mes': mes, 'grafica': grafica,
        'anterior': servicios.mes_anterior(mes),
        'siguiente': servicios.mes_siguiente(mes) if mes < actual else None,
        'es_actual': mes == actual, 'bases': Deduccion.Base.choices,
        'deducciones_inactivas': Deduccion.objects.filter(activa=False),
    })


@login_required
@requiere('finanzas.ver')
@require_POST
def costo_agregar(request):
    mes = _mes(request.POST.get('mes'))
    nombre = request.POST.get('nombre', '').strip()
    try:
        monto = _decimal(request.POST.get('monto'))
    except InvalidOperation:
        monto = None
    if not nombre or monto is None or monto <= 0:
        messages.error(request, 'Escribe el concepto y un monto mayor que cero.')
    else:
        servicios.agregar_costo(nombre, monto, mes, request.POST.get('recurrente') == '1')
        messages.success(request, f'Costo fijo agregado: {nombre}.')
    return _volver(mes)


@login_required
@requiere('finanzas.ver')
@require_POST
def costo_quitar(request, pk):
    mes = _mes(request.POST.get('mes'))
    costo = get_object_or_404(CostoFijo, pk=pk)
    nombre = costo.nombre
    if servicios.quitar_costo(costo, mes):
        messages.success(request, f'{nombre}: eliminado.')
    else:
        messages.success(request, f'{nombre}: deja de contar desde {mes:%m/%Y}. Los meses anteriores no cambian.')
    return _volver(mes)


@login_required
@requiere('finanzas.ver')
@require_POST
def deduccion_agregar(request):
    mes = _mes(request.POST.get('mes'))
    nombre = request.POST.get('nombre', '').strip()
    base = request.POST.get('base')
    try:
        pct = _decimal(request.POST.get('porcentaje'))
    except InvalidOperation:
        pct = None
    if not nombre or pct is None or not (0 < pct <= 100) or base not in Deduccion.Base.values:
        messages.error(request, 'Escribe el concepto y un porcentaje entre 0 y 100.')
    else:
        Deduccion.objects.create(nombre=nombre[:80], porcentaje=pct, base=base)
        messages.success(request, f'Deducción agregada: {nombre} ({pct} %).')
    return _volver(mes)


@login_required
@requiere('finanzas.ver')
@require_POST
def deduccion_quitar(request, pk):
    """Activa/desactiva (no se borra, para poder volver a usarla) o la elimina si se pide."""
    mes = _mes(request.POST.get('mes'))
    d = get_object_or_404(Deduccion, pk=pk)
    if request.POST.get('eliminar') == '1':
        d.delete()
        messages.success(request, f'{d.nombre}: eliminada.')
    else:
        d.activa = not d.activa
        d.save(update_fields=['activa'])
        messages.success(request, f'{d.nombre}: {"activada" if d.activa else "desactivada"}.')
    return _volver(mes)
