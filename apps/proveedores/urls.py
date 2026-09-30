from django.urls import path

from . import views

app_name = 'proveedores'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nuevo/', views.formulario, name='crear'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/editar/', views.formulario, name='editar'),
]
