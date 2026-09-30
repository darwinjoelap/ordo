from django.urls import path

from . import views

app_name = 'compras'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nueva/', views.crear, name='crear'),
    path('pedido/', views.panel_pedido, name='panel_pedido'),
    path('pedido/crear/', views.crear_desde_panel, name='crear_desde_panel'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/agregar/', views.agregar_item, name='agregar_item'),
    path('<int:pk>/actualizar/', views.actualizar_items, name='actualizar_items'),
    path('<int:pk>/estado/', views.cambiar_estado, name='cambiar_estado'),
    path('<int:pk>/recibir/', views.recibir, name='recibir'),
    path('<int:pk>/pdf/', views.pdf, name='pdf'),
]
