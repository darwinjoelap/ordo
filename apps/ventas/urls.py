from django.urls import path

from . import reportes, views, views_devoluciones

app_name = 'ventas'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nuevo/', views.nuevo, name='nuevo'),
    path('por-validar/', views.por_validar, name='por_validar'),
    path('reportes/', reportes.analitica, name='reportes'),
    path('reportes/facturacion/', reportes.facturacion, name='reporte_facturacion'),
    path('reportes/apartados/', reportes.apartados, name='reporte_apartados'),
    path('devoluciones/', views_devoluciones.lista, name='devoluciones'),
    path('devoluciones/<int:pk>/', views_devoluciones.detalle, name='devolucion'),
    path('devoluciones/<int:pk>/pdf/', views_devoluciones.pdf, name='devolucion_pdf'),
    path('<int:pk>/devolver/', views_devoluciones.devolver, name='devolver'),
    path('buscar-clientes/', views.buscar_clientes, name='buscar_clientes'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/buscar-productos/', views.buscar_productos, name='buscar_productos'),
    path('<int:pk>/agregar/', views.agregar_item, name='agregar_item'),
    path('<int:pk>/actualizar/', views.actualizar, name='actualizar'),
    path('<int:pk>/accion/<slug:nombre>/', views.accion, name='accion'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('<int:pk>/pago-entrega/', views.pago_entrega, name='pago_entrega'),
    path('<int:pk>/pdf/', views.pdf, name='pdf'),
    path('<int:pk>/despacho/', views.despacho, name='despacho'),
    path('<int:pk>/despacho/pdf/', views.despacho_pdf_vista, name='despacho_pdf'),
    path('<int:pk>/facturacion/', views.facturacion, name='facturacion'),
]
