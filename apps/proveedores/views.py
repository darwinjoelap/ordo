from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permisos import requiere
from apps.inventario.models import Lote

from .forms import ProveedorForm
from .models import Proveedor


@login_required
@requiere('proveedores.gestionar')
def lista(request):
    q = request.GET.get('q', '').strip()
    proveedores = Proveedor.objects.annotate(n_productos=Count('productos', distinct=True))
    if q:
        proveedores = proveedores.filter(Q(nombre__icontains=q) | Q(rif__icontains=q) | Q(contacto__icontains=q))
    pagina = Paginator(proveedores, 50).get_page(request.GET.get('page'))
    return render(request, 'proveedores/lista.html', {'titulo': 'Proveedores', 'pagina': pagina, 'q': q,
                                                      'querystring': urlencode({'q': q}) if q else ''})


@login_required
@requiere('proveedores.gestionar')
def detalle(request, pk):
    proveedor = get_object_or_404(Proveedor, pk=pk)
    lotes = Lote.objects.filter(proveedor=proveedor).select_related('producto').order_by('-fecha_ingreso', '-pk')[:20]
    return render(request, 'proveedores/detalle.html', {'titulo': proveedor.nombre, 'proveedor': proveedor,
                                                        'lotes': lotes})


@login_required
@requiere('proveedores.gestionar')
def formulario(request, pk=None):
    proveedor = get_object_or_404(Proveedor, pk=pk) if pk else None
    form = ProveedorForm(request.POST or None, instance=proveedor)
    if request.method == 'POST' and form.is_valid():
        proveedor = form.save()
        messages.success(request, f'Proveedor "{proveedor}" guardado.')
        return redirect('proveedores:detalle', pk=proveedor.pk)
    return render(request, 'proveedores/form.html', {
        'titulo': f'Editar {proveedor}' if proveedor else 'Nuevo proveedor', 'form': form, 'proveedor': proveedor})
