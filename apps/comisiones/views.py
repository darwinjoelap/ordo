from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permisos import PERMISOS, requiere, tiene_permiso
from apps.empresas.models import Membresia
from apps.inventario.models import Categoria

from . import servicios
from .models import AjusteComision, Comision, Liquidacion, PorcentajeCategoria, PorcentajeVendedor
from .pdf import liquidacion_pdf


def vendedores(empresa):
    roles = PERMISOS['presupuestos.crear']
    ids = Membresia.objects.filter(empresa=empresa, activa=True, rol__in=roles).values_list('usuario_id', flat=True)
    return get_user_model().objects.filter(pk__in=ids, is_superuser=False).order_by('first_name', 'username')


def _mes(texto):
    """'2026-09' → date(2026, 9, 1); inválido o vacío → mes actual."""
    try:
        anio, mes = map(int, (texto or '').split('-'))
        return date(anio, mes, 1)
    except ValueError:
        return timezone.localdate().replace(day=1)


def _siguiente_mes(d):
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@login_required
@requiere('comisiones.ver_propias')
def inicio(request):
    if not tiene_permiso(request, 'comisiones.liquidar'):
        return redirect('comisiones:detalle_vendedor')
    perfil = request.empresa.perfil
    inicio_mes = timezone.localdate().replace(day=1)
    filas = servicios.resumen_por_vendedor(perfil, inicio_mes)
    sin_porcentaje = vendedores(request.empresa).exclude(
        pk__in=PorcentajeVendedor.objects.values_list('vendedor_id', flat=True))
    return render(request, 'comisiones/inicio.html', {
        'titulo': 'Comisiones', 'filas': filas, 'perfil': perfil, 'sin_porcentaje': sin_porcentaje,
        'liquidaciones': Liquidacion.objects.select_related('vendedor')[:8],
        'totales': {k: sum((f[k] for f in filas), Decimal('0')) for k in ('disponible', 'por_cobrar', 'mes')},
    })


@login_required
@requiere('comisiones.ver_propias')
def detalle_vendedor(request, vendedor_id=None):
    """Comisiones de un vendedor por mes. El vendedor solo ve las suyas."""
    if vendedor_id and tiene_permiso(request, 'comisiones.liquidar'):
        vendedor = get_object_or_404(vendedores(request.empresa), pk=vendedor_id)
    elif vendedor_id and vendedor_id != request.user.pk:
        raise Http404
    else:
        vendedor = request.user
    perfil = request.empresa.perfil
    mes = _mes(request.GET.get('mes'))
    comisiones = (Comision.objects.filter(vendedor=vendedor, fecha__gte=mes, fecha__lt=_siguiente_mes(mes))
                  .select_related('presupuesto__cliente', 'liquidacion').order_by('-fecha', '-pk'))
    for c in comisiones:
        if c.liquidacion_id:
            c.estado, c.css = f'Liquidada ({c.liquidacion.numero})', 'success' if c.liquidacion.pagada else 'info'
        elif perfil.comision_requiere_pago and not c.presupuesto.pagado:
            c.estado, c.css = 'Espera cobro', 'warning'
        else:
            c.estado, c.css = 'Disponible', 'primary'
    ajustes = list(AjusteComision.objects.filter(vendedor=vendedor, fecha__gte=mes, fecha__lt=_siguiente_mes(mes))
                   .select_related('devolucion__presupuesto__cliente', 'liquidacion').order_by('-fecha', '-pk'))
    total_mes = (sum((c.monto_usd for c in comisiones), Decimal('0'))
                 + sum((a.monto_usd for a in ajustes), Decimal('0')))
    base_mes = sum((c.base_usd for c in comisiones), Decimal('0'))
    disponible = servicios.saldo_disponible(perfil, vendedor)
    fila = PorcentajeVendedor.objects.filter(vendedor=vendedor).first()
    return render(request, 'comisiones/vendedor.html', {
        'titulo': f'Comisiones · {vendedor.nombre_visible}', 'vendedor': vendedor,
        'comisiones': comisiones, 'ajustes': ajustes, 'mes': mes, 'mes_anterior': (mes - timedelta(days=1)).replace(day=1),
        'mes_siguiente': _siguiente_mes(mes) if _siguiente_mes(mes) <= timezone.localdate() else None,
        'total_mes': total_mes, 'base_mes': base_mes, 'disponible': disponible,
        'porcentaje': fila.porcentaje if fila else None,
        'liquidaciones': Liquidacion.objects.filter(vendedor=vendedor)[:10],
        'es_propio': vendedor == request.user,
    })


