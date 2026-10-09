from django.urls import path

from . import views, views_importacion as imp

app_name = 'clientes'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nuevo/', views.formulario, name='crear'),
    path('importar/', imp.importar, name='importar'),
    path('importar/plantilla.xlsx', imp.plantilla, name='plantilla'),
    path('exportar.xlsx', imp.exportar, name='exportar'),
    path('importar/<int:pk>/', imp.importar_revision, name='importar_revision'),
    path('importar/<int:pk>/confirmar/', imp.importar_confirmar, name='importar_confirmar'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/editar/', views.formulario, name='editar'),
    path('<int:pk>/estado-cuenta.pdf', views.estado_cuenta_pdf, name='estado_cuenta_pdf'),
    path('<int:pk>/estado-cuenta.xlsx', views.estado_cuenta_excel, name='estado_cuenta_excel'),
]
