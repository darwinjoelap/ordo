from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salud/', views.salud, name='salud'),
]
