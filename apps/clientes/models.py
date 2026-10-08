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


class ImportacionClientes(EmpresaModel):
    """Archivo subido para importar clientes: guarda el contenido entre «revisar» y «confirmar», y deja historial."""

    class Estado(models.TextChoices):
        CON_ERRORES = 'ERRORES', 'Con errores'
        VALIDADA = 'VALIDADA', 'Lista para importar'
        APLICADA = 'APLICADA', 'Importada'

    nombre_archivo = models.CharField('Archivo', max_length=200)
    contenido = models.BinaryField('Contenido')
    estado = models.CharField('Estado', max_length=10, choices=Estado.choices)
    resumen = models.JSONField('Resumen', default=dict)
    errores = models.JSONField('Errores', default=list)
    avisos = models.JSONField('Avisos', default=list)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    aplicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Importación de clientes'
        verbose_name_plural = 'Importaciones de clientes'
        ordering = ['-creado_en']
        base_manager_name = 'todos'

    def __str__(self):
        return f'{self.nombre_archivo} ({self.get_estado_display()})'
