from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permisos import requiere, tiene_permiso

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
    from apps.ventas.models import Presupuesto
    presupuestos = Presupuesto.objects.filter(cliente=cliente).order_by('-creado_en')[:20]
    return render(request, 'clientes/detalle.html', {'titulo': cliente.nombre, 'cliente': cliente,
                                                     'presupuestos': presupuestos})


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
