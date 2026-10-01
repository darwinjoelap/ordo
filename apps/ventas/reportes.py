"""
Reportes de ventas: facturación (libro de ventas) y analítica.

Todo se calcula NETO de devoluciones. En la analítica los montos por línea son SIN IVA y después del
descuento del documento (lo que realmente ingresa); el total con IVA se muestra aparte.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.core.permisos import requiere, tiene_permiso
from apps.inventario.models import Categoria, Producto

from .models import ItemDevolucion, ItemPresupuesto, Presupuesto, redondear

E = Presupuesto.Estado
CIEN = Decimal('100')
CERO = Decimal('0')
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _fecha(texto, defecto):
    try:
        return date.fromisoformat(texto) if texto else defecto
    except ValueError:
        return defecto


def rango(get):
    hoy = timezone.localdate()
    desde = _fecha(get.get('desde'), hoy.replace(day=1))
    hasta = _fecha(get.get('hasta'), hoy)
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


def vendedores_de(empresa):
    return (get_user_model().objects.filter(membresias__empresa=empresa, is_superuser=False)
            .distinct().order_by('first_name', 'username'))


def ventas_base(request):
    """Ventas validadas o devueltas que el usuario puede ver."""
    qs = Presupuesto.objects.filter(estado__in=[E.VALIDADA, E.DEVUELTA]).select_related('cliente', 'vendedor')
    if not tiene_permiso(request, 'presupuestos.ver_todos'):
        qs = qs.filter(vendedor=request.user)
    return qs


# ── Facturación ───────────────────────────────────────────────────────────────

def filtrar_facturacion(qs, f):
    campo = 'fecha_facturacion' if f['por'] == 'factura' else 'validado_en__date'
    qs = qs.filter(**{f'{campo}__gte': f['desde'], f'{campo}__lte': f['hasta']})
    if f['factura'] == 'si':
        qs = qs.filter(facturado=True)
    elif f['factura'] == 'no':
        qs = qs.filter(facturado=False)
    if f['pago'] == 'si':
        qs = qs.filter(pagado=True)
    elif f['pago'] == 'no':
        qs = qs.filter(pagado=False)
    if f['vendedor']:
        qs = qs.filter(vendedor_id=f['vendedor'])
    orden = ['fecha_facturacion', 'numero_factura'] if f['por'] == 'factura' else ['validado_en', 'pk']
    return qs.order_by(*orden)


def totales_facturacion(qs):
    neto = F('total_usd') - F('devuelto_usd')
    return qs.aggregate(
        n=Count('pk'), neto=Sum(neto), bs=Sum('total_bs'), devuelto=Sum('devuelto_usd'),
        n_fact=Count('pk', filter=Q(facturado=True)), fact=Sum(neto, filter=Q(facturado=True)),
        n_sin=Count('pk', filter=Q(facturado=False)), sin=Sum(neto, filter=Q(facturado=False)),
        n_pag=Count('pk', filter=Q(pagado=True)), pag=Sum(neto, filter=Q(pagado=True)),
    )


def _excel_facturacion(ventas, f, empresa):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = 'Facturación'
    ws.append([f'{empresa.nombre} · Reporte de facturación {f["desde"]:%d/%m/%Y} al {f["hasta"]:%d/%m/%Y}'])
    ws.append([])
    cab = ['Fecha venta', 'Venta', 'Cliente', 'RIF', 'Vendedor', 'N° factura', 'N° control', 'Fecha factura',
           'Base USD', 'IVA USD', 'Total USD', 'Devuelto USD', 'Neto USD', 'Tasa', 'Total Bs', 'Pagado', 'Método']
    ws.append(cab)
    for c in ws[3]:
        c.font = Font(bold=True)
    for p in ventas:
        ws.append([timezone.localtime(p.validado_en).date() if p.validado_en else p.fecha, p.numero, p.cliente.nombre,
                   p.cliente.rif, p.vendedor.nombre_visible, p.numero_factura, p.numero_control, p.fecha_facturacion,
                   p.base_usd, p.iva_usd, p.total_usd, p.devuelto_usd, p.neto_usd, p.tasa_bs, p.total_bs,
                   'Sí' if p.pagado else 'No', p.get_metodo_pago_display() if p.pagado else ''])
    for col, ancho in zip('ABCDEFGHIJKLMNOPQ', [12, 16, 32, 14, 20, 14, 14, 12, 12, 10, 12, 12, 12, 12, 16, 8, 14]):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=4):
        for celda in fila:
            if isinstance(celda.value, date):
                celda.number_format = 'DD/MM/YYYY'
            elif isinstance(celda.value, Decimal):
                celda.number_format = '#,##0.00'
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@login_required
@requiere('reportes.ver')
def facturacion(request):
    g = request.GET
    desde, hasta = rango(g)
    f = {'desde': desde, 'hasta': hasta, 'por': g.get('por', 'venta'), 'factura': g.get('factura', ''),
         'pago': g.get('pago', ''), 'vendedor': g.get('vendedor', '')}
    ventas = filtrar_facturacion(ventas_base(request), f)
    sufijo = f'{desde:%Y%m%d}-{hasta:%Y%m%d}'
    if g.get('formato') == 'pdf':
        from .pdf import facturacion_pdf
        r = HttpResponse(facturacion_pdf(list(ventas), totales_facturacion(ventas), f, request.empresa),
                         content_type='application/pdf')
        r['Content-Disposition'] = f'inline; filename="facturacion-{sufijo}.pdf"'
        return r
    if g.get('formato') == 'excel':
        r = HttpResponse(_excel_facturacion(ventas, f, request.empresa), content_type=XLSX)
        r['Content-Disposition'] = f'attachment; filename="facturacion-{sufijo}.xlsx"'
        return r
    params = g.copy()
    params.pop('formato', None)
    return render(request, 'ventas/reporte_facturacion.html', {
        'titulo': 'Reporte de facturación', 'ventas': ventas[:500], 'f': f, 't': totales_facturacion(ventas),
        'vendedores': vendedores_de(request.empresa), 'querystring': params.urlencode(),
    })


# ── Analítica ─────────────────────────────────────────────────────────────────

@dataclass
class Resultado:
    vendido: Decimal = CERO          # sin IVA, neto de devoluciones
    costo: Decimal = CERO
    unidades: int = 0
    ventas: set = field(default_factory=set)
    por_mes: dict = field(default_factory=OrderedDict)
    productos: dict = field(default_factory=dict)
    clientes: dict = field(default_factory=dict)
    vendedores: dict = field(default_factory=dict)
    categorias: dict = field(default_factory=dict)

    @property
    def n_ventas(self):
        return len(self.ventas)

    @property
    def ticket(self):
        return redondear(self.vendido / self.n_ventas) if self.n_ventas else CERO

    @property
    def utilidad(self):
        return self.vendido - self.costo

    @property
    def margen(self):
        return (self.utilidad / self.vendido * CIEN).quantize(Decimal('0.1')) if self.vendido else CERO


def _acumular(dic, clave, nombre, monto, unidades=0, venta=None):
    fila = dic.setdefault(clave, {'nombre': nombre, 'monto': CERO, 'unidades': 0, 'ventas': set()})
    fila['monto'] += monto
    fila['unidades'] += unidades
    if venta is not None:
        fila['ventas'].add(venta)


def _ranking(dic, n=10):
    filas = sorted(dic.values(), key=lambda x: -x['monto'])
    total = sum((x['monto'] for x in filas), CERO)
    tope = filas[0]['monto'] if filas and filas[0]['monto'] > 0 else 1
    resto = filas[n:]
    filas = filas[:n]
    if resto:
        filas.append({'nombre': f'Otros ({len(resto)})', 'monto': sum((x['monto'] for x in resto), CERO),
                      'unidades': sum(x['unidades'] for x in resto), 'ventas': set().union(*[x['ventas'] for x in resto]),
                      'otros': True})
    for x in filas:
        x['n_ventas'] = len(x['ventas'])
        x['pct'] = (x['monto'] / total * CIEN).quantize(Decimal('0.1')) if total else CERO
        x['ancho'] = max(0, min(100, float(x['monto'] / tope * 100))) if tope else 0
    return filas


def _serie(dic):
    """Meses en orden cronológico (sin agrupar en "Otros")."""
    filas = [dic[k] for k in sorted(dic)]
    tope = max((x['monto'] for x in filas), default=CERO) or 1
    for x in filas:
        x['n_ventas'] = len(x['ventas'])
        x['ancho'] = max(0, min(100, float(x['monto'] / tope * 100)))
    return filas


def calcular(ventas, categoria_id=None, producto_id=None):
    """Recorre las líneas de las ventas (una consulta) y arma totales y desgloses."""
    items = (ItemPresupuesto.objects.filter(presupuesto__in=ventas)
             .select_related('producto__categoria', 'presupuesto__cliente', 'presupuesto__vendedor'))
    if categoria_id:
        items = items.filter(producto__categoria_id=categoria_id)
    if producto_id:
        items = items.filter(producto_id=producto_id)
    devueltas = dict(ItemDevolucion.objects.filter(item__in=items).values('item_id')
                     .annotate(t=Sum('cantidad')).values_list('item_id', 't'))
    r = Resultado()
    for it in items:
        p = it.presupuesto
        cant = it.cantidad - devueltas.get(it.pk, 0)
        if cant <= 0:
            continue
        monto = redondear(cant * it.precio_usd * (1 - p.descuento_pct / CIEN))
        r.vendido += monto
        r.costo += cant * it.costo_usd
        r.unidades += cant
        r.ventas.add(p.pk)
        mes = timezone.localtime(p.validado_en).date().replace(day=1)
        _acumular(r.por_mes, mes, f'{MESES[mes.month - 1]} {mes.year}', monto, cant, p.pk)
        _acumular(r.productos, it.producto_id, it.producto.nombre, monto, cant, p.pk)
        _acumular(r.clientes, p.cliente_id, p.cliente.nombre, monto, cant, p.pk)
        _acumular(r.vendedores, p.vendedor_id, p.vendedor.nombre_visible, monto, cant, p.pk)
        _acumular(r.categorias, it.producto.categoria_id, it.producto.categoria.nombre, monto, cant, p.pk)
    return r


@login_required
@requiere('presupuestos.crear')
def analitica(request):
    g = request.GET
    desde, hasta = rango(g)
    ve_todo = tiene_permiso(request, 'presupuestos.ver_todos')
    ve_costos = tiene_permiso(request, 'inventario.ver_costos') and ve_todo
    f = {'desde': desde, 'hasta': hasta, 'vendedor': g.get('vendedor', '') if ve_todo else '',
         'cliente': g.get('cliente', ''), 'categoria': g.get('categoria', ''), 'producto': g.get('producto', '')}
    ventas = ventas_base(request).filter(validado_en__date__gte=desde, validado_en__date__lte=hasta)
    if f['vendedor']:
        ventas = ventas.filter(vendedor_id=f['vendedor'])
    if f['cliente']:
        ventas = ventas.filter(cliente_id=f['cliente'])
    r = calcular(ventas, f['categoria'] or None, f['producto'] or None)

    con_iva = None
    if not (f['categoria'] or f['producto']):
        con_iva = ventas.aggregate(t=Sum(F('total_usd') - F('devuelto_usd')))['t'] or CERO

    # Presupuestos por estado (todos los creados en el rango)
    docs = Presupuesto.objects.filter(fecha__gte=desde, fecha__lte=hasta)
    if not ve_todo:
        docs = docs.filter(vendedor=request.user)
    elif f['vendedor']:
        docs = docs.filter(vendedor_id=f['vendedor'])
    if f['cliente']:
        docs = docs.filter(cliente_id=f['cliente'])
    etiquetas = dict(E.choices)
    estados = [{'nombre': etiquetas[x['estado']], 'monto': Decimal(x['n']), 'unidades': x['n'], 'ventas': set(),
                'css': Presupuesto(estado=x['estado']).css_estado}
               for x in docs.values('estado').annotate(n=Count('pk')).order_by('-n')]
    total_docs = sum(x['unidades'] for x in estados)
    for x in estados:
        x['ancho'] = x['unidades'] / estados[0]['unidades'] * 100 if estados else 0
        x['pct'] = round(x['unidades'] / total_docs * 100, 1) if total_docs else 0
    validadas = sum(x['unidades'] for x in estados if x['nombre'] in (etiquetas[E.VALIDADA], etiquetas[E.DEVUELTA]))

    clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    if not ve_todo:
        clientes = clientes.filter(presupuestos__vendedor=request.user).distinct()
    return render(request, 'ventas/analitica.html', {
        'titulo': 'Reportes de ventas', 'f': f, 'r': r, 'con_iva': con_iva, 've_todo': ve_todo, 've_costos': ve_costos,
        'meses': _serie(r.por_mes),
        'top_productos': _ranking(r.productos), 'top_clientes': _ranking(r.clientes),
        'por_vendedor': _ranking(r.vendedores, n=20), 'por_categoria': _ranking(r.categorias),
        'estados': estados, 'total_docs': total_docs,
        'conversion': round(validadas / total_docs * 100, 1) if total_docs else None,
        'vendedores': vendedores_de(request.empresa) if ve_todo else [],
        'clientes': clientes, 'categorias': Categoria.objects.order_by('nombre'),
        'productos': Producto.objects.filter(activo=True).order_by('nombre').only('pk', 'nombre', 'codigo'),
    })


# ── Inventario apartado ───────────────────────────────────────────────────────

@login_required
@requiere('presupuestos.crear')
def apartados(request):
    """Qué está apartado, para quién, por quién y hasta cuándo; y el total por producto."""
    from .models import Reserva
    docs = (Presupuesto.objects.filter(estado=E.APARTADO).select_related('cliente', 'vendedor')
            .order_by('apartado_hasta', 'pk'))
    if not tiene_permiso(request, 'presupuestos.ver_todos'):
        docs = docs.filter(vendedor=request.user)
    docs = list(docs)
    reservas = (Reserva.objects.filter(item__presupuesto__in=docs)
                .select_related('item__producto__unidad', 'lote').order_by('item__producto__nombre', 'lote__fecha_vencimiento'))
    por_doc, por_producto = {}, {}
    for r in reservas:
        por_doc.setdefault(r.item.presupuesto_id, []).append(r)
        prod = r.item.producto
        fila = por_producto.setdefault(prod.pk, {'producto': prod, 'cantidad': 0, 'docs': set()})
        fila['cantidad'] += r.cantidad
        fila['docs'].add(r.item.presupuesto_id)
    for p in docs:
        p.lista_reservas = por_doc.get(p.pk, [])
    productos = sorted(por_producto.values(), key=lambda x: (-x['cantidad'], x['producto'].nombre))
    return render(request, 'ventas/apartados.html', {
        'titulo': 'Inventario apartado', 'docs': docs, 'productos': productos,
        'total_usd': sum((p.total_usd for p in docs), CERO), 'ahora': timezone.now()})
