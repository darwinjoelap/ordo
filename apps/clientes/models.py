from django.conf import settings
from django.db import models

from apps.core.tenancy import EmpresaModel


class Cliente(EmpresaModel):
    nombre = models.CharField('Nombre o razón social', max_length=200)
    rif = models.CharField('RIF / Cédula', max_length=20, blank=True)
    contacto = models.CharField('Persona de contacto', max_length=100, blank=True)
    telefono = models.CharField('Teléfono', max_length=50, blank=True)
    email = models.EmailField('Correo', blank=True)
    direccion = models.TextField('Dirección', blank=True)
    notas = models.TextField('Notas', blank=True)
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='+', verbose_name='Vendedor asignado')
    activo = models.BooleanField('Activo', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nombre']
        base_manager_name = 'todos'
        indexes = [models.Index(fields=['empresa', 'vendedor'], name='cliente_empresa_vendedor')]

    def __str__(self):
        return self.nombre
