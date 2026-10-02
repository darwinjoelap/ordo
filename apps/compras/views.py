from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere
from apps.inventario.models import Producto
from apps.proveedores.models import Proveedor

from . import servicios, sugerencias
from .forms import ItemForm, OrdenForm
from .models import ItemOrdenCompra, OrdenCompra
from .pdf import orden_compra_pdf, panel_pedido_pdf

Estado = OrdenCompra.Estado


@login_required
@requiere('compras.gestionar')
def lista(request):
    estado = request.GET.get('estado', '')
    ordenes = OrdenCompra.objects.select_related('proveedor').annotate(
        n_items=Count('items'),
        total=Sum(ExpressionWrapper(F('items__cantidad_pedida') * F('items__costo_unitario_usd'),
                                    output_field=DecimalField(max_digits=14, decimal_places=2))))
    if estado:
        ordenes = ordenes.filter(estado=estado)
    pagina = Paginator(ordenes, 30).get_page(request.GET.get('page'))
    return render(request, 'compras/lista.html', {
        'titulo': 'Órdenes de compra', 'pagina': pagina, 'estado': estado, 'estados': Estado.choices,
        'querystring': f'estado={estado}' if estado else ''})


@login_required
@requiere('compras.gestionar')
def crear(request):
    form = OrdenForm(request.POST or None, initial={'proveedor': request.GET.get('proveedor')})
    if request.method == 'POST' and form.is_valid():
        orden = servicios.crear_orden(form.cleaned_data['proveedor'], request.user, notas=form.cleaned_data['notas'])
        return redirect('compras:detalle', pk=orden.pk)
    return render(request, 'compras/crear.html', {'titulo': 'Nueva orden de compra', 'form': form,
                                                  'hay_proveedores': Proveedor.objects.exists()})


def _orden(pk):
    return get_object_or_404(OrdenCompra.objects.select_related('proveedor', 'creado_por'), pk=pk)


@login_required
@requiere('compras.gestionar')
def detalle(request, pk):
    orden = _orden(pk)
    items = list(orden.items.select_related('producto__unidad').order_by(
        'producto__categoria__nombre', 'producto__subcategoria__nombre', 'producto__nombre'))
    return render(request, 'compras/detalle.html', {
        'titulo': orden.numero, 'orden': orden, 'items': items,
        'total': sum((i.subtotal_usd for i in items), Decimal('0')),
        'form_notas': OrdenForm(instance=orden) if orden.editable else None,
    })


@login_required
@requiere('compras.gestionar')
@require_POST
def agregar_item(request, pk):
    orden = _orden(pk)
    form = ItemForm(request.POST)
    if form.is_valid():
        try:
            d = form.cleaned_data
            servicios.agregar_item(orden, d['producto'], d['cantidad'], d['costo'])
            messages.success(request, f'Agregado: {d["producto"].nombre}.')
        except servicios.ErrorCompra as e:
            messages.error(request, str(e))
    else:
        messages.error(request, 'Revisa cantidad y costo.')
    return redirect('compras:detalle', pk=pk)


@login_required
@requiere('compras.gestionar')
@require_POST
def actualizar_items(request, pk):
    """Guarda cantidades/costos editados en la tabla y quita los marcados."""
    orden = _orden(pk)
    if not orden.editable:
        messages.error(request, 'Solo se editan órdenes en borrador.')
        return redirect('compras:detalle', pk=pk)
    form = OrdenForm(request.POST, instance=orden)
    if form.is_valid():
        form.save()
    for item in orden.items.all():
        if request.POST.get(f'quitar_{item.pk}'):
            item.delete()
            continue
        try:
            cantidad = int(request.POST.get(f'cantidad_{item.pk}', item.cantidad_pedida))
            costo = Decimal(request.POST.get(f'costo_{item.pk}', item.costo_unitario_usd).replace(',', '.'))
        except (ValueError, InvalidOperation):
            messages.error(request, f'Valor inválido en {item.producto.nombre}.')
            continue
        if cantidad <= 0 or costo < 0:
            messages.error(request, f'{item.producto.nombre}: cantidad > 0 y costo ≥ 0.')
            continue
        item.cantidad_pedida, item.costo_unitario_usd = cantidad, costo
        item.save(update_fields=['cantidad_pedida', 'costo_unitario_usd'])
    messages.success(request, 'Orden actualizada.')
    return redirect('compras:detalle', pk=pk)


