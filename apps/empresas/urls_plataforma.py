from django.urls import path

from . import views_plataforma as v

app_name = 'plataforma'

urlpatterns = [
    path('', v.lista, name='lista'),
    path('nueva/', v.nueva, name='nueva'),
    path('<int:pk>/', v.editar, name='editar'),
]
