"""
Fija request.empresa y request.membresia para cada request autenticado.
"""
from django.shortcuts import redirect
from django.urls import reverse

from apps.empresas.models import Membresia

from .tenancy import fijar_empresa, restaurar_empresa

SESION_EMPRESA = 'empresa_id'

# Rutas que funcionan sin empresa elegida
PREFIJOS_LIBRES = ('/static/', '/media/', '/admin/', '/salud/', '/cuenta/', '/__debug__/',
                   '/favicon.ico', '/manifest.webmanifest', '/sw.js')


class EmpresaActivaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None
        request.membresia = None
        token = None

        if request.user.is_authenticated:
            membresias = [
                m for m in Membresia.objects.filter(usuario=request.user, activa=True)
                .select_related('empresa', 'empresa__perfil')
                if m.empresa.esta_activa
            ]
            request.membresias = membresias
            elegida = None
            empresa_id = request.session.get(SESION_EMPRESA)
            if empresa_id:
                elegida = next((m for m in membresias if m.empresa_id == empresa_id), None)
            if elegida is None and len(membresias) == 1:
                elegida = membresias[0]
                request.session[SESION_EMPRESA] = elegida.empresa_id

            if elegida:
                request.membresia = elegida
                request.empresa = elegida.empresa
                token = fijar_empresa(elegida.empresa)
            elif not request.path.startswith(PREFIJOS_LIBRES) and not self._es_ruta_empresas(request):
                if membresias:
                    return redirect(f"{reverse('empresas:seleccionar')}?next={request.get_full_path()}")
                return redirect('empresas:sin_empresa')
        else:
            request.membresias = []

        try:
            return self.get_response(request)
        finally:
            if token is not None:
                restaurar_empresa(token)

    @staticmethod
    def _es_ruta_empresas(request):
        return request.path in (reverse('empresas:seleccionar'), reverse('empresas:sin_empresa'))
