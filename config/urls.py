"""
Ordo — URLs raíz.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('', include('apps.core.urls', namespace='core')),
    path('cuenta/', include('apps.usuarios.urls', namespace='usuarios')),
    path('empresa/', include('apps.empresas.urls', namespace='empresas')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if getattr(settings, 'DEBUG_TOOLBAR', False):
        urlpatterns += [path('__debug__/', include('debug_toolbar.urls'))]

admin.site.site_header = 'Ordo — Administración'
admin.site.site_title = 'Ordo'
admin.site.index_title = 'Panel de plataforma'
