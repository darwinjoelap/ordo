from django.urls import path

from . import almacenes, views, views_importacion as imp

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
    path('importar/', imp.importar, name='importar'),
    path('importar/plantilla.xlsx', imp.plantilla, name='plantilla'),
    path('importar/<int:pk>/', imp.importar_revision, name='importar_revision'),
    path('importar/<int:pk>/confirmar/', imp.importar_confirmar, name='importar_confirmar'),
    path('exportar.xlsx', imp.exportar, name='exportar'),
    path('lista-precios/', views.lista_precios, name='lista_precios'),
    path('almacenes/', almacenes.lista, name='almacenes'),
    path('almacenes/nuevo/', almacenes.guardar, name='almacen_crear'),
    path('almacenes/<int:pk>/', almacenes.guardar, name='almacen_editar'),
    path('almacenes/<int:pk>/activar/', almacenes.activar, name='almacen_activar'),
    path('traslados/', almacenes.traslados, name='traslados'),
    path('traslados/nuevo/', almacenes.traslado_nuevo, name='traslado_nuevo'),
    path('traslados/<int:pk>/', almacenes.traslado, name='traslado'),
    path('traslados/<int:pk>/pdf/', almacenes.traslado_pdf, name='traslado_pdf'),
]
