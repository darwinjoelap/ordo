from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core.permisos import requiere, tiene_permiso
from apps.core.pdf import nombre_corto, respuesta_pdf

from . import almacenes, servicios
from .forms import (AjusteForm, CategoriaForm, IngresoForm, MarcaForm, ProductoForm, SubcategoriaForm,
                    UnidadForm)
from .models import Categoria, Lote, Marca, MovimientoInventario, Producto, Subcategoria, Unidad

POR_PAGINA = 50


# ── Inventario ────────────────────────────────────────────────────────────────

@login_required
@requiere('inventario.ver')
def lista(request):
    g = request.GET
    q = g.get('q', '').strip()
    categoria_id, subcategoria_id, marca_id, alerta = (g.get(k, '') for k in ('categoria', 'subcategoria',
                                                                               'marca', 'alerta'))
    # El formulario siempre envía "q": si llega sin "activos", la casilla se desmarcó
    solo_activos = g.get('activos', '0' if 'q' in g else '1') == '1'

    almacen_txt = g.get('almacen', '') if almacenes.activo(request) else ''
    from .models import Almacen
    almacen_sel = 'SIN' if almacen_txt == 'SIN' else (Almacen.objects.filter(pk=almacen_txt).first() if almacen_txt.isdigit() else None)
    productos = Producto.objects.select_related('categoria', 'subcategoria', 'marca', 'unidad').con_stock(almacen_sel)
    ver_servicios = request.empresa.perfil.maneja_servicios and g.get('tipo') == Producto.Tipo.SERVICIO
    productos = productos.servicios() if ver_servicios else productos.fisicos()
    if solo_activos:
        productos = productos.filter(activo=True)
    productos = productos.buscar(q)
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
    if subcategoria_id:
        productos = productos.filter(subcategoria_id=subcategoria_id)
    if marca_id:
        productos = productos.filter(marca_id=marca_id)
    if alerta == 'stock_minimo':
        productos = productos.filter(anot_stock_disponible__lte=F('stock_minimo'))
    elif alerta == 'vencidos':
        productos = productos.filter(anot_tiene_vencidos=True)
    elif alerta == 'agotados':
        productos = productos.filter(anot_stock_disponible__lte=0)
    productos = productos.order_by(Lower('nombre'), 'pk')

    lotes_total = Lote.objects.filter(producto__in=productos.values('pk'))
    if almacen_sel == 'SIN':
        lotes_total = lotes_total.filter(almacen__isnull=True)
    elif almacen_sel is not None:
        lotes_total = lotes_total.filter(almacen=almacen_sel)
    total_unidades = lotes_total.aggregate(
        t=Sum('cantidad_actual'))['t'] or 0
    pagina = Paginator(productos, POR_PAGINA).get_page(g.get('page'))
    params = g.copy()
    params.pop('page', None)

    return render(request, 'inventario/lista.html', {
        'titulo': 'Inventario',
        'pagina': pagina,
        'querystring': params.urlencode(),
        'categorias': Categoria.objects.all(),
        'subcategorias': Subcategoria.objects.select_related('categoria'),
        'marcas': Marca.objects.filter(activa=True),
        'f': {'q': q, 'categoria': categoria_id, 'subcategoria': subcategoria_id, 'marca': marca_id,
              'alerta': alerta, 'activos': solo_activos, 'almacen': almacen_txt,
              'tipo': Producto.Tipo.SERVICIO if ver_servicios else ''},
        'ver_servicios': ver_servicios,
        'almacenes': almacenes.opciones(request), 'almacen_sel': almacen_sel,
        'total_unidades': total_unidades,
        'ver_costos': tiene_permiso(request, 'inventario.ver_costos'),
    })


def _por_almacen(producto):
    from django.db.models import Sum as S
    filas = (Lote.objects.filter(producto=producto, cantidad_actual__gt=0).values('almacen__nombre')
             .annotate(total=S('cantidad_actual'), apartado=S('cantidad_apartada')).order_by('almacen__nombre'))
    return [{'nombre': f['almacen__nombre'] or 'Sin almacén', 'total': f['total'],
             'disponible': f['total'] - f['apartado']} for f in filas]


