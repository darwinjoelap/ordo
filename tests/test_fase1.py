"""Pruebas de la Fase 1: acceso, healthcheck y usuario por correo."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UsuarioTests(TestCase):
    def test_crear_usuario_con_correo_normalizado(self):
        u = get_user_model().objects.create_user('Ana@Empresa.COM', 'clave-segura-123')
        self.assertEqual(u.email, 'ana@empresa.com')
        self.assertTrue(u.check_password('clave-segura-123'))
        self.assertFalse(u.is_staff)

    def test_crear_superusuario(self):
        u = get_user_model().objects.create_superuser('admin@ordo.app', 'clave-segura-123')
        self.assertTrue(u.is_staff and u.is_superuser)


class AccesoTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            'vendedor@empresa.com', 'clave-segura-123', first_name='Luis'
        )

    def test_inicio_exige_login(self):
        r = self.client.get(reverse('core:inicio'))
        self.assertRedirects(r, f"{reverse('usuarios:login')}?next=/")

    def test_login_con_correo_en_mayusculas(self):
        r = self.client.post(reverse('usuarios:login'), {
            'username': 'VENDEDOR@empresa.com', 'password': 'clave-segura-123',
        })
        self.assertRedirects(r, reverse('core:inicio'))

    def test_login_incorrecto(self):
        r = self.client.post(reverse('usuarios:login'), {
            'username': 'vendedor@empresa.com', 'password': 'mala',
        })
        self.assertContains(r, 'Correo o contraseña incorrectos')

    def test_inicio_con_sesion(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse('core:inicio'))
        self.assertContains(r, 'Hola, Luis')

    def test_logout_por_post(self):
        self.client.force_login(self.usuario)
        r = self.client.post(reverse('usuarios:logout'))
        self.assertRedirects(r, reverse('usuarios:login'))


class SaludTests(TestCase):
    def test_healthcheck(self):
        r = self.client.get(reverse('core:salud'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'estado': 'ok'})
