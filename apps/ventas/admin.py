from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import Presupuesto


@admin.register(Presupuesto)
class PresupuestoAdmin(EmpresaModelAdmin):
    list_display = ['numero', 'empresa', 'cliente', 'vendedor', 'estado', 'total_usd', 'fecha']
    list_filter = ['empresa', 'estado']
    search_fields = ['numero', 'cliente__nombre']
    readonly_fields = [f.name for f in Presupuesto._meta.fields if f.name != 'notas']
