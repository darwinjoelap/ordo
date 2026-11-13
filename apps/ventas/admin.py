from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import Devolucion, Presupuesto, UsoIA


@admin.register(Presupuesto)
class PresupuestoAdmin(EmpresaModelAdmin):
    list_display = ['numero', 'empresa', 'cliente', 'vendedor', 'estado', 'total_usd', 'fecha']
    list_filter = ['empresa', 'estado']
    search_fields = ['numero', 'cliente__nombre']
    readonly_fields = [f.name for f in Presupuesto._meta.fields if f.name != 'notas']


@admin.register(Devolucion)
class DevolucionAdmin(EmpresaModelAdmin):
    """Solo consulta: las devoluciones se registran desde la app (ajustan stock y comisiones)."""
    list_display = ['numero', 'empresa', 'presupuesto', 'fecha', 'total_usd', 'reembolsado']
    list_filter = ['empresa', 'reembolsado']
    search_fields = ['numero', 'presupuesto__numero']
    readonly_fields = [f.name for f in Devolucion._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(UsoIA)
class UsoIAAdmin(EmpresaModelAdmin):
    """Uso de «Cargar con IA» por empresa (costo estimado). Solo consulta."""
    list_display = ['creado_en', 'empresa', 'usuario', 'origen', 'archivos', 'lineas', 'sugeridas', 'agregadas', 'ok',
                    'costo_usd', 'modelo']
    list_filter = ['empresa', 'ok', 'origen']
    date_hierarchy = 'creado_en'
    readonly_fields = [f.name for f in UsoIA._meta.fields]

    def has_add_permission(self, request):
        return False
