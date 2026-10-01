from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    ordering = ['empresa_cuenta', 'username']
    list_display = ['username', 'empresa_cuenta', 'first_name', 'last_name', 'is_active', 'is_superuser', 'last_login']
    list_filter = ['is_superuser', 'is_active', 'empresa_cuenta']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    fieldsets = (
        (None, {'fields': ('username', 'empresa_cuenta', 'password')}),
        ('Datos personales', {'fields': ('first_name', 'last_name', 'email', 'telefono')}),
        ('Permisos', {'fields': ('is_active', 'debe_cambiar_clave', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('username', 'empresa_cuenta', 'password1', 'password2')}),
    )
