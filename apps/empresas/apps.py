from django.apps import AppConfig


class EmpresasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.empresas'
    verbose_name = 'Empresas'

    def ready(self):
        from . import signals  # noqa: F401
