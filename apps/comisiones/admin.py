from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import AjusteComision, Comision, Liquidacion, PorcentajeCategoria, PorcentajeVendedor


@admin.register(Comision)
class ComisionAdmin(EmpresaModelAdmin):
    list_display = ('presupuesto', 'vendedor', 'fecha', 'base_usd', 'monto_usd', 'liquidacion', 'empresa')
    list_filter = ('empresa',)
    readonly_fields = [f.name for f in Comision._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Liquidacion)
class LiquidacionAdmin(EmpresaModelAdmin):
    list_display = ('numero', 'vendedor', 'hasta', 'total_usd', 'pagada', 'anulada', 'empresa')
    list_filter = ('empresa', 'pagada', 'anulada')

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(PorcentajeVendedor, EmpresaModelAdmin)
admin.site.register(PorcentajeCategoria, EmpresaModelAdmin)


@admin.register(AjusteComision)
class AjusteComisionAdmin(EmpresaModelAdmin):
    list_display = ('devolucion', 'vendedor', 'fecha', 'monto_usd', 'liquidacion', 'empresa')
    list_filter = ('empresa',)
    readonly_fields = [f.name for f in AjusteComision._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