@login_required
@requiere('inventario.ver')
def detalle(request, pk):
    producto = get_object_or_404(
        Producto.objects.select_related('categoria', 'subcategoria', 'marca', 'unidad', 'proveedor_habitual')
        .prefetch_related('lotes__proveedor', 'lotes__almacen'), pk=pk)
    movimientos = (MovimientoInventario.objects.filter(lote__producto=producto)
                   .select_related('lote__almacen', 'usuario')[:50])
    return render(request, 'inventario/detalle.html', {
        'titulo': producto.nombre,
        'producto': producto,
        'lotes': [l for l in producto.lotes.all() if l.cantidad_actual > 0],
        'por_almacen': _por_almacen(producto) if almacenes.activo(request) else None,
        'movimientos': movimientos,
        'ver_costos': tiene_permiso(request, 'inventario.ver_costos'),
        'puede_gestionar': tiene_permiso(request, 'inventario.gestionar'),
    })


@login_required
@requiere('inventario.gestionar')
def producto_form(request, pk=None):
    producto = get_object_or_404(Producto, pk=pk) if pk else None
    if request.method == 'POST':
        form = ProductoForm(request.POST, instance=producto, maneja_servicios=request.empresa.perfil.maneja_servicios)
        if form.is_valid():
            producto = form.save()
            messages.success(request, f'{"Servicio" if producto.es_servicio else "Producto"} "{producto.nombre}" guardado.')
            return redirect('inventario:detalle', pk=producto.pk)
    else:
        inicial = {'unidad': Unidad.objects.filter(abreviatura='UN').first()} if not producto else None
        if not producto and request.GET.get('tipo') == Producto.Tipo.SERVICIO:
            inicial['tipo'] = Producto.Tipo.SERVICIO
        form = ProductoForm(instance=producto, initial=inicial, maneja_servicios=request.empresa.perfil.maneja_servicios)
    return render(request, 'inventario/producto_form.html', {
        'titulo': f'Editar {producto.nombre}' if producto else
                  ('Nuevo servicio' if request.GET.get('tipo') == Producto.Tipo.SERVICIO else 'Nuevo producto'),
        'form': form, 'producto': producto,
        'hay_categorias': Categoria.objects.exists(),
    })


@login_required
@requiere('inventario.gestionar')
def subcategorias_opciones(request):
    """HTMX: <option> de subcategorías para la categoría elegida."""
    subs = Subcategoria.objects.filter(categoria_id=request.GET.get('categoria') or 0)
    return render(request, 'inventario/partials/opciones.html', {'opciones': subs, 'vacio': '— Sin subcategoría —'})


# ── Buscador de productos (HTMX) ──────────────────────────────────────────────

@login_required
@requiere('inventario.ver')
def buscar_productos(request):
    q = request.GET.get('q', '').strip()
    destino = request.GET.get('destino', 'ingreso')
    productos = []
    if len(q) >= 2:
        productos = (Producto.objects.filter(activo=True).fisicos().buscar(q).select_related('unidad')
                     .con_stock().order_by('nombre')[:12])
    return render(request, 'inventario/partials/resultados_busqueda.html', {
        'productos': productos, 'q': q, 'destino': destino, 'orden_id': request.GET.get('orden', '')})


# ── Ingreso y ajuste ──────────────────────────────────────────────────────────

@login_required
@requiere('inventario.gestionar')
def ingreso(request):
    lote_existente = None
    producto = None
    if request.method == 'POST':
        form = IngresoForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            producto = d['producto']
            try:
                lote = servicios.ingresar(
                    producto, d['cantidad'], d['costo_unitario'], request.user,
                    numero_lote=d['numero_lote'], fecha_vencimiento=d['fecha_vencimiento'],
                    proveedor=d['proveedor'], notas=d['notas'],
                    sumar_a_existente=request.POST.get('confirmar_suma') == '1', almacen=almacenes.elegido(request))
            except servicios.LoteExistente as e:
                lote_existente = e.lote
            except servicios.ErrorInventario as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, f'Ingreso registrado: {d["cantidad"]} × {producto.nombre}'
                                          f'{" · lote " + lote.numero_lote if lote.numero_lote else ""}.')
                if request.POST.get('otro') == '1':
                    return redirect('inventario:ingreso')
                return redirect('inventario:detalle', pk=producto.pk)
        producto = form.cleaned_data.get('producto') if hasattr(form, 'cleaned_data') else None
    else:
        inicial = {}
        if request.GET.get('producto'):
            producto = get_object_or_404(Producto, pk=request.GET['producto'])
            inicial = {'producto': producto, 'costo_unitario': producto.precio_costo_usd,
                       'proveedor': producto.proveedor_habitual}
        form = IngresoForm(initial=inicial)
    return render(request, 'inventario/ingreso.html', {
        'titulo': 'Ingreso de mercancía', 'form': form, 'producto': producto, 'lote_existente': lote_existente,
        'almacenes': almacenes.opciones(request), 'almacen_post': request.POST.get('almacen', ''),
    })


