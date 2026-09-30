from django.urls import path

from . import views, views_equipo

app_name = 'empresas'

urlpatterns = [
    path('elegir/', views.seleccionar, name='seleccionar'),
    path('sin-empresa/', views.sin_empresa, name='sin_empresa'),
    path('mi-empresa/', views.mi_empresa, name='mi_empresa'),
    path('mi-empresa/vista-previa/', views.vista_previa, name='vista_previa'),
    path('mi-empresa/pdf-prueba/', views.pdf_prueba, name='pdf_prueba'),
    path('equipo/', views_equipo.lista, name='equipo'),
    path('equipo/agregar/', views_equipo.agregar, name='equipo_agregar'),
    path('equipo/<int:pk>/', views_equipo.actualizar, name='equipo_actualizar'),
    path('equipo/<int:pk>/clave/', views_equipo.restablecer_clave, name='equipo_clave'),
]
