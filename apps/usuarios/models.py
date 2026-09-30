"""
Usuario de Ordo.

- Se inicia sesión con correo, no con nombre de usuario.
- El ROL no vive aquí: vive en la membresía usuario↔empresa (Fase 2),
  porque una misma persona puede ser Vendedor en una empresa y Dueño en otra.
"""
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _crear(self, email, password, **extra):
        if not email:
            raise ValueError('El correo es obligatorio.')
        email = self.normalize_email(email).lower()
        usuario = self.model(email=email, **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._crear(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        if not extra['is_staff'] or not extra['is_superuser']:
            raise ValueError('El superusuario necesita is_staff e is_superuser.')
        return self._crear(email, password, **extra)


class Usuario(AbstractUser):
    username = None
    email = models.EmailField('Correo', unique=True)
    telefono = models.CharField('Teléfono', max_length=30, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UsuarioManager()

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
        ordering = ['first_name', 'last_name', 'email']

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def iniciales(self):
        partes = [self.first_name[:1], self.last_name[:1]]
        texto = ''.join(p for p in partes if p) or self.email[:1]
        return texto.upper()
