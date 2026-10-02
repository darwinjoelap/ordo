"""Devoluciones de ventas validadas (total o parcial). La lógica vive en servicios.devolver."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.permisos import requiere, tiene_permiso
from apps.core.pdf import nombre_corto, respuesta_pdf

from . import servicios
from .models import Devolucion, ItemDevolucion, ItemPresupuesto, Presupuesto
from .pdf import devolucion_pdf
from .views import _presupuesto, visibles


def _devoluciones_visibles(request):
    return Devolucion.objects.filter(presupuesto__in=visibles(request)).select_related(
        'presupuesto__cliente', 'presupuesto__vendedor', 'creada_por')


def _fecha(texto):
    return date.fromisoformat(texto) if texto else None


@login_required
@requiere('ventas.devolver')
def devolver(request, pk):
    p = _presupuesto(request, pk)
    if p.estado != Presupuesto.Estado.VALIDADA:
        messages.error(request, 'Solo se pueden devolver ventas validadas.')
        return redirect('ventas:detalle', pk=pk)
    ya = servicios.devuelto_por_item(p)
    items = list(ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto__unidad')
                 .order_by(Lower('producto__nombre'), 'pk'))
    for i in items:
        i.devuelto = ya.get(i.pk, 0)
        i.maximo = i.cantidad - i.devuelto
        i.pedido, i.reingresa = 0, True
    datos = {'motivo': '', 'fecha': timezone.localdate(), 'reembolso': False, 'monto': '', 'metodo': '',
             'fecha_reembolso': '', 'referencia': ''}
    if request.method == 'POST':
        post = request.POST
        datos.update(motivo=post.get('motivo', ''), reembolso=post.get('reembolso') == '1',
                     monto=post.get('reembolso_monto', ''), metodo=post.get('reembolso_metodo', ''),
                     fecha_reembolso=post.get('reembolso_fecha', ''), referencia=post.get('reembolso_referencia', ''))
        try:
            lineas = {}
            for i in items:
                i.pedido = int(post.get(f'cantidad_{i.pk}') or 0)
                i.reingresa = post.get(f'reingresa_{i.pk}') == '1'
                lineas[i.pk] = (i.pedido, i.reingresa)
            datos['fecha'] = _fecha(post.get('fecha')) or timezone.localdate()
            reembolso = None
            if datos['reembolso']:
                monto = datos['monto'].strip().replace(',', '.')
                reembolso = {'monto_usd': Decimal(monto) if monto else None, 'metodo': datos['metodo'],
                             'fecha': _fecha(datos['fecha_reembolso']), 'referencia': datos['referencia']}
            dev = servicios.devolver(p, request.user, lineas, datos['motivo'], datos['fecha'], reembolso)
        except (ValueError, InvalidOperation):
            messages.error(request, 'Hay cantidades, montos o fechas inválidos.')
        except servicios.ErrorVenta as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'Devolución {dev.numero} registrada por {dev.total_usd} USD.')
            return redirect('ventas:devolucion', pk=dev.pk)
    return render(request, 'ventas/devolver.html', {
        'titulo': f'Devolución de {p.numero}', 'p': p, 'items': items, 'datos': datos,
        'metodos': Presupuesto.MetodoPago.choices,
        'previas': Devolucion.objects.filter(presupuesto=p).order_by('creada_en'),
    })


@login_required
@requiere('presupuestos.crear')
def detalle(request, pk):
    dev = get_object_or_404(_devoluciones_visibles(request), pk=pk)
    if request.method == 'POST':
        if not tiene_permiso(request, 'ventas.devolver'):
            messages.error(request, 'Tu rol no permite esta acción.')
            return redirect('ventas:devolucion', pk=pk)
        try:
            monto = request.POST.get('reembolso_monto', '').strip().replace(',', '.')
            servicios.registrar_reembolso(dev, Decimal(monto) if monto else None,
                                          request.POST.get('reembolso_metodo', ''),
                                          _fecha(request.POST.get('reembolso_fecha')),
                                          request.POST.get('reembolso_referencia', ''))
            messages.success(request, 'Reembolso registrado.')
        except (ValueError, InvalidOperation):
            messages.error(request, 'Monto o fecha inválidos.')
        except servicios.ErrorVenta as e:
            messages.error(request, str(e))
        return redirect('ventas:devolucion', pk=pk)
    lineas = ItemDevolucion.objects.filter(devolucion=dev).select_related('item__producto__unidad', 'lote')
    ajuste = None
    if tiene_permiso(request, 'comisiones.liquidar') or dev.presupuesto.vendedor_id == request.user.pk:
        from apps.comisiones.models import AjusteComision
        ajuste = AjusteComision.objects.filter(devolucion=dev).select_related('liquidacion').first()
    return render(request, 'ventas/devolucion.html', {
        'titulo': dev.numero, 'dev': dev, 'p': dev.presupuesto, 'lineas': lineas, 'ajuste': ajuste,
        'metodos': Presupuesto.MetodoPago.choices, 'puede_devolver': tiene_permiso(request, 'ventas.devolver'),
    })


@login_required
@requiere('ventas.devolver')
def lista(request):
    q = request.GET.get('q', '').strip()
    qs = _devoluciones_visibles(request)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(presupuesto__numero__icontains=q)
                       | Q(presupuesto__cliente__nombre__icontains=q))
    totales = qs.aggregate(usd=Sum('total_usd'), reembolsado=Sum('reembolso_usd'))
    pagina = Paginator(qs.order_by('-creada_en', '-pk'), 30).get_page(request.GET.get('page'))
    return render(request, 'ventas/devoluciones.html', {
        'titulo': 'Devoluciones', 'pagina': pagina, 'q': q, 'totales': totales})


@login_required
@requiere('presupuestos.crear')
def pdf(request, pk):
    dev = get_object_or_404(_devoluciones_visibles(request), pk=pk)
    return respuesta_pdf(devolucion_pdf(dev, request.empresa), dev.numero,
                         nombre_corto(dev.presupuesto.cliente.nombre), dev.fecha)
