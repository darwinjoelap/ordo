from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from . import plataforma
from .forms import EditarEmpresaForm, NuevaEmpresaForm
from .models import Empresa, Membresia


def solo_plataforma(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return login_required(envoltura)


def _enlace(request, empresa):
    return request.build_absolute_uri(f'/{empresa.slug}/')


@solo_plataforma
def lista(request):
    q = request.GET.get('q', '').strip()
    empresas = (Empresa.objects.select_related('perfil')
                .annotate(n_activos=Count('membresias', filter=Q(membresias__activa=True))).order_by('nombre'))
    if q:
        empresas = empresas.filter(Q(nombre__icontains=q) | Q(slug__icontains=q) | Q(perfil__rif__icontains=q)
                                   | Q(perfil__razon_social__icontains=q))
    empresas = list(empresas)
    for e in empresas:
        e.enlace = _enlace(request, e)
    return render(request, 'plataforma/lista.html', {'titulo': 'Empresas', 'empresas': empresas, 'q': q})


@solo_plataforma
def nueva(request):
    form = NuevaEmpresaForm(request.POST or None, initial={'plan': Empresa.Plan.PRUEBA})
    if request.method == 'POST' and form.is_valid():
        empresa, dueno, clave = plataforma.crear_empresa(form.cleaned_data)
        return render(request, 'plataforma/creada.html', {
            'titulo': 'Empresa creada', 'empresa': empresa, 'dueno': dueno, 'clave': clave,
            'enlace': _enlace(request, empresa)})
    return render(request, 'plataforma/form.html', {'titulo': 'Nueva empresa', 'form': form})


@solo_plataforma
def editar(request, pk):
    empresa = get_object_or_404(Empresa.objects.select_related('perfil'), pk=pk)
    inicial = {'nombre_comercial': empresa.nombre, 'razon_social': empresa.perfil.razon_social,
               'rif': empresa.perfil.rif, 'slug': empresa.slug, 'plan': empresa.plan, 'estado': empresa.estado,
               'activa_hasta': empresa.activa_hasta, 'limite_usuarios': empresa.limite_usuarios,
               'notas': empresa.notas}
    form = EditarEmpresaForm(request.POST or None, initial=inicial, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        datos = dict(form.cleaned_data, nombre=form.cleaned_data['nombre_comercial'])
        plataforma.actualizar_empresa(empresa, datos)
        messages.success(request, f'{empresa.nombre}: cambios guardados.')
        return redirect('plataforma:editar', pk=pk)
    miembros = Membresia.objects.filter(empresa=empresa).select_related('usuario').order_by('-activa', 'rol')
    return render(request, 'plataforma/form.html', {
        'titulo': empresa.nombre, 'form': form, 'empresa': empresa, 'miembros': miembros,
        'enlace': _enlace(request, empresa)})
