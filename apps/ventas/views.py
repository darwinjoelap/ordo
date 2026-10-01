from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.clientes.permisos import clientes_visibles
from apps.core.permisos import requiere, tiene_permiso
from apps.inventario.models import Producto

from . import servicios
from .models import ItemPresupuesto, Presupuesto, Reserva
from .pdf import presupuesto_pdf

E = Presupuesto.Estado


def _fecha_o_none(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def visibles(request):
    qs = Presupuesto.objects.select_related('cliente', 'vendedor')
    if not tiene_permiso(request, 'presupuestos.ver_todos'):
        qs = qs.filter(vendedor=request.user)
    return qs


def _presupuesto(request, pk):
    return get_object_or_404(visibles(request), pk=pk)


@login_required
@requiere('presupuestos.crear')
def lista(request):
    g = request.GET
    estado, q, vendedor = g.get('estado', ''), g.get('q', '').strip(), g.get('vendedor', '')
    desde, hasta = _fecha_o_none(g.get('desde')), _fecha_o_none(g.get('hasta'))
    qs = visibles(request)
    # Ventas: por fecha de validación; el resto, por fecha del documento
    campo_fecha = 'validado_en__date' if estado == 'ventas' else 'fecha'
    if desde:
        qs = qs.filter(**{f'{campo_fecha}__gte': desde})
    if hasta:
        qs = qs.filter(**{f'{campo_fecha}__lte': hasta})
    if estado == 'ventas':
        qs = qs.filter(estado=E.VALIDADA)
    elif estado == 'abiertos':
        qs = qs.filter(estado__in=[E.BORRADOR, E.EMITIDO, E.APARTADO, E.POR_VALIDAR])
    elif estado:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(cliente__nombre__icontains=q) | Q(cliente__rif__icontains=q))
    if vendedor and tiene_permiso(request, 'presupuestos.ver_todos'):
        qs = qs.filter(vendedor_id=vendedor)
    totales = qs.aggregate(n=Count('pk'), usd=Sum('total_usd'), devuelto=Sum('devuelto_usd'))
    totales['neto'] = (totales['usd'] or 0) - (totales['devuelto'] or 0)
    pagina = Paginator(qs.order_by('-creado_en', '-pk'), 30).get_page(g.get('page'))
    params = g.copy()
    params.pop('page', None)
    from django.contrib.auth import get_user_model
    vendedores = get_user_model().objects.filter(membresias__empresa=request.empresa, is_superuser=False).distinct() \
        if tiene_permiso(request, 'presupuestos.ver_todos') else []
    return render(request, 'ventas/lista.html', {
        'titulo': 'Presupuestos y ventas', 'pagina': pagina, 'querystring': params.urlencode(),
        'f': {'estado': estado, 'q': q, 'vendedor': vendedor, 'desde': desde, 'hasta': hasta}, 'estados': E.choices, 'totales': totales,
        'vendedores': vendedores,
    })


@login_required
@requiere('presupuestos.crear')
def nuevo(request):
    """Paso 1: elegir cliente (buscador) → crea el borrador."""
    if request.method == 'POST' or request.GET.get('cliente'):
        cliente = get_object_or_404(clientes_visibles(request).filter(activo=True),
                                    pk=request.POST.get('cliente') or request.GET.get('cliente'))
        if request.method == 'POST':
            p = servicios.crear(cliente, request.user, request.empresa)
            return redirect('ventas:detalle', pk=p.pk)
        return render(request, 'ventas/nuevo.html', {'titulo': 'Nuevo presupuesto', 'cliente': cliente})
    return render(request, 'ventas/nuevo.html', {'titulo': 'Nuevo presupuesto'})


@login_required
@requiere('presupuestos.crear')
def buscar_clientes(request):
    q = request.GET.get('q', '').strip()
    clientes = []
    if len(q) >= 2:
        clientes = clientes_visibles(request).filter(activo=True).filter(
            Q(nombre__icontains=q) | Q(rif__icontains=q))[:10]
    return render(request, 'ventas/partials/clientes.html', {'clientes': clientes, 'q': q})


