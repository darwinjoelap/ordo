from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'usuarios'

urlpatterns = [
    path('entrar/', views.EntrarPrincipal.as_view(), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),
    path('perfil/', views.perfil, name='perfil'),
]
