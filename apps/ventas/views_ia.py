"""«Cargar con IA» en un presupuesto: pedido (texto, fotos o PDF) → revisión → agregar. Ver carga_ia.py."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core import gemini
from apps.core.permisos import requiere, tiene_permiso
from apps.inventario.models import Producto

from . import carga_ia, servicios
from .models import UsoIA
from .views import _presupuesto

log = logging.getLogger('apps.ventas')


def _presupuesto_ia(request, pk):
    if not request.empresa.perfil.carga_ia_presupuestos:
        raise Http404
    p = _presupuesto(request, pk)
    if not p.editable:
        messages.error(request, 'Este presupuesto ya no se puede modificar.')
        return p, redirect('ventas:detalle', pk=pk)
    return p, None


def _ctx(p, **extra):
    return {'p': p, 'titulo': f'Cargar con IA · {p.numero or "Presupuesto"}', 'prueba': gemini.en_prueba(),
            'max_archivos': carga_ia.MAX_ARCHIVOS, **extra}


@login_required
@requiere('presupuestos.crear')
def cargar(request, pk):
    p, salida = _presupuesto_ia(request, pk)
    if salida:
        return salida
    if request.method != 'POST':
        return render(request, 'ventas/carga_ia.html', _ctx(p))

    texto = request.POST.get('texto', '')
    archivos_subidos = request.FILES.getlist('archivos')
    origen = UsoIA.Origen.MIXTO if texto.strip() and archivos_subidos else (
        UsoIA.Origen.ARCHIVO if archivos_subidos else UsoIA.Origen.TEXTO)
    uso = UsoIA(presupuesto=p, usuario=request.user, origen=origen, archivos=len(archivos_subidos))
    try:
        archivos = carga_ia.validar_archivos(archivos_subidos)
        resultado = carga_ia.procesar(texto, archivos, request.empresa.perfil)
    except (carga_ia.ErrorPedido, gemini.ErrorIA) as e:
        if isinstance(e, gemini.ErrorIA):            # el error del proveedor sí se registra (cuenta como intento)
            uso.ok, uso.error = False, str(e)[:300]
            uso.save()
            log.warning('IA presupuesto %s: %s', p.pk, e)
        messages.error(request, str(e))
        return render(request, 'ventas/carga_ia.html', _ctx(p, texto=texto))
    uso.lineas, uso.sugeridas = len(resultado.lineas), resultado.sugeridas
    uso.modelo, uso.tokens_entrada, uso.tokens_salida = resultado.modelo, resultado.tokens_entrada, resultado.tokens_salida
    uso.costo_usd = gemini.costo_usd(resultado.tokens_entrada, resultado.tokens_salida)
    uso.save()
    return render(request, 'ventas/carga_ia_revision.html', _ctx(p, resultado=resultado, uso=uso))


@login_required
@requiere('presupuestos.crear')
@require_POST
def agregar(request, pk):
    p, salida = _presupuesto_ia(request, pk)
    if salida:
        return salida
    perfil = request.empresa.perfil
    puede_fijar = tiene_permiso(request, 'precios.fijar')
    productos = Producto.objects.filter(activo=True)
    if not perfil.maneja_servicios:
        productos = productos.fisicos()
    agregados, errores = [], []
    try:
        n = min(int(request.POST.get('n', 0)), carga_ia.MAX_LINEAS)
    except ValueError:
        n = 0
    for i in range(n):
        if not request.POST.get(f'incluir_{i}') or not request.POST.get(f'producto_{i}'):
            continue
        producto = productos.filter(pk=request.POST.get(f'producto_{i}')).first()
        if producto is None:
            continue
        try:
            cantidad = int(request.POST.get(f'cantidad_{i}') or 1)
            servicios.agregar_item(p, producto, cantidad, None, perfil, puede_fijar)
            agregados.append(producto.nombre)
        except ValueError:
            errores.append(f'{producto.nombre}: cantidad inválida.')
        except servicios.ErrorVenta as e:
            errores.append(f'{producto.nombre}: {e}')
    uso = UsoIA.objects.filter(pk=request.POST.get('uso'), presupuesto=p).first()
    if uso:
        uso.agregadas = len(agregados)
        uso.save(update_fields=['agregadas'])
    for e in errores:
        messages.error(request, e)
    if agregados:
        messages.success(request, f'Agregado{"s" if len(agregados) > 1 else ""} {len(agregados)} producto'
                                  f'{"s" if len(agregados) > 1 else ""} desde el pedido. Revisa precios y stock.')
    elif not errores:
        messages.info(request, 'No se agregó ningún producto.')
    return redirect(reverse('ventas:detalle', args=[pk]) + '#agregar')
