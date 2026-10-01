from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from . import servicios
from .models import TasaCambio, TasaEmpresa


@admin.register(TasaCambio)
class TasaCambioAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'bs_por_usd', 'fuente', 'registrada_por', 'actualizado_en']
    readonly_fields = ['registrada_por']

    def save_model(self, request, obj, form, change):
        if not change or 'bs_por_usd' in form.changed_data:
            obj.fuente = TasaCambio.Fuente.MANUAL
            obj.registrada_por = request.user
        super().save_model(request, obj, form, change)
        servicios.limpiar_cache()


@admin.register(TasaEmpresa)
class TasaEmpresaAdmin(EmpresaModelAdmin):
    list_display = ['fecha', 'empresa', 'bs_por_usd', 'registrada_por', 'actualizado_en']
    list_filter = ['empresa']
