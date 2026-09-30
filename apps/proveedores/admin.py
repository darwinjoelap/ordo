from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import Proveedor


@admin.register(Proveedor)
class ProveedorAdmin(EmpresaModelAdmin):
    list_display = ['nombre', 'empresa', 'rif', 'telefono', 'activo']
    search_fields = ['nombre', 'rif']