@login_required
@requiere('inventario.gestionar')
def ajuste(request):
    producto = None
    if request.method == 'POST':
        form = AjusteForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            producto = d['producto']
            if d['lote'].producto_id != producto.pk:
                raise Http404
            try:
                servicios.ajustar(d['lote'], d['tipo'], d['cantidad'], request.user, d['motivo'])
            except servicios.ErrorInventario as e:
                form.add_error('cantidad', str(e))
            else:
                messages.success(request, 'Ajuste registrado.')
                return redirect('inventario:detalle', pk=producto.pk)
        producto = producto or Producto.objects.filter(pk=request.POST.get('producto') or 0).first()
    else:
        if request.GET.get('producto'):
            producto = get_object_or_404(Producto, pk=request.GET['producto'])
        form = AjusteForm(initial={'producto': producto, 'lote': request.GET.get('lote')})
    return render(request, 'inventario/ajuste.html', {'titulo': 'Ajuste de inventario', 'form': form,
                                                      'producto': producto})


# ── Catálogo: categorías, subcategorías, marcas, unidades ─────────────────────

CATALOGO = {
    'categorias': (Categoria, CategoriaForm, 'Categorías', ['nombre', 'descripcion']),
    'subcategorias': (Subcategoria, SubcategoriaForm, 'Subcategorías', ['categoria', 'nombre']),
    'marcas': (Marca, MarcaForm, 'Marcas', ['nombre', 'activa']),
    'unidades': (Unidad, UnidadForm, 'Unidades de medida', ['nombre', 'abreviatura']),
}


@login_required
@requiere('inventario.gestionar')
def catalogo(request, tipo='categorias'):
    if tipo not in CATALOGO:
        raise Http404
    modelo, Form, titulo, columnas = CATALOGO[tipo]
    editando = get_object_or_404(modelo, pk=request.GET['editar']) if request.GET.get('editar') else None
    if request.method == 'POST':
        form = Form(request.POST, instance=editando)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f'"{obj}" guardado.')
            return redirect(reverse('inventario:catalogo', args=[tipo]))
    else:
        form = Form(instance=editando)
    objetos = modelo.objects.all()
    if tipo == 'subcategorias':
        objetos = objetos.select_related('categoria')
    filas = [(o, [getattr(o, c) for c in columnas]) for o in objetos]
    return render(request, 'inventario/catalogo.html', {
        'titulo': titulo, 'tipo': tipo, 'tipos': {k: v[2] for k, v in CATALOGO.items()},
        'form': form, 'editando': editando,
        'encabezados': [modelo._meta.get_field(c).verbose_name for c in columnas], 'filas': filas,
    })


# ── Lista de precios (PDF) ────────────────────────────────────────────────────

@login_required
@requiere('inventario.ver')
def lista_precios(request):
    from django.http import HttpResponse

    from apps.tasas.servicios import tasa_vigente

    from .pdf import lista_precios_pdf
    if request.GET.get('generar'):
        productos = (Producto.objects.filter(activo=True).con_stock()
                     .select_related('categoria', 'marca', 'unidad').order_by(Lower('categoria__nombre'), Lower('nombre')))
        if request.GET.get('categoria'):
            productos = productos.filter(categoria_id=request.GET['categoria'])
        if request.GET.get('con_existencia'):      # los servicios siempre están disponibles
            productos = productos.filter(Q(anot_stock_disponible__gt=0) | Q(tipo=Producto.Tipo.SERVICIO))
        if not request.empresa.perfil.maneja_servicios:
            productos = productos.fisicos()
        contenido = lista_precios_pdf(productos, request.empresa,
                                      mostrar_existencia=bool(request.GET.get('mostrar_existencia')),
                                      tasa=tasa_vigente(request.empresa) if request.GET.get('en_bs') else None)
        from django.utils import timezone
        return respuesta_pdf(contenido, 'Lista-de-precios', nombre_corto(request.empresa.perfil.nombre_comercial
                                                                         or request.empresa.nombre),
                             timezone.localdate())
    return render(request, 'inventario/lista_precios.html', {'titulo': 'Lista de precios',
                                                             'categorias': Categoria.objects.all()})
