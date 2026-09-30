from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import CambioClaveForm, PerfilForm


@login_required
def perfil(request):
    """Datos personales y cambio de contraseña del usuario que inició sesión."""
    accion = request.POST.get('accion') if request.method == 'POST' else None
    form = PerfilForm(request.POST if accion == 'datos' else None, instance=request.user)
    form_clave = CambioClaveForm(request.user, request.POST if accion == 'clave' else None)
    if accion == 'datos' and form.is_valid():
        form.save()
        messages.success(request, 'Tus datos se guardaron.')
        return redirect('usuarios:perfil')
    if accion == 'clave' and form_clave.is_valid():
        usuario = form_clave.save()
        usuario.debe_cambiar_clave = False
        usuario.save(update_fields=['debe_cambiar_clave'])
        update_session_auth_hash(request, usuario)      # no cierra la sesión
        messages.success(request, 'Contraseña cambiada.')
        return redirect('/')
    return render(request, 'usuarios/perfil.html', {
        'titulo': 'Mi perfil', 'form': form, 'form_clave': form_clave,
        'obligatorio': request.user.debe_cambiar_clave,
    })
