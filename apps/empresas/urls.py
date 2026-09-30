from django.urls import path

from . import views

app_name = 'empresas'

urlpatterns = [
    path('elegir/', views.seleccionar, name='seleccionar'),
    path('sin-empresa/', views.sin_empresa, name='sin_empresa'),
    path('mi-empresa/', views.mi_empresa, name='mi_empresa'),
    path('mi-empresa/vista-previa/', views.vista_previa, name='vista_previa'),
    path('mi-empresa/pdf-prueba/', views.pdf_prueba, name='pdf_prueba'),
]
