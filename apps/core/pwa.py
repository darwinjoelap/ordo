"""
PWA: manifest, service worker y página sin conexión.

El service worker:
- precarga estáticos (CSS/JS/iconos) y la página /offline/;
- estáticos: primero caché (tienen hash en el nombre gracias a WhiteNoise);
- páginas: SIEMPRE red; si no hay conexión muestra /offline/;
- excepción: Consulta rápida (apps/core/consulta.py) guarda su pantalla y sus datos para verlos sin conexión.
  No guarda HTML de la app en caché: los datos son por empresa y por usuario.
"""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control, never_cache

PRECARGA = [
    'vendor/bootstrap/bootstrap.min.css',
    'vendor/bootstrap-icons/bootstrap-icons.min.css',
    'css/ordo.css',
    'vendor/bootstrap/bootstrap.bundle.min.js',
    'vendor/htmx/htmx.min.js',
    'js/pwa.js',
    'js/consulta.js',
    'img/marca/ordo-simbolo-web.png',
    'img/marca/ordo-logo-horizontal-web.png',
    'img/marca/pwa/icon-192.png',
]


@cache_control(max_age=3600, public=True)
def manifest(request):
    datos = {
        'id': '/',
        'name': 'Ordo — Gestión comercial',
        'short_name': 'Ordo',
        'description': 'Presupuestos, ventas, inventario y comisiones.',
        'lang': 'es',
        'start_url': '/?origen=app',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait-primary',
        'background_color': '#F4F6F9',
        'theme_color': '#053D74',
        'icons': [
            {'src': static('img/marca/pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('img/marca/pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('img/marca/pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Nuevo presupuesto', 'short_name': 'Presupuesto', 'url': '/ventas/nuevo/',
             'icons': [{'src': static('img/marca/pwa/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'Inventario', 'url': '/inventario/',
             'icons': [{'src': static('img/marca/pwa/icon-192.png'), 'sizes': '192x192'}]},
        ],
    }
    return JsonResponse(datos, content_type='application/manifest+json', json_dumps_params={'ensure_ascii': False})


@never_cache
def service_worker(request):
    version = settings.ORDO_VERSION
    precarga = [static(r) for r in PRECARGA] + ['/offline/']
    js = SW_JS.replace('__VERSION__', version).replace('__PRECARGA__', json.dumps(precarga)) \
              .replace('__STATIC__', settings.STATIC_URL)
    r = HttpResponse(js, content_type='application/javascript; charset=utf-8')
    r['Service-Worker-Allowed'] = '/'
    return r


@cache_control(max_age=86400, public=True)
def offline(request):
    return render(request, 'core/offline.html')


SW_JS = r"""// Ordo service worker · versión __VERSION__
const CACHE = 'ordo-__VERSION__';
const PRECARGA = __PRECARGA__;
const STATIC = '__STATIC__';
const CONSULTA = 'consulta-ordo';   // no empieza por "ordo-": sobrevive a los despliegues

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECARGA)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k.startsWith('ordo-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Estáticos: primero caché, luego red (y se guarda)
  if (url.pathname.startsWith(STATIC)) {
    e.respondWith(
      caches.match(req).then((r) => r || fetch(req).then((resp) => {
        if (resp.ok) { const copia = resp.clone(); caches.open(CACHE).then((c) => c.put(req, copia)); }
        return resp;
      }))
    );
    return;
  }

  // Consulta rápida (pantalla y datos): primero red y se guarda la última respuesta; sin conexión, lo guardado.
  // Si la sesión terminó (redirige al login o 401/403) se borra lo guardado en este dispositivo.
  if (url.pathname === '/consulta/' || url.pathname === '/consulta/datos.json') {
    e.respondWith(
      fetch(req).then((resp) => {
        if (resp.ok && !resp.redirected) {
          const copia = resp.clone(); caches.open(CONSULTA).then((c) => c.put(url.pathname, copia));
        } else if (resp.redirected || resp.status === 401 || resp.status === 403) {
          caches.delete(CONSULTA);
        }
        return resp;
      }).catch(() => caches.open(CONSULTA).then((c) => c.match(url.pathname))
        .then((r) => r || (req.mode === 'navigate' ? caches.match('/offline/') : Response.error())))
    );
    return;
  }

  // Páginas: siempre red; sin conexión → /offline/
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/offline/')));
  }
});
"""


@login_required
def visor_pdf(request):
    """
    Muestra un PDF de la app DENTRO de la app (pdf.js). En la PWA instalada, abrir el PDF directo saca al usuario
    de la app y "atrás" la cierra; con el visor, "atrás" vuelve a la pantalla anterior.
    Solo acepta rutas internas (?u=/ventas/5/pdf/).
    """
    u = request.GET.get('u', '')
    if not u.startswith('/') or u.startswith('//') or '\\' in u \
            or not url_has_allowed_host_and_scheme(u, allowed_hosts=None):
        raise Http404
    return render(request, 'core/visor_pdf.html', {'titulo': 'Documento', 'url_pdf': u})


def instalar(request):
    return render(request, 'core/instalar.html', {'titulo': 'Instalar Ordo'})
