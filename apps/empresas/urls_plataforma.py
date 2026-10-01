from django.urls import path

from . import views_plataforma as v

app_name = 'plataforma'

urlpatterns = [
    path('', v.lista, name='lista'),
    path('nueva/', v.nueva, name='nueva'),
    path('<int:pk>/', v.editar, name='editar'),
    path('<int:pk>/entrar/', v.entrar, name='entrar'),
    path('salir/', v.salir, name='salir'),
    path('tasas/', v.tasas, name='tasas'),
    path('<int:pk>/migrar/', v.migrar, name='migrar'),
]
