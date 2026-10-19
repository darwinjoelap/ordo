"""Agenda de servicios, ficha de cada servicio (programar / realizado), constancia y reporte."""
from datetime import time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.pdf import nombre_archivo, respuesta_pdf
from apps.core.permisos import requiere, tiene_permiso

from . import agenda as srv
from .pdf_servicios import constancia_pdf as pdf_constancia, reporte_excel as excel_reporte, reporte_pdf as pdf_reporte
from .servicios import ErrorVenta
from .views import _fecha_o_none, visibles


def _exigir_activo(request):
    if not srv.activo(request.empresa):
        raise Http404('Los servicios están desactivados en Mi empresa.')


def _lineas(request):
    """Líneas de servicio que este usuario puede ver (el vendedor, solo las de sus ventas)."""
    return srv.de_ventas(visibles(request))


def _equipo(request):
    return get_user_model().objects.filter(membresias__empresa=request.empresa, membresias__activa=True,
                                           is_superuser=False).distinct().order_by('first_name', 'username')


def _hora_o_none(texto):
    try:
        return time.fromisoformat(texto) if texto else None
    except ValueError:
        return None


@login_required
@requiere('servicios.gestionar')
def agenda(request):
    _exigir_activo(request)
    g = request.GET
    claves = [c for c, _, _ in srv.PESTANAS]
    tab = g.get('tab') if g.get('tab') in claves else 'hoy'
    q, responsable = g.get('q', '').strip(), g.get('responsable', '')
    qs = _lineas(request)
    if q:
        qs = qs.filter(Q(presupuesto__cliente__nombre__icontains=q) | Q(producto__nombre__icontains=q)
                       | Q(presupuesto__numero__icontains=q))
    if responsable == 'sin':
        qs = qs.filter(responsable__isnull=True, responsable_nombre='')
    elif responsable.isdigit():
        qs = qs.filter(responsable_id=responsable)
    conteos = srv.resumen(qs)
    filas = srv.pestana(qs, tab)
    if tab == 'realizados':
        desde, hasta = _fecha_o_none(g.get('desde')), _fecha_o_none(g.get('hasta'))
        if desde:
            filas = filas.filter(realizado_en__date__gte=desde)
        if hasta:
            filas = filas.filter(realizado_en__date__lte=hasta)
    pagina = Paginator(filas, 30).get_page(g.get('page'))
    perfil = request.empresa.perfil
    for i in pagina:
        i.etiqueta = srv.ETIQUETAS[i.estado_servicio]
        i.whatsapp = srv.enlace_whatsapp(i, perfil) if not i.realizado_en else ''
    params = g.copy()
    params.pop('page', None)
    params['tab'] = tab
    querystring_pagina = params.urlencode()
    params.pop('tab', None)
    return render(request, 'ventas/servicios_agenda.html', {
        'titulo': 'Agenda de servicios', 'pagina': pagina, 'tab': tab, 'conteos': conteos,
        'pestanas': [(c, t, icono, conteos.get(c)) for c, t, icono in srv.PESTANAS],
        'f': {'q': q, 'responsable': responsable, 'desde': g.get('desde', ''), 'hasta': g.get('hasta', '')},
        'querystring': params.urlencode(), 'querystring_pagina': querystring_pagina,
        'equipo': _equipo(request), 'hoy': timezone.localdate(),
    })


