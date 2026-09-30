from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import OrdenCompra


@admin.register(OrdenCompra)
class OrdenCompraAdmin(EmpresaModelAdmin):
    list_display = ['numero', 'empresa', 'proveedor', 'estado', 'fecha']
    list_filter = ['empresa', 'estado']
    search_fields = ['numero']
