from django.contrib import admin


class EmpresaModelAdmin(admin.ModelAdmin):
    """Admin de plataforma: ve todas las empresas (usa el manager `todos`)."""
    list_filter = ['empresa']

    def get_queryset(self, request):
        return self.model.todos.select_related('empresa')

    def has_add_permission(self, request):
        # Los datos de negocio se crean desde la app, dentro de su empresa
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from .tenancy import EmpresaModel
        if issubclass(db_field.related_model, EmpresaModel):
            kwargs['queryset'] = db_field.related_model.todos.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