@login_required
@requiere('servicios.gestionar')
def servicio(request, pk):
    _exigir_activo(request)
    item = get_object_or_404(_lineas(request), pk=pk)
    p = item.presupuesto
    if request.method == 'POST':
        accion = request.POST.get('accion')
        try:
            if accion == 'programar':
                fecha = _fecha_o_none(request.POST.get('fecha'))
                responsable = None
                quien = request.POST.get('responsable', '')
                if quien.isdigit():
                    responsable = _equipo(request).filter(pk=quien).first()
                srv.programar(item, fecha, _hora_o_none(request.POST.get('hora')), responsable,
                                 request.POST.get('responsable_nombre', '') if quien == 'otro' else '')
                messages.success(request, 'Servicio programado.' if fecha else 'Se quitó la fecha del servicio.')
            elif accion == 'realizar':
                fecha = _fecha_o_none(request.POST.get('fecha_realizado')) or timezone.localdate()
                cuando = srv.combinar(fecha, _hora_o_none(request.POST.get('hora_realizado')))
                srv.realizar(item, request.user, cuando, request.POST.get('nota', ''),
                                request.POST.get('recibe_nombre', ''), request.POST.get('recibe_cedula', ''),
                                request.POST.get('firma', ''))
                messages.success(request, 'Servicio marcado como realizado.')
            elif accion == 'deshacer':
                if not tiene_permiso(request, 'servicios.deshacer'):
                    raise ErrorVenta('Solo el dueño o un administrador puede deshacer un «realizado».')
                srv.deshacer(item)
                messages.success(request, 'Se deshizo el «realizado». El servicio vuelve a la agenda.')
        except ErrorVenta as e:
            messages.error(request, str(e))
        return redirect('ventas:servicio', pk=pk)
    perfil = request.empresa.perfil
    ahora = timezone.localtime()
    return render(request, 'ventas/servicio.html', {
        'titulo': item.producto.nombre, 'i': item, 'p': p, 'etiqueta': srv.ETIQUETAS[item.estado_servicio],
        'equipo': _equipo(request), 'puede_realizar': p.estado in srv.CONFIRMADAS and not item.realizado_en,
        'puede_programar': p.estado not in p.CAIDAS and not item.realizado_en,
        'puede_deshacer': tiene_permiso(request, 'servicios.deshacer') and bool(item.realizado_en),
        'whatsapp': srv.enlace_whatsapp(item, perfil), 'tiene_telefono': bool(srv.telefono_whatsapp(p.cliente.telefono)),
        'ahora_fecha': ahora.date().isoformat(), 'ahora_hora': ahora.strftime('%H:%M'),
        'otros': [o for o in srv.de_ventas([p]).order_by('pk') if o.pk != item.pk],
    })


@login_required
@requiere('servicios.gestionar')
def constancia_pdf(request, pk):
    _exigir_activo(request)
    item = get_object_or_404(_lineas(request), pk=pk)
    return respuesta_pdf(pdf_constancia(item, request.empresa), f'Servicio {item.presupuesto.numero}-S{item.pk}')


def _datos_reporte(request):
    _exigir_activo(request)
    g = request.GET
    desde, hasta = srv.rango(_fecha_o_none(g.get('desde')), _fecha_o_none(g.get('hasta')))
    qs = _lineas(request)
    responsable = g.get('responsable', '')
    if responsable.isdigit():
        qs = qs.filter(responsable_id=responsable)
    servicio_id = g.get('servicio', '')
    if servicio_id.isdigit():
        qs = qs.filter(producto_id=servicio_id)
    return {'desde': desde, 'hasta': hasta, 'responsable': responsable, 'servicio': servicio_id}, \
        srv.reporte(qs, desde, hasta)


@login_required
@requiere('reportes.ver')
def reporte(request):
    f, datos = _datos_reporte(request)
    from apps.inventario.models import Producto
    return render(request, 'ventas/servicios_reporte.html', {
        'titulo': 'Reporte de servicios', 'f': f, 'd': datos, 'equipo': _equipo(request),
        'servicios': Producto.objects.servicios().order_by('nombre').only('pk', 'nombre'),
        'querystring': request.GET.urlencode(),
    })


@login_required
@requiere('reportes.ver')
def reporte_pdf(request):
    f, datos = _datos_reporte(request)
    return respuesta_pdf(pdf_reporte(datos, f['desde'], f['hasta'], request.empresa), 'Servicios', f['desde'], f['hasta'])


@login_required
@requiere('reportes.ver')
def reporte_excel(request):
    f, datos = _datos_reporte(request)
    r = HttpResponse(excel_reporte(datos, f['desde'], f['hasta']),
                     content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    r['Content-Disposition'] = (f'attachment; filename="{nombre_archivo("Servicios", f["desde"], f["hasta"], extension="xlsx")}"')
    return r
