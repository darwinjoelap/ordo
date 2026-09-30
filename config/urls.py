"""
Ordo — URLs raíz.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.shortcuts import redirect

urlpatterns = [
    path('', include('apps.core.urls', namespace='core')),
    path('cuenta/', include('apps.usuarios.urls', namespace='usuarios')),
    path('empresa/', include('apps.empresas.urls', namespace='empresas')),
    path('inventario/', include('apps.inventario.urls', namespace='inventario')),
    path('proveedores/', include('apps.proveedores.urls', namespace='proveedores')),
    path('compras/', include('apps.compras.urls', namespace='compras')),
    path('clientes/', include('apps.clientes.urls', namespace='clientes')),
    path('ventas/', include('apps.ventas.urls', namespace='ventas')),
    path('favicon.ico', lambda r: redirect(static_url('img/marca/pwa/favicon.ico'), permanent=True)),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if getattr(settings, 'DEBUG_TOOLBAR', False):
        urlpatterns += [path('__debug__/', include('debug_toolbar.urls'))]

admin.site.site_header = 'Ordo — Administración'
admin.site.site_title = 'Ordo'
admin.site.index_title = 'Panel de plataforma'
