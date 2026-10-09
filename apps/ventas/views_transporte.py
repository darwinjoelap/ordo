"""Catálogo de transportistas y vehículos para las notas de despacho."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere

from .models import Transportista, Vehiculo
from .servicios import normalizar_placa


def _texto(request, campo, largo):
    return ' '.join(request.POST.get(campo, '').split())[:largo]


@login_required
@requiere('transporte.gestionar')
def lista(request):
    editar_t = request.GET.get('t')
    editar_v = request.GET.get('v')
    return render(request, 'ventas/transporte.html', {
        'titulo': 'Transporte', 'transportistas': Transportista.objects.all(), 'vehiculos': Vehiculo.objects.all(),
        't_editar': Transportista.objects.filter(pk=editar_t).first() if editar_t else None,
        'v_editar': Vehiculo.objects.filter(pk=editar_v).first() if editar_v else None,
    })


@login_required
@requiere('transporte.gestionar')
@require_POST
def transportista_guardar(request, pk=None):
    t = get_object_or_404(Transportista, pk=pk) if pk else Transportista()
    nombre = _texto(request, 'nombre', 120)
    if not nombre:
        messages.error(request, 'Escribe el nombre del transportista.')
        return redirect('ventas:transporte')
    repetido = Transportista.objects.filter(nombre__iexact=nombre).exclude(pk=t.pk).first()
    if repetido:
        messages.error(request, f'Ya existe un transportista llamado «{repetido.nombre}».')
        return redirect('ventas:transporte')
    t.nombre, t.cedula = nombre, _texto(request, 'cedula', 20).upper()
    t.telefono, t.empresa_transporte = _texto(request, 'telefono', 30), _texto(request, 'empresa_transporte', 120)
    t.save()
    messages.success(request, f'Transportista guardado: {t.nombre}.')
    return redirect('ventas:transporte')


@login_required
@requiere('transporte.gestionar')
@require_POST
def vehiculo_guardar(request, pk=None):
    v = get_object_or_404(Vehiculo, pk=pk) if pk else Vehiculo()
    placa = normalizar_placa(request.POST.get('placa'))
    if not placa:
        messages.error(request, 'Escribe la placa del vehículo.')
        return redirect('ventas:transporte')
    if Vehiculo.objects.filter(placa=placa).exclude(pk=v.pk).exists():
        messages.error(request, f'La placa {placa} ya está registrada.')
        return redirect('ventas:transporte')
    v.placa, v.descripcion = placa, _texto(request, 'descripcion', 120)
    v.save()
    messages.success(request, f'Vehículo guardado: {v.placa}.')
    return redirect('ventas:transporte')


@login_required
@requiere('transporte.gestionar')
@require_POST
def activar(request, tipo, pk):
    """Desactivar no borra: el registro deja de ofrecerse en las notas nuevas, las viejas no cambian."""
    modelo = Transportista if tipo == 't' else Vehiculo
    obj = get_object_or_404(modelo, pk=pk)
    obj.activo = not obj.activo
    obj.save(update_fields=['activo'])
    messages.success(request, f'{obj}: {"activado" if obj.activo else "desactivado"}.')
    return redirect('ventas:transporte')
