from django.urls import path

from . import views

app_name = 'ventas'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nuevo/', views.nuevo, name='nuevo'),
    path('por-validar/', views.por_validar, name='por_validar'),
    path('buscar-clientes/', views.buscar_clientes, name='buscar_clientes'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/buscar-productos/', views.buscar_productos, name='buscar_productos'),
    path('<int:pk>/agregar/', views.agregar_item, name='agregar_item'),
    path('<int:pk>/actualizar/', views.actualizar, name='actualizar'),
    path('<int:pk>/accion/<slug:nombre>/', views.accion, name='accion'),
    path('<int:pk>/pago-entrega/', views.pago_entrega, name='pago_entrega'),
    path('<int:pk>/pdf/', views.pdf, name='pdf'),
]