@login_required
@requiere('comisiones.liquidar')
def configuracion(request):
    lista_vendedores = list(vendedores(request.empresa))
    categorias = list(Categoria.objects.order_by('nombre'))
    pct_v = dict(PorcentajeVendedor.objects.values_list('vendedor_id', 'porcentaje'))
    pct_c = dict(PorcentajeCategoria.objects.values_list('categoria_id', 'porcentaje'))
    if request.method == 'POST':
        errores = []

        def leer(nombre):
            texto = request.POST.get(nombre, '').strip().replace(',', '.')
            if not texto:
                return None
            try:
                valor = Decimal(texto)
            except InvalidOperation:
                errores.append(texto)
                return None
            if not (0 <= valor <= 100):
                errores.append(texto)
                return None
            return valor.quantize(Decimal('0.01'))
        with transaction.atomic():
            for v in lista_vendedores:
                valor = leer(f'v_{v.pk}')
                if valor is None:
                    PorcentajeVendedor.objects.filter(vendedor=v).delete()
                else:
                    PorcentajeVendedor.objects.update_or_create(vendedor=v, defaults={'porcentaje': valor})
            for c in categorias:
                valor = leer(f'c_{c.pk}')
                if valor is None:
                    PorcentajeCategoria.objects.filter(categoria=c).delete()
                else:
                    PorcentajeCategoria.objects.update_or_create(categoria=c, defaults={'porcentaje': valor})
            if errores:
                transaction.set_rollback(True)
        if errores:
            messages.error(request, f'Porcentajes inválidos (0 a 100): {", ".join(errores)}. No se guardó nada.')
        else:
            messages.success(request, 'Porcentajes guardados. Aplican a las ventas que se validen desde ahora.')
            return redirect('comisiones:configuracion')
    for v in lista_vendedores:
        v.pct = pct_v.get(v.pk)
    for c in categorias:
        c.pct = pct_c.get(c.pk)
    return render(request, 'comisiones/configuracion.html', {
        'titulo': 'Porcentajes de comisión', 'vendedores': lista_vendedores, 'categorias': categorias})


@login_required
@requiere('comisiones.liquidar')
def liquidar(request, vendedor_id):
    vendedor = get_object_or_404(vendedores(request.empresa), pk=vendedor_id)
    perfil = request.empresa.perfil
    try:
        hasta = date.fromisoformat(request.POST.get('hasta') or request.GET.get('hasta') or '')
    except ValueError:
        hasta = timezone.localdate()
    if request.method == 'POST':
        try:
            liq = servicios.liquidar(perfil, vendedor, hasta, request.user, request.empresa)
        except servicios.ErrorComision as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'Liquidación {liq.numero} creada por {liq.total_usd} USD.')
            return redirect('comisiones:liquidacion', pk=liq.pk)
    comisiones = list(servicios.disponibles(perfil, vendedor, hasta)
                      .select_related('presupuesto__cliente').order_by('fecha', 'pk'))
    ajustes = list(servicios.ajustes_aplicables(perfil, vendedor, hasta)
                   .select_related('devolucion__presupuesto__cliente').order_by('fecha', 'pk'))
    total = (sum((c.monto_usd for c in comisiones), Decimal('0'))
             + sum((a.monto_usd for a in ajustes), Decimal('0')))
    return render(request, 'comisiones/liquidar.html', {
        'titulo': 'Liquidar comisiones', 'vendedor': vendedor, 'hasta': hasta, 'comisiones': comisiones,
        'ajustes': ajustes, 'total': total})


def _liquidaciones_visibles(request):
    qs = Liquidacion.objects.select_related('vendedor', 'creada_por')
    if not tiene_permiso(request, 'comisiones.liquidar'):
        qs = qs.filter(vendedor=request.user)
    return qs


@login_required
@requiere('comisiones.ver_propias')
def liquidacion(request, pk):
    liq = get_object_or_404(_liquidaciones_visibles(request), pk=pk)
    if request.method == 'POST':
        if not tiene_permiso(request, 'comisiones.liquidar'):
            raise Http404
        try:
            if request.POST.get('accion') == 'pagar':
                fecha = request.POST.get('fecha_pago')
                servicios.marcar_pagada(liq, date.fromisoformat(fecha) if fecha else None,
                                        request.POST.get('metodo_pago', ''), request.POST.get('referencia', ''))
                messages.success(request, 'Liquidación marcada como pagada.')
            elif request.POST.get('accion') == 'anular':
                servicios.anular(liq)
                messages.success(request, 'Liquidación anulada. Sus comisiones vuelven a estar disponibles.')
        except (servicios.ErrorComision, ValueError) as e:
            messages.error(request, str(e))
        return redirect('comisiones:liquidacion', pk=pk)
    comisiones = Comision.objects.filter(liquidacion=liq).select_related('presupuesto__cliente').order_by('fecha', 'pk')
    ajustes = (AjusteComision.objects.filter(liquidacion=liq)
               .select_related('devolucion__presupuesto__cliente').order_by('fecha', 'pk'))
    return render(request, 'comisiones/liquidacion.html', {'titulo': liq.numero, 'liq': liq, 'comisiones': comisiones,
                                                           'ajustes': ajustes})


@login_required
@requiere('comisiones.ver_propias')
def liquidacion_pdf_vista(request, pk):
    liq = get_object_or_404(_liquidaciones_visibles(request), pk=pk)
    r = HttpResponse(liquidacion_pdf(liq, request.empresa), content_type='application/pdf')
    r['Content-Disposition'] = f'inline; filename="{liq.numero}.pdf"'
    return r
