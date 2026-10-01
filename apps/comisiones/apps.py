from django.apps import AppConfig


class ComisionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.comisiones'
    verbose_name = 'Comisiones'

    def ready(self):
        from apps.ventas.servicios import venta_devuelta, venta_validada

        from . import servicios
        venta_validada.connect(servicios.al_validar_venta, dispatch_uid='comisiones.al_validar_venta')
        venta_devuelta.connect(servicios.al_devolver_venta, dispatch_uid='comisiones.al_devolver_venta')
