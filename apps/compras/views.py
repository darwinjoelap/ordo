from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.inventario import almacenes as almacenes_inv
from apps.core.permisos import requiere
from apps.inventario.models import Producto
from apps.proveedores.models import Proveedor
from apps.core.numeros import numero
from apps.core.pdf import nombre_corto, respuesta_pdf

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
    errores = 0
    for item in orden.items.select_related('producto'):
        if request.POST.get(f'quitar_{item.pk}'):
            item.delete()
            continue
        nombre = item.producto.nombre
        texto_cant = request.POST.get(f'cantidad_{item.pk}', str(item.cantidad_pedida)).strip()
        texto_costo = request.POST.get(f'costo_{item.pk}', str(item.costo_unitario_usd)).strip()
        cantidad, costo = numero(texto_cant), numero(texto_costo)
        if cantidad is None or cantidad != int(cantidad):
            messages.error(request, f'{nombre}: la cantidad «{texto_cant or "vacía"}» debe ser un número entero.')
            errores += 1
            continue
        if costo is None:
            messages.error(request, f'{nombre}: el costo «{texto_costo or "vacío"}» no es un número (ej.: 12.50 o 12,50).')
            errores += 1
            continue
        if cantidad <= 0 or costo < 0:
            messages.error(request, f'{nombre}: la cantidad debe ser mayor que 0 y el costo no puede ser negativo.')
            errores += 1
            continue
        item.cantidad_pedida, item.costo_unitario_usd = int(cantidad), costo.quantize(Decimal('0.01'))
        item.save(update_fields=['cantidad_pedida', 'costo_unitario_usd'])
    if errores:
        messages.warning(request, f'Se guardó lo demás. Corrige {errores} producto{"s" if errores > 1 else ""} y vuelve a guardar.')
    else:
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
                costo = numero(p.get(f'costo_{i.pk}', str(i.costo_unitario_usd)))
                if cantidad == 0 and costo is None:          # no llegó: el costo no importa
                    costo = i.costo_unitario_usd
                if costo is None or costo < 0:
                    errores[i.pk] = 'Costo vacío o inválido (ej.: 12.50 o 12,50).'
                    continue
                costo = costo.quantize(Decimal('0.01'))
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
                servicios.recibir(orden, recepciones, request.user, almacen=almacenes_inv.elegido(request))
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
                                                    'filas': filas, 'almacenes': almacenes_inv.opciones(request)})


@login_required
@requiere('compras.gestionar')
def pdf(request, pk):
    orden = _orden(pk)
    contenido = orden_compra_pdf(orden, request.empresa, mostrar_costos=request.GET.get('costos', '1') == '1')
    return respuesta_pdf(contenido, orden.numero, nombre_corto(orden.proveedor.nombre), orden.fecha)


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
    from django.utils import timezone
    return respuesta_pdf(contenido, 'Pedido', nombre_corto(request.empresa.perfil.nombre_comercial
                                                           or request.empresa.nombre), timezone.localdate())


@login_required
@requiere('compras.gestionar')
@require_POST
def crear_desde_panel(request):
    """Crea UNA orden (borrador) para el proveedor elegido con los productos marcados."""
    proveedor = get_object_or_404(Proveedor, pk=request.POST.get('proveedor') or 0)
    items = []
    for pid in request.POST.getlist('producto'):
        producto = Producto.objects.filter(pk=pid, activo=True).fisicos().first()
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
