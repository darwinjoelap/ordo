from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
import logging

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.middleware import SESION_EMPRESA, SESION_SOPORTE

from . import plataforma
from .forms import EditarEmpresaForm, NuevaEmpresaForm
from .models import Empresa, Membresia


def solo_plataforma(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return login_required(envoltura)


def _enlace(request, empresa):
    return request.build_absolute_uri(f'/{empresa.slug}/')


@solo_plataforma
def lista(request):
    q = request.GET.get('q', '').strip()
    empresas = (Empresa.objects.select_related('perfil')
                .annotate(n_activos=Count('membresias', filter=Q(membresias__activa=True,
                                                               membresias__usuario__is_superuser=False))).order_by('nombre'))
    if q:
        empresas = empresas.filter(Q(nombre__icontains=q) | Q(slug__icontains=q) | Q(perfil__rif__icontains=q)
                                   | Q(perfil__razon_social__icontains=q))
    empresas = list(empresas)
    for e in empresas:
        e.enlace = _enlace(request, e)
    return render(request, 'plataforma/lista.html', {'titulo': 'Empresas', 'empresas': empresas, 'q': q})


@solo_plataforma
def nueva(request):
    form = NuevaEmpresaForm(request.POST or None, initial={'plan': Empresa.Plan.PRUEBA})
    if request.method == 'POST' and form.is_valid():
        empresa, dueno, clave = plataforma.crear_empresa(form.cleaned_data)
        return render(request, 'plataforma/creada.html', {
            'titulo': 'Empresa creada', 'empresa': empresa, 'dueno': dueno, 'clave': clave,
            'enlace': _enlace(request, empresa)})
    return render(request, 'plataforma/form.html', {'titulo': 'Nueva empresa', 'form': form})


@solo_plataforma
def editar(request, pk):
    empresa = get_object_or_404(Empresa.objects.select_related('perfil'), pk=pk)
    inicial = {'nombre_comercial': empresa.nombre, 'razon_social': empresa.perfil.razon_social,
               'rif': empresa.perfil.rif, 'slug': empresa.slug, 'plan': empresa.plan, 'estado': empresa.estado,
               'activa_hasta': empresa.activa_hasta, 'limite_usuarios': empresa.limite_usuarios,
               'notas': empresa.notas}
    form = EditarEmpresaForm(request.POST or None, initial=inicial, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        datos = dict(form.cleaned_data, nombre=form.cleaned_data['nombre_comercial'])
        plataforma.actualizar_empresa(empresa, datos)
        messages.success(request, f'{empresa.nombre}: cambios guardados.')
        return redirect('plataforma:editar', pk=pk)
    miembros = Membresia.objects.filter(empresa=empresa, usuario__is_superuser=False).select_related('usuario').order_by('-activa', 'rol')
    return render(request, 'plataforma/form.html', {
        'titulo': empresa.nombre, 'form': form, 'empresa': empresa, 'miembros': miembros,
        'enlace': _enlace(request, empresa)})


log = logging.getLogger('apps.plataforma')


@solo_plataforma
@require_POST
def entrar(request, pk):
    """El superusuario entra a la empresa como Soporte Ordo (permisos de Dueño, sin ser miembro)."""
    empresa = get_object_or_404(Empresa, pk=pk)
    request.session[SESION_SOPORTE] = empresa.pk
    request.session.pop(SESION_EMPRESA, None)
    log.warning('Soporte: %s entró a la empresa %s (%s)', request.user.username, empresa.nombre, empresa.pk)
    return redirect('core:inicio')


@solo_plataforma
@require_POST
def salir(request):
    request.session.pop(SESION_SOPORTE, None)
    request.session.pop(SESION_EMPRESA, None)
    return redirect('plataforma:lista')


@solo_plataforma
def tasas(request):
    """Tasa BCV (única para todas las empresas): historial, carga manual y consulta al BCV."""
    from datetime import date
    from decimal import Decimal, InvalidOperation

    from django.utils import timezone

    from apps.tasas import servicios as tasas_srv
    from apps.tasas.models import TasaCambio
    if request.method == 'POST':
        if request.POST.get('accion') == 'bcv':
            try:
                t = tasas_srv.actualizar_desde_bcv()
                messages.success(request, f'Tasa BCV registrada: Bs {t.bs_por_usd} ({t.fecha:%d/%m/%Y}).')
            except Exception as e:  # el BCV falla seguido: se informa y se puede cargar a mano
                logging.getLogger('apps.tasas').warning('Consulta manual al BCV falló: %s', e)
                messages.error(request, f'No se pudo consultar el BCV ({e.__class__.__name__}). Cárgala a mano.')
        else:
            try:
                texto = request.POST.get('valor', '').strip()
                if ',' in texto:                      # formato venezolano: 1.234,5678
                    texto = texto.replace('.', '').replace(',', '.')
                valor = Decimal(texto)
                fecha = date.fromisoformat(request.POST.get('fecha') or timezone.localdate().isoformat())
                if valor <= 0:
                    raise InvalidOperation
                if fecha > timezone.localdate():
                    raise ValueError('futura')
            except (InvalidOperation, ValueError):
                messages.error(request, 'Indica una tasa mayor que cero y una fecha que no sea futura.')
            else:
                tasas_srv.registrar(valor.quantize(Decimal('0.0001')), TasaCambio.Fuente.MANUAL, request.user, fecha)
                messages.success(request, f'Tasa del {fecha:%d/%m/%Y} guardada: Bs {valor}.')
        return redirect('plataforma:tasas')
    return render(request, 'plataforma/tasas.html', {
        'titulo': 'Tasa BCV', 'tasas': TasaCambio.objects.select_related('registrada_por')[:60],
        'vigente': tasas_srv.tasa_global(), 'hoy': timezone.localdate()})
