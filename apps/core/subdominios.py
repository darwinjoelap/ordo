"""
Subdominio por empresa (como Ordo Salud, ADR-049): https://<slug>.<BASE_DOMAIN>/  →  esa empresa.

- Sin BASE_DOMAIN (desarrollo, dirección de Railway) todo sigue por ruta: /<slug>/.
- <slug>.app.ordove.com: la empresa sale del host; sin sesión, la raíz es su login con su marca.
  Con sesión, solo vale una membresía de ESA empresa (o soporte de plataforma). /plataforma/ y /admin/ no existen.
- admin.app.ordove.com: panel de plataforma (cuentas sin empresa).
- app.ordove.com/<slug>/: redirige al subdominio.
Las cookies quedan en cada subdominio (no se fija SESSION_COOKIE_DOMAIN): cada empresa tiene su propia sesión.
"""
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect

ADMIN = 'admin'
NO_EMPRESA = {ADMIN, 'www', 'app', 'api', 'static', 'media', 'mail'}


def base():
    return (getattr(settings, 'BASE_DOMAIN', '') or '').strip().lower().strip('.')


def host_de(request):
    return request.get_host().split(':')[0].lower()


def subdominio(request):
    """'' si el host no es un subdominio de BASE_DOMAIN; si no, el primer nivel ('agroservicios', 'admin'…)."""
    dominio = base()
    host = host_de(request)
    if not dominio or not host.endswith('.' + dominio):
        return ''
    resto = host[:-len(dominio) - 1]
    return '' if '.' in resto else resto


def enlace(request, slug):
    """Dirección que se le da a la empresa: su subdominio si hay BASE_DOMAIN; si no, /<slug>/ en este host."""
    dominio = base()
    if dominio:
        return f"{'https' if request.is_secure() else 'http'}://{slug}.{dominio}/"
    return request.build_absolute_uri(f'/{slug}/')


class SubdominioMiddleware:
    """Va después de AuthenticationMiddleware y antes de EmpresaActivaMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa_host = None
        request.es_admin_host = False
        sub = subdominio(request)
        if sub == ADMIN:
            request.es_admin_host = True
            if request.path == '/':
                return redirect('plataforma:lista' if request.user.is_authenticated else '/cuenta/entrar/?plataforma=1')
        elif sub and sub not in NO_EMPRESA:
            from apps.empresas.models import Empresa
            empresa = Empresa.objects.select_related('perfil').filter(slug=sub).first()
            if empresa is None:
                raise Http404('Empresa no encontrada')
            request.empresa_host = empresa
            request.empresa_login = empresa          # cualquier login en este host busca el usuario de esta empresa
            if request.path.startswith(('/plataforma/', '/admin/')):
                raise Http404
            if not request.user.is_authenticated and request.path in ('/', '/cuenta/entrar/'):
                from apps.empresas.views_entrada import EntradaEmpresa
                respuesta = EntradaEmpresa.as_view()(request, slug=empresa.slug)
                return respuesta.render() if hasattr(respuesta, 'render') else respuesta
        return self.get_response(request)
