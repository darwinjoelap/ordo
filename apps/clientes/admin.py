from django.contrib import admin

from apps.core.admin import EmpresaModelAdmin

from .models import Cliente

admin.site.register(Cliente, EmpresaModelAdmin)