@login_required
@requiere('presupuestos.crear')
def buscar_productos(request, pk):
    p = _presupuesto(request, pk)
    q = request.GET.get('q', '').strip()
    productos = []
    if len(q) >= 2:
        productos = (Producto.objects.filter(activo=True).buscar(q).con_stock().select_related('unidad')
                     .order_by('nombre')[:12])
    perfil = request.empresa.perfil
    filas = [(pr, *servicios.rango_precio(perfil, pr)) for pr in productos]
    return render(request, 'ventas/partials/productos.html', {
        'p': p, 'filas': filas, 'q': q, 'puede_fijar': tiene_permiso(request, 'precios.fijar'),
        'modo': perfil.modo_precio})


@login_required
@requiere('presupuestos.crear')
def detalle(request, pk):
    p = _presupuesto(request, pk)
    items = list(ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto__unidad'))
    reservas = {}
    for r in Reserva.objects.filter(item__presupuesto=p).select_related('lote'):
        reservas.setdefault(r.item_id, []).append(r)
    for i in items:
        i.lista_reservas = reservas.get(i.pk, [])
    perfil = request.empresa.perfil
    comision = None
    if p.es_venta and (tiene_permiso(request, 'comisiones.liquidar') or p.vendedor_id == request.user.pk):
        from apps.comisiones.models import AjusteComision, Comision
        comision = Comision.objects.filter(presupuesto=p).select_related('liquidacion').first()
        if comision:
            comision.lista_ajustes = list(AjusteComision.objects.filter(comision=comision).select_related('devolucion'))
            comision.neto = comision.monto_usd + sum(a.monto_usd for a in comision.lista_ajustes)
    from .models import Devolucion
    return render(request, 'ventas/detalle.html', {
        'comision': comision,
        'devoluciones': Devolucion.objects.filter(presupuesto=p).order_by('creada_en') if p.es_venta else [],
        'puede_devolver': tiene_permiso(request, 'ventas.devolver'),
        'puede_facturar': tiene_permiso(request, 'ventas.facturar'),
        'titulo': p.numero, 'p': p, 'items': items, 'perfil': perfil,
        'puede_fijar': tiene_permiso(request, 'precios.fijar'),
        'puede_validar': tiene_permiso(request, 'ventas.validar'),
        'precio_editable': perfil.modo_precio != 'FIJO' or tiene_permiso(request, 'precios.fijar'),
        'metodos': Presupuesto.MetodoPago.choices,
    })


@login_required
@requiere('presupuestos.crear')
@require_POST
def agregar_item(request, pk):
    p = _presupuesto(request, pk)
    try:
        producto = get_object_or_404(Producto.objects.filter(activo=True), pk=request.POST.get('producto'))
        cantidad = int(request.POST.get('cantidad') or 1)
        precio = request.POST.get('precio', '').replace(',', '.') or None
        precio = Decimal(precio) if precio is not None else None
        item = servicios.agregar_item(p, producto, cantidad, precio, request.empresa.perfil,
                                      tiene_permiso(request, 'precios.fijar'))
        if item.fuera_de_rango:
            messages.warning(request, f'{producto.nombre}: precio fuera del rango permitido. La venta quedará marcada para revisión.')
        else:
            messages.success(request, f'Agregado: {producto.nombre}.')
    except (ValueError, InvalidOperation):
        messages.error(request, 'Cantidad o precio inválidos.')
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    return redirect('ventas:detalle', pk=pk)


@login_required
@requiere('presupuestos.crear')
@require_POST
def actualizar(request, pk):
    p = _presupuesto(request, pk)
    cambios, quitar = {}, []
    try:
        for item in ItemPresupuesto.objects.filter(presupuesto=p):
            if request.POST.get(f'quitar_{item.pk}'):
                quitar.append(item.pk)
                continue
            cantidad = int(request.POST.get(f'cantidad_{item.pk}', item.cantidad))
            precio_txt = request.POST.get(f'precio_{item.pk}')
            precio = Decimal(precio_txt.replace(',', '.')) if precio_txt else item.precio_usd
            cambios[item.pk] = (cantidad, precio)
        descuento = request.POST.get('descuento_pct')
        descuento = Decimal(descuento.replace(',', '.')) if descuento else None
        if descuento and not tiene_permiso(request, 'precios.fijar') and request.empresa.perfil.modo_precio == 'FIJO':
            descuento = None
        servicios.actualizar_items(p, cambios, quitar, request.empresa.perfil, tiene_permiso(request, 'precios.fijar'),
                                   descuento)
        p.notas = request.POST.get('notas', p.notas)
        p.condiciones = request.POST.get('condiciones', p.condiciones)
        p.save(update_fields=['notas', 'condiciones'])
        messages.success(request, 'Presupuesto actualizado.')
    except (ValueError, InvalidOperation):
        messages.error(request, 'Hay cantidades o precios inválidos.')
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    return redirect('ventas:detalle', pk=pk)


ACCIONES = {
    'emitir': ('presupuestos.crear', lambda r, p: servicios.emitir(p), 'Presupuesto emitido.'),
    'apartar': ('presupuestos.crear', lambda r, p: servicios.apartar(p, r.user, r.empresa), 'Stock apartado.'),
    'desapartar': ('presupuestos.crear', lambda r, p: servicios.desapartar(p, r.user), 'Stock liberado.'),
    'confirmar': ('presupuestos.crear', lambda r, p: servicios.confirmar(p, r.user, r.empresa), None),
    'cancelar': ('presupuestos.crear', lambda r, p: servicios.cancelar(p, r.user), 'Presupuesto cancelado.'),
    'validar': ('ventas.validar', lambda r, p: servicios.validar(p, r.user), 'Venta validada.'),
    'rechazar': ('ventas.validar', lambda r, p: servicios.rechazar(
        p, r.user, r.POST.get('motivo', ''), r.POST.get('liberar') != '1', r.empresa), 'Venta rechazada.'),
}


@login_required
@requiere('presupuestos.crear')
@require_POST
def accion(request, pk, nombre):
    p = _presupuesto(request, pk)
    if nombre not in ACCIONES:
        return redirect('ventas:detalle', pk=pk)
    permiso, funcion, mensaje = ACCIONES[nombre]
    if not tiene_permiso(request, permiso):
        messages.error(request, 'Tu rol no permite esta acción.')
        return redirect('ventas:detalle', pk=pk)
    try:
        p = funcion(request, p)
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    else:
        if nombre == 'confirmar':
            mensaje = ('Venta confirmada y validada.' if p.estado == E.VALIDADA
                       else 'Venta confirmada. Queda pendiente de validación.')
        messages.success(request, mensaje)
    destino = request.POST.get('volver')
    return redirect(destino if destino == '/ventas/por-validar/' else f'/ventas/{pk}/')


@login_required
@requiere('presupuestos.crear')
@require_POST
def pago_entrega(request, pk):
    p = _presupuesto(request, pk)
    try:
        if 'pagado' in request.POST:
            fecha = request.POST.get('fecha_pago') or None
            servicios.registrar_pago(p, request.POST.get('pagado') == '1', request.POST.get('metodo_pago', ''),
                                     date.fromisoformat(fecha) if fecha else None)
        if 'entregado' in request.POST:
            servicios.registrar_entrega(p, request.POST.get('entregado') == '1')
        messages.success(request, 'Actualizado.')
    except (servicios.ErrorVenta, ValueError) as e:
        messages.error(request, str(e))
    return redirect('ventas:detalle', pk=pk)


@login_required
@requiere('ventas.validar')
def por_validar(request):
    ventas = (Presupuesto.objects.filter(estado=E.POR_VALIDAR).select_related('cliente', 'vendedor')
              .order_by('confirmado_en'))
    return render(request, 'ventas/por_validar.html', {'titulo': 'Ventas por validar', 'ventas': ventas})


@login_required
@requiere('presupuestos.crear')
def pdf(request, pk):
    p = _presupuesto(request, pk)
    contenido = presupuesto_pdf(p, request.empresa, moneda=request.GET.get('moneda', 'ambas'))
    r = HttpResponse(contenido, content_type='application/pdf')
    r['Content-Disposition'] = f'inline; filename="{p.numero}.pdf"'
    return r


@login_required
@requiere('ventas.facturar')
@require_POST
def facturacion(request, pk):
    p = _presupuesto(request, pk)
    try:
        fecha = request.POST.get('fecha_facturacion') or None
        servicios.registrar_facturacion(p, request.POST.get('facturado') == '1', request.POST.get('numero_factura', ''),
                                        request.POST.get('numero_control', ''),
                                        date.fromisoformat(fecha) if fecha else None)
        messages.success(request, 'Datos de facturación guardados.')
    except ValueError:
        messages.error(request, 'Fecha inválida.')
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    return redirect('ventas:detalle', pk=pk)
