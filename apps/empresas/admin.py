from django.contrib import admin

from .models import Empresa, Membresia, PerfilEmpresa


class MembresiaInline(admin.TabularInline):
    model = Membresia
    extra = 1
    autocomplete_fields = ['usuario']


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'estado', 'plan', 'activa_hasta', 'creado_en']
    list_filter = ['estado', 'plan']
    search_fields = ['nombre', 'slug']
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [MembresiaInline]


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'empresa', 'rol', 'activa']
    list_filter = ['rol', 'activa', 'empresa']
    search_fields = ['usuario__username', 'empresa__nombre']
    autocomplete_fields = ['usuario', 'empresa']


@admin.register(PerfilEmpresa)
class PerfilEmpresaAdmin(admin.ModelAdmin):
    list_display = ['nombre_comercial', 'empresa', 'rif', 'modo_precio', 'actualizado_en']
    search_fields = ['nombre_comercial', 'rif', 'empresa__nombre']
    readonly_fields = ['logo_pdf']
