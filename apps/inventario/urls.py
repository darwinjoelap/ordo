from django.urls import path

from . import views

app_name = 'inventario'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('productos/nuevo/', views.producto_form, name='producto_crear'),
    path('productos/<int:pk>/', views.detalle, name='detalle'),
    path('productos/<int:pk>/editar/', views.producto_form, name='producto_editar'),
    path('ingreso/', views.ingreso, name='ingreso'),
    path('ajuste/', views.ajuste, name='ajuste'),
    path('buscar/', views.buscar_productos, name='buscar'),
    path('catalogo/subcategorias-opciones/', views.subcategorias_opciones, name='subcategorias_opciones'),
    path('catalogo/<slug:tipo>/', views.catalogo, name='catalogo'),
]
