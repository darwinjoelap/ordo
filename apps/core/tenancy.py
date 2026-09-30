"""
Multiempresa: empresa activa por request y modelo base con aislamiento.

Regla de oro: todo modelo de negocio hereda de EmpresaModel.
  - `Modelo.objects` solo ve filas de la empresa activa.
  - Sin empresa activa, `Modelo.objects` no devuelve NADA (falla cerrado).
  - `Modelo.todos` ve todo: solo para comandos internos, admin y migraciones.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ImproperlyConfigured
from django.db import models

_empresa_actual = ContextVar('empresa_actual', default=None)


def empresa_actual():
    """Empresa activa del request/contexto en curso (o None)."""
    return _empresa_actual.get()


def fijar_empresa(empresa):
    """Fija la empresa activa y devuelve el token para restaurar."""
    return _empresa_actual.set(empresa)


def restaurar_empresa(token):
    _empresa_actual.reset(token)


@contextmanager
def usando_empresa(empresa):
    """Para comandos y tests: `with usando_empresa(e): Producto.objects...`"""
    token = fijar_empresa(empresa)
    try:
        yield empresa
    finally:
        restaurar_empresa(token)


class EmpresaQuerySet(models.QuerySet):
    pass


class EmpresaManager(models.Manager.from_queryset(EmpresaQuerySet)):
    def get_queryset(self):
        qs = super().get_queryset()
        empresa = empresa_actual()
        if empresa is None:
            return qs.none()
        return qs.filter(empresa=empresa)


class EmpresaModel(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.PROTECT, editable=False,
        related_name='+', verbose_name='Empresa',
    )

    objects = EmpresaManager()
    todos = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = 'todos'

    def save(self, *args, **kwargs):
        if self.empresa_id is None:
            empresa = empresa_actual()
            if empresa is None:
                raise ImproperlyConfigured(
                    f'{type(self).__name__} necesita empresa: guarda dentro de un request '
                    'con empresa activa o usa `usando_empresa(...)`.'
                )
            self.empresa = empresa
        super().save(*args, **kwargs)
