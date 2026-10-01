"""
Fija request.empresa y request.membresia para cada request autenticado.
"""
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from apps.empresas.models import Empresa, Membresia, Rol

from .tenancy import fijar_empresa, restaurar_empresa

SESION_EMPRESA = 'empresa_id'
SESION_SOPORTE = 'soporte_empresa_id'   # superusuario dentro de una empresa sin ser miembro


def membresia_soporte(usuario, empresa):
    """Membresía virtual (no se guarda) con la que un superusuario opera dentro de cualquier empresa."""
    m = Membresia(usuario=usuario, empresa=empresa, rol=Rol.DUENO, activa=True)
    m.soporte = True
    return m

# Rutas que funcionan sin empresa elegida
PREFIJOS_LIBRES = ('/static/', '/media/', '/admin/', '/salud/', '/cuenta/', '/__debug__/', '/plataforma/',
                   '/favicon.ico', '/manifest.webmanifest', '/sw.js', '/offline/', '/instalar/')


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
            soporte_id = request.session.get(SESION_SOPORTE) if request.user.is_superuser else None
            if soporte_id:
                empresa = Empresa.objects.select_related('perfil').filter(pk=soporte_id).first()
                elegida = membresia_soporte(request.user, empresa) if empresa else None
            if elegida is None and len(membresias) == 1 and not request.user.is_superuser:
                elegida = membresias[0]
                request.session[SESION_EMPRESA] = elegida.empresa_id

            if elegida:
                request.membresia = elegida
                request.empresa = elegida.empresa
                token = fijar_empresa(elegida.empresa)
            elif not request.path.startswith(PREFIJOS_LIBRES) and not self._es_ruta_empresas(request):
                if request.user.is_superuser:
                    return redirect('plataforma:lista')
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
        if request.path in (reverse('empresas:seleccionar'), reverse('empresas:sin_empresa')):
            return True
        try:                                   # enlace propio de una empresa: /<slug>/
            return resolve(request.path_info).url_name == 'entrada_empresa'
        except Resolver404:
            return False
