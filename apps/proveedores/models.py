from django.db import models

from apps.core.tenancy import EmpresaModel


class Proveedor(EmpresaModel):
    nombre = models.CharField('Nombre', max_length=200)
    rif = models.CharField('RIF', max_length=20, blank=True)
    contacto = models.CharField('Persona de contacto', max_length=100, blank=True)
    telefono = models.CharField('Teléfono', max_length=50, blank=True)
    email = models.EmailField('Correo', blank=True)
    direccion = models.TextField('Dirección', blank=True)
    notas = models.TextField('Notas', blank=True)
    activo = models.BooleanField('Activo', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'
        ordering = ['nombre']
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nombre'], name='proveedor_nombre_unico_por_empresa'),
        ]

    def __str__(self):
        return self.nombre
