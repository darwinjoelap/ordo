from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere

from . import equipo
from .forms import InvitarForm
from .models import Membresia, Rol


def _miembros(request):
    return Membresia.objects.filter(empresa=request.empresa).select_related('usuario')


@login_required
@requiere('usuarios.gestionar')
def lista(request):
    actor = request.membresia
    miembros = list(_miembros(request).order_by('-activa', 'usuario__first_name', 'usuario__email'))
    for m in miembros:
        m.gestionable = equipo.puede_gestionar(actor, m)
        m.clave_restablecible = m.gestionable and equipo.solo_en_esta_empresa(m.usuario, request.empresa)
    return render(request, 'empresas/equipo.html', {
        'titulo': 'Equipo', 'miembros': miembros, 'roles': equipo.roles_asignables(actor),
        'form': InvitarForm(roles=equipo.roles_asignables(actor), initial={'rol': Rol.VENDEDOR}),
    })


@login_required
@requiere('usuarios.gestionar')
@require_POST
def agregar(request):
    roles = equipo.roles_asignables(request.membresia)
    form = InvitarForm(request.POST, roles=roles)
    if form.is_valid():
        d = form.cleaned_data
        try:
            m, clave = equipo.agregar(request.empresa, request.membresia, d['email'], d['nombre'], d['apellido'], d['rol'])
        except equipo.ErrorEquipo as e:
            messages.error(request, str(e))
        else:
            if clave:
                return render(request, 'empresas/equipo_credenciales.html', {
                    'titulo': 'Acceso creado', 'usuario': m.usuario, 'clave': clave, 'nuevo': True})
            messages.success(request, f'{m.usuario} ya tenía cuenta en Ordo: se agregó al equipo con su misma contraseña.')
        return redirect('empresas:equipo')
    for campo, errores in form.errors.items():
        messages.error(request, f'{form.fields[campo].label if campo in form.fields else ""}: {" ".join(errores)}')
    return redirect('empresas:equipo')


@login_required
@requiere('usuarios.gestionar')
@require_POST
def actualizar(request, pk):
    m = get_object_or_404(_miembros(request), pk=pk)
    try:
        equipo.actualizar(request.membresia, m, request.POST.get('rol', m.rol), request.POST.get('activa') == '1')
    except equipo.ErrorEquipo as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f'{m.usuario}: cambios guardados.')
    return redirect('empresas:equipo')


@login_required
@requiere('usuarios.gestionar')
@require_POST
def restablecer_clave(request, pk):
    m = get_object_or_404(_miembros(request), pk=pk)
    try:
        clave = equipo.restablecer_clave(request.membresia, m)
    except equipo.ErrorEquipo as e:
        messages.error(request, str(e))
        return redirect('empresas:equipo')
    return render(request, 'empresas/equipo_credenciales.html', {
        'titulo': 'Contraseña temporal', 'usuario': m.usuario, 'clave': clave, 'nuevo': False})
