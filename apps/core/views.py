from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


@login_required
def inicio(request):
    """Tablero: cifras del mes según el rol (el vendedor ve solo lo suyo)."""
    ctx = {'titulo': 'Inicio'}
    if getattr(request, 'empresa', None) is None or getattr(request, 'membresia', None) is None:
        return render(request, 'core/inicio.html', ctx)
    from datetime import timedelta

    from django.db.models import Count, F, Q, Sum
    from django.utils import timezone

    from apps.core.permisos import tiene_permiso
    from apps.inventario.models import Producto
    from apps.ventas.models import Presupuesto

    E = Presupuesto.Estado
    ahora = timezone.localtime()
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    docs = Presupuesto.objects.all()
    if not tiene_permiso(request, 'presupuestos.ver_todos'):
        docs = docs.filter(vendedor=request.user)
    if tiene_permiso(request, 'presupuestos.crear'):
        # Neto de devoluciones; las ventas devueltas por completo no cuentan
        mes = docs.filter(estado__in=[E.VALIDADA, E.DEVUELTA], validado_en__gte=inicio_mes).aggregate(
            n=Count('pk', filter=Q(estado=E.VALIDADA)), usd=Sum(F('total_usd') - F('devuelto_usd')))
        ctx.update({
            'ventas_mes': mes,
            'por_validar': docs.filter(estado=E.POR_VALIDAR).aggregate(n=Count('pk'), usd=Sum('total_usd')),
            'apartados': docs.filter(estado=E.APARTADO).count(),
            'por_vencer': docs.filter(estado=E.APARTADO, apartado_hasta__lte=ahora + timedelta(days=2))
                              .select_related('cliente').order_by('apartado_hasta')[:5],
            'abiertos': docs.filter(estado__in=[E.BORRADOR, E.EMITIDO]).count(),
            'ultimos': docs.select_related('cliente').order_by('-actualizado_en')[:6],
            'por_cobrar': docs.filter(Q(estado=E.POR_PAGAR) | Q(estado=E.VALIDADA, pagado=False)).aggregate(
                n=Count('pk'), usd=Sum(F('total_usd') - F('devuelto_usd'))),
            'por_entregar': docs.filter(estado__in=Presupuesto.CONFIRMADAS, entregado=False).count(),
        })
    if tiene_permiso(request, 'comisiones.ver_propias'):
        from apps.comisiones.models import AjusteComision, Comision
        ctx['mi_comision_mes'] = sum(
            (m.objects.filter(vendedor=request.user, fecha__gte=inicio_mes.date()).aggregate(t=Sum('monto_usd'))['t'] or 0
             for m in (Comision, AjusteComision)), 0)
    if tiene_permiso(request, 'inventario.ver'):
        from apps.inventario.models import Lote
        hoy = ahora.date()
        criticos = (Producto.objects.filter(activo=True, stock_minimo__gt=0).con_stock()
                    .filter(anot_stock_disponible__lte=F('stock_minimo')).order_by('anot_stock_disponible', 'nombre'))
        con_stock = Lote.objects.filter(cantidad_actual__gt=0).select_related('producto')
        vencidos = con_stock.filter(fecha_vencimiento__lt=hoy).order_by('fecha_vencimiento')
        proximos = con_stock.filter(fecha_vencimiento__gte=hoy, fecha_vencimiento__lte=hoy + timedelta(days=30)) \
            .order_by('fecha_vencimiento')
        ctx.update({'bajo_minimo': criticos.count(), 'criticos': criticos[:5],
                    'lotes_vencidos': vencidos[:5], 'n_lotes_vencidos': vencidos.count(),
                    'lotes_proximos': proximos[:5], 'n_lotes_proximos': proximos.count()})
    return render(request, 'core/inicio.html', ctx)


@never_cache
def salud(request):
    """Healthcheck para Railway: responde 200 si la app y la BD están vivas."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'estado': 'ok'})
    except Exception:  # pragma: no cover - solo falla con la BD caída
        return JsonResponse({'estado': 'error'}, status=503)
