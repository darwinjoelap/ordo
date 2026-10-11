from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.pdf import nombre_archivo, respuesta_pdf
from apps.core.permisos import requiere, tiene_permiso

from . import cobranza
from .models import Presupuesto
from .views import _fecha_o_none, visibles


def _filtros(request):
    g = request.GET
    hoy = timezone.localdate()
    desde = _fecha_o_none(g.get('desde')) or hoy.replace(day=1)
    hasta = _fecha_o_none(g.get('hasta')) or hoy
    docs = visibles(request)
    vendedor = g.get('vendedor', '') if tiene_permiso(request, 'presupuestos.ver_todos') else ''
    if vendedor:
        docs = docs.filter(vendedor_id=vendedor)
    metodo = g.get('metodo', '') if g.get('metodo', '') in Presupuesto.MetodoPago.values else ''
    abonos = cobranza.abonos_de(docs)
    if metodo:
        abonos = abonos.filter(metodo=metodo)
    filas = list(cobranza.detalle(abonos, desde, hasta))
    return {'desde': desde, 'hasta': hasta, 'vendedor': vendedor, 'metodo': metodo}, filas, \
        cobranza.resumen(abonos, desde, hasta)


@login_required
@requiere('presupuestos.crear')
def reporte(request):
    f, filas, tot = _filtros(request)
    from django.contrib.auth import get_user_model
    vendedores = get_user_model().objects.filter(membresias__empresa=request.empresa, is_superuser=False).distinct() \
        if tiene_permiso(request, 'presupuestos.ver_todos') else []
    return render(request, 'ventas/cobranza.html', {
        'titulo': 'Cobranza', 'f': f, 'filas': filas, 'tot': tot, 'vendedores': vendedores,
        'metodos': [m for m in Presupuesto.MetodoPago.choices if m[0] != 'MIXTO'],
        've_todo': tiene_permiso(request, 'presupuestos.ver_todos'), 'querystring': request.GET.urlencode(),
    })


@login_required
@requiere('presupuestos.crear')
def reporte_pdf(request):
    f, filas, tot = _filtros(request)
    filtro = dict(Presupuesto.MetodoPago.choices).get(f['metodo'], '')
    return respuesta_pdf(cobranza.pdf(filas, tot, f['desde'], f['hasta'], request.empresa, filtro),
                         'Cobranza', f['desde'], f['hasta'])


@login_required
@requiere('presupuestos.crear')
def reporte_excel(request):
    f, filas, tot = _filtros(request)
    r = HttpResponse(cobranza.excel(filas, tot, f['desde'], f['hasta']),
                     content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    r['Content-Disposition'] = f'attachment; filename="{nombre_archivo("Cobranza", f["desde"], f["hasta"], extension="xlsx")}"'
    return r
