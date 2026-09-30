"""
Empresas (clientes de Ordo), membresías usuario↔empresa y perfil de marca.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Empresa(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = 'ACTIVA', 'Activa'
        SUSPENDIDA = 'SUSPENDIDA', 'Suspendida'

    class Plan(models.TextChoices):
        PRUEBA = 'PRUEBA', 'Prueba'
        BASICO = 'BASICO', 'Básico'
        PRO = 'PRO', 'Pro'

    nombre = models.CharField('Nombre', max_length=150)
    slug = models.SlugField('Identificador', max_length=60, unique=True,
                            help_text='Se usa en rutas internas y carpetas de Cloudinary.')
    estado = models.CharField('Estado', max_length=12, choices=Estado.choices, default=Estado.ACTIVA)
    plan = models.CharField('Plan', max_length=10, choices=Plan.choices, default=Plan.PRUEBA)
    activa_hasta = models.DateField('Activa hasta', null=True, blank=True,
                                    help_text='Vacío = sin vencimiento.')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre)[:50] or 'empresa'
            slug, n = base, 2
            while Empresa.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def esta_activa(self):
        if self.estado != self.Estado.ACTIVA:
            return False
        if self.activa_hasta and self.activa_hasta < timezone.localdate():
            return False
        return True


class Rol(models.TextChoices):
    DUENO = 'DUENO', 'Dueño'
    ADMIN = 'ADMIN', 'Administrador'
    ALMACEN = 'ALMACEN', 'Almacén'
    VENDEDOR = 'VENDEDOR', 'Vendedor'


class Membresia(models.Model):
    """Un usuario pertenece a una empresa con un rol."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='membresias', verbose_name='Usuario')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE,
                                related_name='membresias', verbose_name='Empresa')
    rol = models.CharField('Rol', max_length=10, choices=Rol.choices, default=Rol.VENDEDOR)
    activa = models.BooleanField('Activa', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Membresía'
        verbose_name_plural = 'Membresías'
        ordering = ['empresa__nombre', 'usuario__email']
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'empresa'], name='membresia_unica'),
        ]

    def __str__(self):
        return f'{self.usuario} — {self.empresa} ({self.get_rol_display()})'


# ── Perfil de marca y datos de la empresa ────────────────────────────────────

def _ruta_logo(instancia, archivo):
    return f'ordo/{instancia.empresa.slug}/logo/{archivo}'


def _ruta_firma(instancia, archivo):
    return f'ordo/{instancia.empresa.slug}/firma/{archivo}'


color_hex = RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Usa un color en formato #RRGGBB.')


class PerfilEmpresa(models.Model):
    class ModoPrecio(models.TextChoices):
        FIJO = 'FIJO', 'Fijo: lo define el administrador'
        LIBRE = 'LIBRE', 'Libre: lo define el vendedor'
        RANGO = 'RANGO', 'Rango: el vendedor elige dentro de un margen'

    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE, related_name='perfil')

    # Identidad
    nombre_comercial = models.CharField('Nombre comercial', max_length=150)
    razon_social = models.CharField('Razón social', max_length=200, blank=True)
    rif = models.CharField('RIF', max_length=20, blank=True)
    logo = models.ImageField('Logo', upload_to=_ruta_logo, blank=True,
                             help_text='PNG o JPG, máximo 2 MB. Se usa en la app y en los documentos.')
    logo_pdf = models.ImageField('Logo para PDF', upload_to=_ruta_logo, blank=True, editable=False)
    color_principal = models.CharField('Color principal', max_length=7, default='#053D74',
                                       validators=[color_hex])

    # Contacto
    direccion_fiscal = models.TextField('Dirección fiscal', blank=True)
    telefono = models.CharField('Teléfono', max_length=40, blank=True)
    telefono_2 = models.CharField('Teléfono 2', max_length=40, blank=True)
    email = models.EmailField('Correo', blank=True)
    sitio_web = models.CharField('Sitio web', max_length=120, blank=True)
    instagram = models.CharField('Instagram', max_length=60, blank=True)
    whatsapp = models.CharField('WhatsApp', max_length=40, blank=True)

    # Documentos
    prefijo_numeracion = models.CharField('Prefijo de numeración', max_length=6, blank=True,
                                          help_text='Ej: BL → BL202600001')
    condiciones_presupuesto = models.TextField(
        'Condiciones del presupuesto', blank=True,
        default='Precios sujetos a la tasa del día de emisión. Validez según fecha indicada.')
    pie_documentos = models.CharField('Pie de página de documentos', max_length=250, blank=True)
    datos_bancarios = models.TextField('Datos bancarios / pago móvil', blank=True)
    firma = models.ImageField('Firma o sello', upload_to=_ruta_firma, blank=True,
                              help_text='Opcional. PNG con fondo transparente.')

    # Comercial
    iva_porcentaje = models.DecimalField('IVA por defecto (%)', max_digits=5, decimal_places=2,
                                         default=Decimal('16.00'),
                                         validators=[MinValueValidator(0), MaxValueValidator(100)])
    dias_validez_presupuesto = models.PositiveSmallIntegerField('Validez del presupuesto (días)', default=7)
    dias_apartado = models.PositiveSmallIntegerField('Días de apartado', default=15)
    modo_precio = models.CharField('Modo de precios', max_length=6, choices=ModoPrecio.choices,
                                   default=ModoPrecio.RANGO)
    margen_minimo_pct = models.DecimalField('Margen mínimo sobre costo (%)', max_digits=6, decimal_places=2,
                                            default=Decimal('0.00'), validators=[MinValueValidator(0)])
    margen_maximo_pct = models.DecimalField('Margen máximo sobre costo (%)', max_digits=6, decimal_places=2,
                                            null=True, blank=True, validators=[MinValueValidator(0)],
                                            help_text='Vacío = sin tope.')
    requiere_validacion = models.BooleanField('Las ventas requieren validación', default=True)
    vendedores_ven_todos_los_clientes = models.BooleanField(
        'Los vendedores ven todos los clientes', default=False,
        help_text='Si está apagado, cada vendedor ve solo los clientes que creó o tiene asignados.')
    comision_requiere_pago = models.BooleanField('La comisión exige venta cobrada', default=False)

    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de empresa'
        verbose_name_plural = 'Perfiles de empresa'

    def __str__(self):
        return f'Perfil — {self.nombre_comercial}'

    @property
    def logo_para_pdf(self):
        """Archivo de logo que deben usar los PDF (versión optimizada si existe)."""
        return self.logo_pdf or self.logo or None
