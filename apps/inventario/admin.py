from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import Categoria, Lote, Marca, MovimientoInventario, Producto, Subcategoria, Unidad


@admin.register(Producto)
class ProductoAdmin(EmpresaModelAdmin):
    list_display = ['codigo', 'nombre', 'empresa', 'categoria', 'precio_venta_usd', 'activo']
    search_fields = ['codigo', 'nombre']


@admin.register(Lote)
class LoteAdmin(EmpresaModelAdmin):
    list_display = ['producto', 'numero_lote', 'fecha_vencimiento', 'cantidad_actual', 'cantidad_apartada', 'empresa']
    readonly_fields = ['cantidad_actual', 'cantidad_apartada']   # solo se mueven con servicios.py


@admin.register(MovimientoInventario)
class MovimientoAdmin(EmpresaModelAdmin):
    list_display = ['fecha', 'tipo', 'cantidad', 'lote', 'usuario', 'empresa']
    list_filter = ['empresa', 'tipo']

    def has_change_permission(self, request, obj=None):
        return False


for modelo in (Categoria, Subcategoria, Marca, Unidad):
    admin.site.register(modelo, EmpresaModelAdmin)
