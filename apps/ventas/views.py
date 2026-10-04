from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.clientes.permisos import clientes_visibles
from apps.core.permisos import requiere, tiene_permiso
from apps.inventario.models import Producto
from apps.core.pdf import nombre_corto, respuesta_pdf

from . import servicios
from .models import ItemPresupuesto, Presupuesto, Reserva, desglose_bs
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


# Sugerencias para «Banco emisor» (el campo acepta cualquier texto)
BANCOS = ['Banco de Venezuela', 'Banesco', 'Mercantil', 'Provincial (BBVA)', 'BNC', 'Bancamiga', 'Banplus', 'Bancaribe',
          'Banco Exterior', 'Banco del Tesoro', 'Bicentenario', 'BFC Fondo Común', 'Venezolano de Crédito', 'Banco Plaza',
          'Banco Activo', 'Sofitasa', '100% Banco', 'Bancrecer', 'Mi Banco', 'Banco Caroní', 'Del Sur', 'Banfanb',
          'Zelle', 'Binance', 'Otro']


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
        qs = qs.filter(estado__in=[E.BORRADOR, E.EMITIDO, E.APARTADO, E.POR_PAGAR, E.POR_VALIDAR])
    elif estado == 'por_cobrar':        # confirmadas sin pago + ventas validadas sin pago
        qs = qs.filter(Q(estado=E.POR_PAGAR) | Q(estado=E.VALIDADA, pagado=False))
    elif estado == 'por_entregar':      # toda venta confirmada (cobrada o no) que aún no se entrega
        qs = qs.filter(estado__in=Presupuesto.CONFIRMADAS, entregado=False)
    elif estado:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(cliente__nombre__icontains=q) | Q(cliente__rif__icontains=q))
    pendiente = g.get('pendiente', '')
    if pendiente == 'pago':
        qs = qs.filter(Q(estado=E.POR_PAGAR) | Q(estado=E.VALIDADA, pagado=False))
    elif pendiente == 'entrega':
        qs = qs.filter(estado__in=Presupuesto.CONFIRMADAS, entregado=False)
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
        'f': {'estado': estado, 'q': q, 'vendedor': vendedor, 'desde': desde, 'hasta': hasta, 'pendiente': pendiente}, 'estados': E.choices, 'totales': totales,
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
            # Siempre uno NUEVO y en blanco: a un cliente se le hacen varios presupuestos y nunca se abre uno
            # anterior por defecto. Los que tiene abiertos se listan abajo para elegir uno a propósito.
            p = servicios.crear(cliente, request.user, request.empresa)
            return redirect('ventas:detalle', pk=p.pk)
        abiertos = (visibles(request).filter(cliente=cliente, estado__in=[E.BORRADOR, E.EMITIDO])
                    .annotate(n_items=Count('items')).order_by('-creado_en', '-pk')[:30])
        return render(request, 'ventas/nuevo.html', {'titulo': 'Nuevo presupuesto', 'cliente': cliente,
                                                     'abiertos': abiertos})
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


def _tasa_referencial(request, p):
    """
    Un borrador aún no tiene tasa (se congela al emitir). Para mostrar montos en Bs se le pone EN MEMORIA
    (no se guarda) la tasa vigente. Devuelve True si la tasa que queda en `p` es referencial.
    """
    if p.tasa_bs:
        return False
    from apps.tasas.servicios import tasa_vigente
    tasa = tasa_vigente(request.empresa)
    if not tasa:
        return False
    p.tasa_bs = tasa.bs_por_usd
    return True


@login_required
@requiere('presupuestos.crear')
def detalle(request, pk):
    p = _presupuesto(request, pk)
    items = list(ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto__unidad')
                 .order_by(Lower('producto__nombre'), 'pk'))
    tasa_referencial = _tasa_referencial(request, p)
    montos_bs = desglose_bs(p, items)
    stock = {}
    if p.editable:      # aviso «Sin stock» mientras se arma el presupuesto (apartado ya tiene su reserva)
        stock = {pr.pk: pr.stock_disponible for pr in
                 Producto.objects.filter(pk__in=[i.producto_id for i in items]).con_stock()}
    for i in items:
        i.subtotal_bs = montos_bs['lineas'][i.pk] if montos_bs else None
        i.disponible = stock.get(i.producto_id)
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
        'titulo': p.numero_visible, 'p': p, 'items': items, 'perfil': perfil,
        'montos_bs': montos_bs, 'total_unidades': sum(i.cantidad for i in items), 'tasa_referencial': tasa_referencial,
        'puede_fijar': tiene_permiso(request, 'precios.fijar'),
        'puede_validar': tiene_permiso(request, 'ventas.validar'),
        'precio_editable': perfil.modo_precio != 'FIJO' or tiene_permiso(request, 'precios.fijar'),
        'metodos': Presupuesto.MetodoPago.choices, 'bancos': BANCOS,
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
        disponible = Producto.objects.filter(pk=producto.pk).con_stock().first().stock_disponible
        if disponible < item.cantidad:
            messages.warning(request, f'{producto.nombre}: sin stock suficiente (disponible: {max(disponible, 0)}).')
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
        perfil = request.empresa.perfil
        puede_iva = perfil.modo_precio != 'FIJO' or tiene_permiso(request, 'precios.fijar')
        sin_iva = (request.POST.get('sin_iva') == '1') if puede_iva and 'iva_enviado' in request.POST else None
        servicios.actualizar_items(p, cambios, quitar, perfil, tiene_permiso(request, 'precios.fijar'),
                                   descuento, sin_iva=sin_iva)
        p.notas = request.POST.get('notas', p.notas)
        p.condiciones = request.POST.get('condiciones', p.condiciones)
        p.save(update_fields=['notas', 'condiciones'])
        if 'guardar' in request.POST:           # botón «Guardar»: aquí recibe su número (exige productos)
            sin_numero = not p.numero
            p = servicios.guardar(p)
            messages.success(request, f'Presupuesto guardado con el número {p.numero}.' if sin_numero
                             else 'Presupuesto actualizado.')
        else:
            messages.success(request, 'Presupuesto actualizado.')
    except (ValueError, InvalidOperation):
        messages.error(request, 'Hay cantidades o precios inválidos.')
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    return redirect('ventas:detalle', pk=pk)