@login_required
@requiere('compras.gestionar')
@require_POST
def cambiar_estado(request, pk):
    orden = _orden(pk)
    try:
        servicios.cambiar_estado(orden, request.POST.get('estado'))
        messages.success(request, f'Orden {orden.numero}: {orden.get_estado_display()}.')
    except (servicios.ErrorCompra, ValueError) as e:
        messages.error(request, str(e))
    return redirect('compras:detalle', pk=pk)


@login_required
@requiere('compras.gestionar')
def recibir(request, pk):
    orden = _orden(pk)
    if not orden.recibible:
        messages.error(request, 'Esta orden no está pendiente de recepción.')
        return redirect('compras:detalle', pk=pk)
    items = [i for i in orden.items.select_related('producto__unidad') if i.pendiente > 0]
    errores = {}
    if request.method == 'POST':
        recepciones = []
        for i in items:
            p = request.POST
            try:
                cantidad = int(p.get(f'cantidad_{i.pk}') or 0)
                costo = Decimal((p.get(f'costo_{i.pk}') or str(i.costo_unitario_usd)).replace(',', '.'))
                venc_txt = p.get(f'vence_{i.pk}') or ''
                venc = datetime.strptime(venc_txt, '%Y-%m-%d').date() if venc_txt else None
            except (ValueError, InvalidOperation):
                errores[i.pk] = 'Valores inválidos.'
                continue
            if cantidad < 0 or cantidad > i.pendiente:
                errores[i.pk] = f'Entre 0 y {i.pendiente}.'
                continue
            if cantidad and i.producto.maneja_lotes and not p.get(f'lote_{i.pk}', '').strip():
                errores[i.pk] = 'Indica el lote.'
                continue
            if cantidad and i.producto.maneja_vencimiento and not venc:
                errores[i.pk] = 'Indica el vencimiento.'
                continue
            recepciones.append({'item': i, 'cantidad': cantidad, 'costo': costo, 'fecha_vencimiento': venc,
                                'numero_lote': p.get(f'lote_{i.pk}', '').strip()})
        if not errores:
            try:
                servicios.recibir(orden, recepciones, request.user)
            except servicios.ErrorCompra as e:
                messages.error(request, str(e))
            else:
                orden.refresh_from_db()
                messages.success(request, f'Recepción registrada. Orden: {orden.get_estado_display()}.')
                return redirect('compras:detalle', pk=pk)
    p = request.POST
    filas = [{
        'item': i, 'error': errores.get(i.pk, ''),
        'cantidad': p.get(f'cantidad_{i.pk}', i.pendiente), 'lote': p.get(f'lote_{i.pk}', ''),
        'vence': p.get(f'vence_{i.pk}', ''), 'costo': p.get(f'costo_{i.pk}', i.costo_unitario_usd),
    } for i in items]
    return render(request, 'compras/recibir.html', {'titulo': f'Recibir {orden.numero}', 'orden': orden,
                                                    'filas': filas})


@login_required
@requiere('compras.gestionar')
def pdf(request, pk):
    orden = _orden(pk)
    contenido = orden_compra_pdf(orden, request.empresa, mostrar_costos=request.GET.get('costos', '1') == '1')
    r = HttpResponse(contenido, content_type='application/pdf')
    r['Content-Disposition'] = f'inline; filename="{orden.numero}.pdf"'
    return r


# ── Panel de pedido ───────────────────────────────────────────────────────────

