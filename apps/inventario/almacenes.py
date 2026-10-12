"""Multialmacén: helpers para formularios y las pantallas de almacenes y traslados."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.pdf import respuesta_pdf
from apps.core.permisos import requiere

from . import servicios
from .models import Almacen, ItemTraslado, Lote, Traslado


def activo(request):
    return bool(getattr(request, 'empresa', None) and request.empresa.perfil.multialmacen)


def asegurar_principal():
    """Al activar multialmacén se crea «Almacén principal» si no hay ninguno."""
    if not Almacen.objects.exists():
        Almacen.objects.create(nombre='Almacén principal', principal=True)


def opciones(request):
    """Almacenes para elegir en ingresos y recepciones (vacío si multialmacén está apagado)."""
    if not activo(request):
        return []
    return list(Almacen.objects.filter(activo=True))


def elegido(request, campo='almacen'):
    """Almacén elegido en un formulario. Con multialmacén activo y sin elección: el principal."""
    if not activo(request):
        return None
    valor = request.POST.get(campo) or request.GET.get(campo)
    if valor:
        return Almacen.objects.filter(pk=valor, activo=True).first() or servicios.principal()
    return servicios.principal()


def _origen(valor):
    """'' o 'SIN' → None (Sin almacén); id → Almacen."""
    if not valor or valor == 'SIN':
        return None
    return get_object_or_404(Almacen, pk=valor)


def _exigir(request):
    if not activo(request):
        raise Http404('Multialmacén no está activo.')


# ── Pantallas ─────────────────────────────────────────────────────────────────

@login_required
@requiere('inventario.gestionar')
def lista(request):
    _exigir(request)
    asegurar_principal()
    resumen = {r['almacen']: r for r in Lote.objects.filter(cantidad_actual__gt=0).values('almacen').annotate(
        unidades=Sum('cantidad_actual'), apartadas=Sum('cantidad_apartada'), productos=Count('producto', distinct=True))}
    almacenes = list(Almacen.objects.select_related('responsable'))
    for a in almacenes:
        a.resumen = resumen.get(a.pk, {})
    sin = resumen.get(None, {})
    editar = Almacen.objects.filter(pk=request.GET.get('editar')).first() if request.GET.get('editar') else None
    usuarios = get_user_model().objects.filter(membresias__empresa=request.empresa, membresias__activa=True).distinct()
    return render(request, 'inventario/almacenes.html', {
        'titulo': 'Almacenes', 'almacenes': almacenes, 'sin': sin, 'editar': editar, 'usuarios': usuarios,
        'traslados': Traslado.objects.select_related('origen', 'destino', 'usuario')[:10],
    })


@login_required
@requiere('inventario.gestionar')
@require_POST
def guardar(request, pk=None):
    _exigir(request)
    a = get_object_or_404(Almacen, pk=pk) if pk else Almacen()
    nombre = ' '.join(request.POST.get('nombre', '').split())[:80]
    if not nombre:
        messages.error(request, 'Escribe el nombre del almacén.')
        return redirect('inventario:almacenes')
    if Almacen.objects.filter(nombre__iexact=nombre).exclude(pk=a.pk).exists():
        messages.error(request, f'Ya existe un almacén llamado «{nombre}».')
        return redirect('inventario:almacenes')
    a.nombre, a.direccion = nombre, request.POST.get('direccion', '').strip()[:200]
    a.responsable = get_user_model().objects.filter(pk=request.POST.get('responsable') or 0,
                                                    membresias__empresa=request.empresa).first()
    a.save()
    if request.POST.get('principal') == '1' or not Almacen.objects.filter(principal=True).exclude(pk=a.pk).exists():
        Almacen.objects.exclude(pk=a.pk).update(principal=False)
        Almacen.objects.filter(pk=a.pk).update(principal=True, activo=True)
    messages.success(request, f'Almacén guardado: {a.nombre}.')
    return redirect('inventario:almacenes')


@login_required
@requiere('inventario.gestionar')
@require_POST
def activar(request, pk):
    _exigir(request)
    a = get_object_or_404(Almacen, pk=pk)
    if a.activo:
        if a.principal:
            messages.error(request, 'El almacén principal no se puede desactivar: marca otro como principal primero.')
            return redirect('inventario:almacenes')
        if Lote.objects.filter(almacen=a, cantidad_actual__gt=0).exists():
            messages.error(request, f'«{a.nombre}» todavía tiene existencia: trasládala antes de desactivarlo.')
            return redirect('inventario:almacenes')
    a.activo = not a.activo
    a.save(update_fields=['activo'])
    messages.success(request, f'{a.nombre}: {"activado" if a.activo else "desactivado"}.')
    return redirect('inventario:almacenes')


@login_required
@requiere('inventario.gestionar')
def traslado_nuevo(request):
    _exigir(request)
    asegurar_principal()
    origen_txt = request.POST.get('origen', request.GET.get('origen', 'SIN'))
    origen = _origen(origen_txt)
    q = request.GET.get('q', '').strip()
    lotes = servicios.lotes_trasladables(origen)
    if q:
        lotes = lotes.filter(Q(producto__nombre__icontains=q) | Q(producto__codigo__icontains=q) | Q(numero_lote__icontains=q))
    if request.method == 'POST':
        destino = Almacen.objects.filter(pk=request.POST.get('destino') or 0, activo=True).first()
        try:
            if request.POST.get('todo') == '1':
                t = servicios.trasladar_todo(origen, destino, request.user)
            else:
                lineas = []
                for lote in servicios.lotes_trasladables(origen):
                    valor = request.POST.get(f'cant_{lote.pk}', '').strip()
                    if valor:
                        lineas.append((lote, int(valor)))
                t = servicios.trasladar(origen, destino, lineas, request.user, request.POST.get('notas', ''))
        except ValueError:
            messages.error(request, 'Revisa las cantidades.')
        except servicios.ErrorInventario as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'Traslado {t.numero} registrado.')
            return redirect('inventario:traslado', pk=t.pk)
    return render(request, 'inventario/traslado_nuevo.html', {
        'titulo': 'Nuevo traslado', 'origen_txt': origen_txt or 'SIN', 'origen': origen, 'q': q,
        'lotes': list(lotes[:300]), 'almacenes': Almacen.objects.filter(activo=True),
        'hay_sin': Lote.objects.filter(almacen__isnull=True, cantidad_actual__gt=0).exists(),
    })


@login_required
@requiere('inventario.gestionar')
def traslado(request, pk):
    _exigir(request)
    t = get_object_or_404(Traslado.objects.select_related('origen', 'destino', 'usuario'), pk=pk)
    return render(request, 'inventario/traslado.html', {
        'titulo': t.numero, 't': t,
        'items': ItemTraslado.objects.filter(traslado=t).select_related('producto__unidad', 'lote_origen'),
    })


@login_required
@requiere('inventario.gestionar')
def traslados(request):
    _exigir(request)
    return render(request, 'inventario/traslados.html', {
        'titulo': 'Traslados', 'traslados': Traslado.objects.select_related('origen', 'destino', 'usuario')
        .annotate(n=Count('items'), unidades=Sum('items__cantidad'))[:200],
    })


@login_required
@requiere('inventario.gestionar')
def traslado_pdf(request, pk):
    _exigir(request)
    t = get_object_or_404(Traslado.objects.select_related('origen', 'destino', 'usuario'), pk=pk)
    from .pdf import traslado_pdf as generar
    items = list(ItemTraslado.objects.filter(traslado=t).select_related('producto__unidad', 'lote_origen'))
    return respuesta_pdf(generar(t, items, request.empresa), t.numero, t.fecha.date())