ACCIONES = {
    'emitir': ('presupuestos.crear', lambda r, p: servicios.emitir(p), 'Presupuesto emitido.'),
    'actualizar_tasa': ('presupuestos.crear', lambda r, p: servicios.actualizar_tasa(p),
                        'Tasa actualizada a la de hoy. Los montos en Bs se recalcularon.'),
    'apartar': ('presupuestos.crear', lambda r, p: servicios.apartar(p, r.user, r.empresa), 'Stock apartado.'),
    'desapartar': ('presupuestos.crear', lambda r, p: servicios.desapartar(p, r.user), 'Stock liberado.'),
    'confirmar': ('presupuestos.crear', lambda r, p: servicios.confirmar(p, r.user, r.empresa), None),
    'desconfirmar': ('presupuestos.crear', lambda r, p: servicios.desconfirmar(p, r.user, r.empresa),
                     'La venta volvió a apartado.'),
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
            mensaje = {E.VALIDADA: 'Venta confirmada y validada.',
                       E.POR_PAGAR: 'Venta confirmada. Queda por cobrar y por entregar: al registrar el pago pasa a validación.',
                       }.get(p.estado, 'Venta confirmada. Queda pendiente de validación.')
        messages.success(request, mensaje)
    destino = request.POST.get('volver')
    return redirect(destino if destino == '/ventas/por-validar/' else f'/ventas/{pk}/')


@login_required
@requiere('presupuestos.crear')
@require_POST
def eliminar(request, pk):
    """Borra por completo un borrador. No deja documento cancelado ni hueco en la numeración si era el último."""
    p = _presupuesto(request, pk)
    try:
        numero, libre = servicios.eliminar(p)
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
        return redirect('ventas:detalle', pk=pk)
    if not numero:
        messages.success(request, 'Borrador eliminado.')
    elif libre:
        messages.success(request, f'Borrador {numero} eliminado. Su número se usará en el próximo presupuesto.')
    else:
        messages.warning(request, f'Borrador {numero} eliminado. Ya había presupuestos posteriores: ese número '
                                  f'queda sin usar.')
    return redirect('ventas:lista')


@login_required
@requiere('presupuestos.crear')
@require_POST
def pago_entrega(request, pk):
    p = _presupuesto(request, pk)
    try:
        if 'pagado' in request.POST:
            fecha = request.POST.get('fecha_pago') or None
            monto = request.POST.get('monto_pago', '').strip().replace(',', '.')
            servicios.registrar_pago(p, request.POST.get('pagado') == '1', request.POST.get('metodo_pago', ''),
                                     date.fromisoformat(fecha) if fecha else None,
                                     banco=request.POST.get('banco_pago', ''),
                                     referencia=request.POST.get('referencia_pago', ''),
                                     monto=Decimal(monto) if monto else None,
                                     moneda=request.POST.get('moneda_pago', ''), usuario=request.user)
        if 'entregado' in request.POST:
            servicios.registrar_entrega(p, request.POST.get('entregado') == '1')
        messages.success(request, 'Actualizado.')
    except servicios.ErrorVenta as e:
        messages.error(request, str(e))
    except (ValueError, InvalidOperation):
        messages.error(request, 'Revisa la fecha y el monto del pago.')
    return redirect('ventas:detalle', pk=pk)


@login_required
@requiere('ventas.validar')
def por_validar(request):
    ventas = (Presupuesto.objects.filter(estado=E.POR_VALIDAR).select_related('cliente', 'vendedor', 'pago_registrado_por')
              .order_by('confirmado_en'))
    return render(request, 'ventas/por_validar.html', {'titulo': 'Ventas por validar', 'ventas': ventas})


@login_required
@requiere('presupuestos.crear')
def pdf(request, pk):
    p = _presupuesto(request, pk)
    referencial = _tasa_referencial(request, p)
    contenido = presupuesto_pdf(p, request.empresa, moneda=request.GET.get('moneda', 'ambas'),
                                tasa_referencial=referencial)
    return respuesta_pdf(contenido, p.numero or 'Borrador', nombre_corto(p.cliente.nombre), p.fecha)


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
