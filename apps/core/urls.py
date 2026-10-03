from django.urls import path

from . import consulta, pwa, views

app_name = 'core'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salud/', views.salud, name='salud'),
    path('manifest.webmanifest', pwa.manifest, name='manifest'),
    path('sw.js', pwa.service_worker, name='service_worker'),
    path('offline/', pwa.offline, name='offline'),
    path('consulta/', consulta.consulta, name='consulta'),
    path('consulta/datos.json', consulta.consulta_datos, name='consulta_datos'),
    path('visor/', pwa.visor_pdf, name='visor_pdf'),
    path('instalar/', pwa.instalar, name='instalar'),
]
