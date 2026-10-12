"""Despacho por almacén: bandeja, registro de entregas, confirmación del vendedor y constancias."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.pdf import nombre_corto, respuesta_pdf
from apps.core.permisos import requiere, tiene_permiso

from . import entregas as srv
from .models import Entrega, Presupuesto
from .pdf import entrega_pdf
from .servicios import ErrorVenta
from .views import visibles

E = Presupuesto.Estado


def _activo(request):
    if not srv.activo(request.empresa):
        raise Http404('La gestión de despacho por almacén no está activa.')


def _almacenes_inv(request):
    from apps.inventario.almacenes import opciones
    return opciones(request)


def venta_para_despacho(request, pk):
    """Almacén ve cualquier venta confirmada; el vendedor, solo las suyas (las que ya ve)."""
    if tiene_permiso(request, 'despacho.gestionar'):
        qs = Presupuesto.objects.filter(estado__in=(*Presupuesto.CONFIRMADAS, E.DEVUELTA))
    elif tiene_permiso(request, 'presupuestos.crear'):
        qs = visibles(request)
    else:
        raise PermissionDenied
    return get_object_or_404(qs.select_related('cliente', 'vendedor'), pk=pk)


@login_required
@requiere('despacho.gestionar')
def bandeja(request):
    _activo(request)
    q = request.GET.get('q', '').strip()
    base = Presupuesto.objects.all()
    almacen = request.GET.get('almacen', '')
    if request.empresa.perfil.multialmacen and almacen:
        base = base.filter(almacen__isnull=True) if almacen == 'SIN' else base.filter(almacen_id=almacen)
    if q:
        base = base.filter(Q(numero__icontains=q) | Q(cliente__nombre__icontains=q))
    pendientes = list(srv.bandeja(base).select_related('almacen'))
    con_entregas = set(Entrega.objects.filter(presupuesto__in=pendientes).values_list('presupuesto_id', flat=True))
    for p in pendientes:
        p.estado_despacho = 'PARCIAL' if p.pk in con_entregas else 'PENDIENTE'
    transito = list(srv.transito_de(base))
    transito_ids = {e.presupuesto_id for e in transito}
    pendientes = [p for p in pendientes if not (p.pk in transito_ids and all(n == 0 for _, _, n in srv.pendientes(p)))]
    recientes = Entrega.objects.select_related('presupuesto__cliente', 'entregado_por').order_by('-entregado_en')[:15]
    return render(request, 'ventas/almacen_bandeja.html', {
        'titulo': 'Despacho', 'pendientes': pendientes, 'transito': transito, 'recientes': recientes, 'q': q,
        'almacenes': _almacenes_inv(request), 'almacen': almacen,
    })


@login_required
def despachar(request, pk):
    _activo(request)
    p = venta_para_despacho(request, pk)
    puede = tiene_permiso(request, 'despacho.gestionar')
    if request.method == 'POST':
        if not puede:
            raise PermissionDenied
        try:
            cantidades = {}
            for i, _, _ in srv.pendientes(p):
                valor = request.POST.get(f'cant_{i.pk}', '').strip()
                cantidades[i.pk] = int(valor) if valor else 0
            entrega = srv.registrar(p, request.user, cantidades, request.POST.get('recibe', ''),
                                    request.POST.get('nombre', ''), request.POST.get('cedula', ''),
                                    request.POST.get('observaciones', ''), request.POST.get('firma', ''))
        except ValueError:
            messages.error(request, 'Revisa las cantidades.')
        except ErrorVenta as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'Entrega {entrega.numero} registrada.'
                             + (' Queda en tránsito hasta que el vendedor confirme la entrega al cliente.'
                                if entrega.en_transito else ''))
            return redirect('ventas:despachar', pk=p.pk)
    lineas = srv.pendientes(p)
    return render(request, 'ventas/almacen_despachar.html', {
        'titulo': f'Despacho {p.numero}', 'p': p, 'lineas': lineas, 'puede': puede,
        'hay_pendiente': any(n for _, _, n in lineas), 'estado': srv.ETIQUETAS[srv.estado(p)],
        'entregas': Entrega.objects.filter(presupuesto=p).select_related('entregado_por', 'cliente_confirmado_por'),
        'recibe': Entrega.Recibe.choices, 'puede_anular': tiene_permiso(request, 'ventas.validar'),
    })


@login_required
@require_POST
def confirmar_cliente(request, pk, entrega_id):
    _activo(request)
    p = venta_para_despacho(request, pk)
    entrega = get_object_or_404(Entrega, pk=entrega_id, presupuesto=p)
    if not (p.vendedor_id == request.user.pk or tiene_permiso(request, 'ventas.validar')):
        raise PermissionDenied
    try:
        srv.confirmar_cliente(entrega, request.user, request.POST.get('nombre', ''), request.POST.get('cedula', ''),
                              request.POST.get('firma', ''))
        messages.success(request, 'Entrega al cliente confirmada.')
    except ErrorVenta as e:
        messages.error(request, str(e))
    if request.POST.get('volver') == 'despacho':
        return redirect('ventas:despachar', pk=pk)
    return redirect('ventas:detalle', pk=pk)


@login_required
@requiere('ventas.validar')
@require_POST
def anular_entrega(request, pk, entrega_id):
    _activo(request)
    p = venta_para_despacho(request, pk)
    entrega = get_object_or_404(Entrega, pk=entrega_id, presupuesto=p)
    srv.anular(entrega)
    messages.success(request, f'Entrega {entrega.numero} anulada: sus cantidades vuelven a estar por despachar.')
    return redirect('ventas:despachar', pk=pk)


@login_required
def constancia_pdf(request, pk, entrega_id):
    p = venta_para_despacho(request, pk)
    entrega = get_object_or_404(Entrega.objects.select_related('entregado_por'), pk=entrega_id, presupuesto=p)
    return respuesta_pdf(entrega_pdf(entrega, request.empresa), entrega.numero, nombre_corto(p.cliente.nombre),
                         entrega.entregado_en.date())
