"""
Enlace propio de cada empresa: https://<dominio>/<slug>/

- Sin sesión: login con la marca de la empresa; al entrar queda elegida esa empresa.
- Con sesión y membresía activa: elige esa empresa y va al inicio.
- Empresa suspendida o vencida: aviso, sin acceso.
"""
from django.contrib.auth import views as auth_views
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.middleware import SESION_EMPRESA, SESION_SOPORTE
from apps.usuarios.forms import LoginForm

from .models import Empresa, Membresia

COOKIE_EMPRESA = 'ordo_empresa'


def _membresia(usuario, empresa):
    return Membresia.objects.filter(usuario=usuario, empresa=empresa, activa=True).first()


class EntradaEmpresa(auth_views.LoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginForm

    def dispatch(self, request, *args, **kwargs):
        self.empresa = get_object_or_404(Empresa.objects.select_related('perfil'), slug=kwargs['slug'])
        if not self.empresa.esta_activa and not request.user.is_superuser:
            return render(request, 'empresas/suspendida.html', {'empresa_marca': self.empresa}, status=403)
        request.empresa_login = self.empresa          # el backend busca el usuario dentro de esta empresa
        if request.user.is_authenticated:
            if _membresia(request.user, self.empresa):
                request.session[SESION_EMPRESA] = self.empresa.pk
                request.session.pop(SESION_SOPORTE, None)
                return redirect('core:inicio')
            if request.user.is_superuser:
                request.session[SESION_SOPORTE] = self.empresa.pk
                return redirect('core:inicio')
            return render(request, 'empresas/sin_acceso.html', {'empresa_marca': self.empresa}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa_marca'] = self.empresa
        return ctx

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        # Recordar la empresa en este equipo: la dirección principal y la app instalada vuelven a su login
        respuesta.set_cookie(COOKIE_EMPRESA, self.empresa.slug, max_age=60 * 60 * 24 * 365, samesite='Lax',
                             secure=self.request.is_secure(), httponly=True)
        usuario = form.get_user()
        if _membresia(usuario, self.empresa):
            self.request.session[SESION_EMPRESA] = self.empresa.pk
        elif usuario.is_superuser:
            self.request.session[SESION_SOPORTE] = self.empresa.pk
        return respuesta

    def get_success_url(self):
        return '/'


def entrada(request, slug):
    if slug != slug.lower():
        raise Http404
    return EntradaEmpresa.as_view()(request, slug=slug)
