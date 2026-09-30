from django.urls import path

from . import views

app_name = 'comisiones'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('mias/', views.detalle_vendedor, name='detalle_vendedor'),
    path('vendedor/<int:vendedor_id>/', views.detalle_vendedor, name='vendedor'),
    path('configuracion/', views.configuracion, name='configuracion'),
    path('liquidar/<int:vendedor_id>/', views.liquidar, name='liquidar'),
    path('liquidaciones/<int:pk>/', views.liquidacion, name='liquidacion'),
    path('liquidaciones/<int:pk>/pdf/', views.liquidacion_pdf_vista, name='liquidacion_pdf'),
]
