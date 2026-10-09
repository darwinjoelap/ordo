from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.permisos import requiere, tiene_permiso

from . import estado_cuenta
from .forms import ClienteForm
from .permisos import clientes_visibles


@login_required
@requiere('clientes.gestionar')
def lista(request):
    q = request.GET.get('q', '').strip()
    clientes = clientes_visibles(request).select_related('vendedor')
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(rif__icontains=q) | Q(contacto__icontains=q))
    pagina = Paginator(clientes.order_by('nombre', 'pk'), 50).get_page(request.GET.get('page'))
    return render(request, 'clientes/lista.html', {'titulo': 'Clientes', 'pagina': pagina, 'q': q,
                                                   'querystring': urlencode({'q': q}) if q else ''})


@login_required
@requiere('clientes.gestionar')
def detalle(request, pk):
    cliente = get_object_or_404(clientes_visibles(request).select_related('vendedor'), pk=pk)
    base, docs, filtro, desde, hasta = _estado_cuenta(request, cliente)
    pagina = Paginator(docs, 30).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'clientes/detalle.html', {
        'titulo': cliente.nombre, 'cliente': cliente, 'pagina': pagina, 'filtro': filtro,
        'filtros': [(k, etq, n) for (k, (etq, _)), n in zip(estado_cuenta.FILTROS.items(), estado_cuenta.conteos(base).values())],
        'totales': estado_cuenta.totales(docs), 'desde': desde, 'hasta': hasta, 'querystring': params.urlencode(),
        'saldo_total': estado_cuenta.totales(estado_cuenta.documentos(base, 'por_cobrar')[0])['saldo'],
    })


def _estado_cuenta(request, cliente):
    from apps.ventas.views import _fecha_o_none, visibles
    base = visibles(request).filter(cliente=cliente)
    desde, hasta = _fecha_o_none(request.GET.get('desde')), _fecha_o_none(request.GET.get('hasta'))
    docs, filtro = estado_cuenta.documentos(base, request.GET.get('filtro', 'todos'), desde, hasta)
    return base, docs, filtro, desde, hasta


@login_required
@requiere('clientes.gestionar')
def estado_cuenta_pdf(request, pk):
    from apps.core.pdf import nombre_corto, respuesta_pdf
    cliente = get_object_or_404(clientes_visibles(request), pk=pk)
    _, docs, filtro, desde, hasta = _estado_cuenta(request, cliente)
    contenido = estado_cuenta.pdf(cliente, list(docs), filtro, request.empresa, desde, hasta)
    return respuesta_pdf(contenido, 'Estado-cuenta', nombre_corto(cliente.nombre), filtro.replace('_', '-'),
                         timezone.localdate())


@login_required
@requiere('clientes.gestionar')
def estado_cuenta_excel(request, pk):
    from apps.core.pdf import nombre_archivo, nombre_corto
    cliente = get_object_or_404(clientes_visibles(request), pk=pk)
    _, docs, filtro, desde, hasta = _estado_cuenta(request, cliente)
    r = HttpResponse(estado_cuenta.excel(cliente, list(docs), filtro, desde, hasta),
                     content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    nombre = nombre_archivo('Estado-cuenta', nombre_corto(cliente.nombre), filtro.replace('_', '-'),
                            timezone.localdate(), extension='xlsx')
    r['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return r


@login_required
@requiere('clientes.gestionar')
def formulario(request, pk=None):
    cliente = get_object_or_404(clientes_visibles(request), pk=pk) if pk else None
    puede_asignar = tiene_permiso(request, 'presupuestos.ver_todos')
    form = ClienteForm(request.POST or None, instance=cliente, puede_asignar=puede_asignar, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        cliente = form.save(commit=False)
        if not puede_asignar and not cliente.vendedor_id:
            cliente.vendedor = request.user
        cliente.save()
        messages.success(request, f'Cliente "{cliente}" guardado.')
        siguiente = request.GET.get('volver')
        if siguiente == 'presupuesto':
            return redirect(f"/ventas/nuevo/?cliente={cliente.pk}")
        return redirect('clientes:detalle', pk=cliente.pk)
    return render(request, 'clientes/form.html', {
        'titulo': f'Editar {cliente}' if cliente else 'Nuevo cliente', 'form': form, 'cliente': cliente})
