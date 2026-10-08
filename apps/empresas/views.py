import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from reportlab.platypus import Spacer

from apps.core.pdf import Paragraph  # noqa: E402  (escapa & y < de los datos)

from apps.core.middleware import SESION_EMPRESA
from apps.core.pdf import ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.permisos import requiere

from .forms import PerfilEmpresaForm
from .models import Membresia
from .servicios import generar_logo_pdf


@login_required
def seleccionar(request):
    """Elegir con qué empresa trabajar (usuarios con varias membresías)."""
    siguiente = request.GET.get('next') or request.POST.get('next') or '/'
    if not url_has_allowed_host_and_scheme(siguiente, {request.get_host()}):
        siguiente = '/'
    if request.method == 'POST':
        try:
            empresa_id = int(request.POST.get('empresa'))
        except (TypeError, ValueError):
            raise Http404
        if not any(m.empresa_id == empresa_id for m in request.membresias):
            raise Http404
        request.session[SESION_EMPRESA] = empresa_id
        return redirect(siguiente)
    if not request.membresias:
        return redirect('empresas:sin_empresa')
    return render(request, 'empresas/seleccionar.html', {
        'titulo': 'Elige una empresa', 'siguiente': siguiente,
    })


@login_required
def sin_empresa(request):
    if request.membresias:
        return redirect('core:inicio')
    suspendidas = [m.empresa for m in Membresia.objects.filter(usuario=request.user, activa=True)
                   .select_related('empresa', 'empresa__perfil') if not m.empresa.esta_activa]
    return render(request, 'empresas/sin_empresa.html', {'titulo': 'Sin empresa asignada', 'suspendidas': suspendidas})


@login_required
@requiere('empresa.configurar')
def mi_empresa(request):
    perfil = request.empresa.perfil
    logo_anterior = perfil.logo.name if perfil.logo else ''
    if request.method == 'POST':
        form = PerfilEmpresaForm(request.POST, request.FILES, instance=perfil)
        if form.is_valid():
            perfil = form.save()
            nuevo_logo = perfil.logo.name if perfil.logo else ''
            if nuevo_logo != logo_anterior:
                generar_logo_pdf(perfil)
                perfil.save(update_fields=['logo_pdf'])
            messages.success(request, 'Datos de la empresa guardados.')
            return redirect(f"{request.path}?tab={request.POST.get('tab', 'identidad')}")
        messages.error(request, 'Revisa los campos marcados.')
    else:
        form = PerfilEmpresaForm(instance=perfil)
    return render(request, 'empresas/mi_empresa.html', {
        'titulo': 'Mi empresa',
        'form': form,
        'tab': request.GET.get('tab', 'identidad'),
    })


@login_required
@requiere('empresa.configurar')
@require_POST
def vista_previa(request):
    """HTMX: encabezado de documento con los datos escritos (sin guardar)."""
    form = PerfilEmpresaForm(request.POST, instance=request.empresa.perfil)
    form.is_valid()  # solo para poblar cleaned_data; no se guarda
    perfil = request.empresa.perfil
    campos = [f for f in form.Meta.fields if f not in ('logo', 'firma')]
    datos = {f: form.cleaned_data.get(f, getattr(perfil, f)) for f in campos}
    return render(request, 'empresas/partials/vista_previa.html', {'d': datos})


@login_required
@requiere('empresa.configurar')
def pdf_prueba(request):
    """PDF de ejemplo para ver cómo salen el logo y los datos en los documentos."""
    empresa = request.empresa
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'Prueba — {empresa.perfil.nombre_comercial}')
    hoy = timezone.localdate().strftime('%d/%m/%Y')
    elementos = encabezado_empresa(empresa, titulo='DOCUMENTO DE PRUEBA', subtitulo=f'Fecha: {hoy}')
    elementos += [
        Paragraph('Así se verá el encabezado en presupuestos, órdenes de compra, listas de precios y '
                  'liquidaciones de comisiones.', ESTILOS['Normal']),
        Spacer(1, 8),
    ]
    perfil = empresa.perfil
    if perfil.condiciones_presupuesto:
        elementos += [Paragraph('<b>Condiciones</b>', ESTILOS['Normal']),
                      Paragraph(perfil.condiciones_presupuesto.replace('\n', '<br/>'), ESTILOS['Normal']),
                      Spacer(1, 8)]
    if perfil.datos_bancarios:
        elementos += [Paragraph('<b>Datos para el pago</b>', ESTILOS['Normal']),
                      Paragraph(perfil.datos_bancarios.replace('\n', '<br/>'), ESTILOS['Normal'])]
    pie = pie_empresa(empresa)
    doc.build(elementos, onFirstPage=pie, onLaterPages=pie)
    respuesta = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    respuesta['Content-Disposition'] = 'inline; filename="prueba-encabezado.pdf"'
    return respuesta


@login_required
@requiere('tasa.cargar')
def tasa(request):
    """Tasa del día de la empresa: ver la vigente, cargar una propia si el BCV no actualizó, o volver a la del BCV."""
    from datetime import date
    from decimal import Decimal, InvalidOperation

    from django.utils import timezone

    from apps.tasas import servicios as tasas
    from apps.tasas.models import TasaCambio, TasaEmpresa
    hoy = timezone.localdate()
    empresa = request.empresa
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'borrar':
            try:
                fecha = date.fromisoformat(request.POST.get('fecha', ''))
            except ValueError:
                fecha = None
            if fecha:
                tasas.borrar_de_empresa(empresa, fecha)
                messages.success(request, 'Tasa propia eliminada: se usa la del BCV.')
        elif accion == 'bcv':
            try:
                t = tasas.actualizar_desde_bcv()
                messages.success(request, f'BCV consultado: Bs {t.bs_por_usd} ({t.fecha:%d/%m/%Y}).')
            except Exception as e:  # el sitio del BCV falla seguido
                logging.getLogger('apps.tasas').warning('Consulta al BCV desde %s falló: %s', empresa, e)
                messages.error(request, 'El BCV no respondió. Puedes cargar la tasa del día a mano.')
        else:
            try:
                texto = request.POST.get('valor', '').strip()
                if ',' in texto:                       # formato venezolano: 1.234,5678
                    texto = texto.replace('.', '').replace(',', '.')
                valor = Decimal(texto)
                if valor <= 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                messages.error(request, 'Indica una tasa mayor que cero (ej.: 36,5021).')
            else:
                tasas.registrar_de_empresa(empresa, valor.quantize(Decimal('0.0001')), request.user, hoy)
                messages.success(request, f'Tasa de hoy guardada para {empresa.nombre}: Bs {valor}.')
        return redirect('empresas:tasa')
    return render(request, 'empresas/tasa.html', {
        'titulo': 'Tasa del día', 'hoy': hoy, 'vigente': tasas.tasa_vigente(empresa), 'bcv': tasas.tasa_global(),
        'propias': TasaEmpresa.objects.select_related('registrada_por')[:30],
        'historial_bcv': TasaCambio.objects.all()[:15],
    })