def _panel(request):
    """Filtros del panel (GET) → (grupos por proveedor, días, filtros)."""
    g = request.GET
    try:
        dias = max(1, min(365, int(g.get('dias', 30))))
    except ValueError:
        dias = 30
    f = {k: g.get(k, '') for k in ('proveedor', 'categoria', 'subcategoria', 'marca')}
    f['todos'] = g.get('todos') == '1'
    grupos = sugerencias.calcular(dias, f['proveedor'] or None, solo_necesarios=not f['todos'],
                                  categoria_id=f['categoria'] or None, subcategoria_id=f['subcategoria'] or None,
                                  marca_id=f['marca'] or None)
    return grupos, dias, f


@login_required
@requiere('compras.gestionar')
def panel_pedido(request):
    from apps.inventario.models import Categoria, Marca, Subcategoria
    grupos, dias, f = _panel(request)
    consulta = request.GET.copy()
    consulta.pop('c', None)
    return render(request, 'compras/panel_pedido.html', {
        'titulo': 'Panel de pedido', 'grupos': grupos, 'dias': dias, 'proveedor_id': f['proveedor'],
        'todos': f['todos'], 'f': f, 'proveedores': Proveedor.objects.filter(activo=True),
        'categorias': Categoria.objects.order_by('nombre'),
        'subcategorias': Subcategoria.objects.select_related('categoria').order_by('nombre'),
        'marcas': Marca.objects.order_by('nombre'),
        'resumen': sugerencias.por_clasificacion(grupos), 'querystring': consulta.urlencode(),
    })


@login_required
@requiere('compras.gestionar')
def panel_pedido_pdf_vista(request):
    """
    PDF del pedido clasificado por categoría › subcategoría, con total de unidades por clasificación.
    ?c=12:5,13:10 → cantidades escritas en el panel (producto:cantidad); sin "c" usa lo sugerido.
    """
    from apps.inventario.models import Categoria, Marca, Subcategoria
    grupos, dias, f = _panel(request)
    cantidades = None
    if 'c' in request.GET:
        cantidades = {}
        for par in request.GET['c'].split(','):
            try:
                pid, cant = par.split(':')
                cantidades[int(pid)] = max(0, int(cant))
            except ValueError:
                continue
    textos = []
    for clave, modelo, etiqueta in (('proveedor', Proveedor, 'Proveedor'), ('categoria', Categoria, 'Categoría'),
                                    ('subcategoria', Subcategoria, 'Subcategoría'), ('marca', Marca, 'Marca')):
        if f[clave] == 'ninguno':
            textos.append('Sin proveedor habitual')
        elif f[clave].isdigit():
            obj = modelo.objects.filter(pk=f[clave]).first()
            if obj:
                textos.append(f'{etiqueta}: {obj.nombre}')
    contenido = panel_pedido_pdf(request.empresa, sugerencias.por_clasificacion(grupos, cantidades), dias,
                                 ' · '.join(textos))
    r = HttpResponse(contenido, content_type='application/pdf')
    r['Content-Disposition'] = 'inline; filename="pedido.pdf"'
    return r


@login_required
@requiere('compras.gestionar')
@require_POST
def crear_desde_panel(request):
    """Crea UNA orden (borrador) para el proveedor elegido con los productos marcados."""
    proveedor = get_object_or_404(Proveedor, pk=request.POST.get('proveedor') or 0)
    items = []
    for pid in request.POST.getlist('producto'):
        producto = Producto.objects.filter(pk=pid, activo=True).first()
        if not producto:
            raise Http404
        try:
            cantidad = int(request.POST.get(f'cantidad_{pid}') or 0)
        except ValueError:
            cantidad = 0
        if cantidad > 0:
            items.append((producto, cantidad, producto.precio_costo_usd))
    if not items:
        messages.error(request, 'Marca al menos un producto con cantidad mayor que cero.')
        return redirect('compras:panel_pedido')
    orden = servicios.crear_orden(proveedor, request.user, items)
    messages.success(request, f'Orden {orden.numero} creada en borrador con {len(items)} productos. Revísala y envíala.')
    return redirect('compras:detalle', pk=orden.pk)
