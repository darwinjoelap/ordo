"""Obliga a cambiar la contraseña temporal antes de usar Ordo."""
from django.shortcuts import redirect

LIBRES = ('/cuenta/', '/static/', '/media/', '/salud/', '/manifest.webmanifest', '/sw.js', '/offline/', '/favicon.ico')


class CambioClaveObligatorioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, 'user', None)
        if u is not None and u.is_authenticated and u.debe_cambiar_clave and not request.path.startswith(LIBRES):
            return redirect('/cuenta/perfil/?clave=1')
        return self.get_response(request)
