from django.urls import path

from . import views

app_name = 'finanzas'

urlpatterns = [
    path('equilibrio/', views.equilibrio, name='equilibrio'),
    path('equilibrio/costo/', views.costo_agregar, name='costo_agregar'),
    path('equilibrio/costo/<int:pk>/quitar/', views.costo_quitar, name='costo_quitar'),
    path('equilibrio/deduccion/', views.deduccion_agregar, name='deduccion_agregar'),
    path('equilibrio/deduccion/<int:pk>/quitar/', views.deduccion_quitar, name='deduccion_quitar'),
]
