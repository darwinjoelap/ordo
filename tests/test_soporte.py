"""Cuenta de soporte Ordo: entra a cualquier empresa sin ser miembro y sin aparecer en su equipo."""
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.empresas import equipo
from apps.empresas.models import Empresa, Membresia, Rol

U = get_user_model()
CLAVE = 'clave-soporte-segura-1'
BASE = 'gestion.test'


def soporte(clave=CLAVE, **extra):
    u = U(username='soporte', first_name='Soporte', last_name='Ordo', es_soporte=True, **extra)
    u.set_password(clave)
    u.save()
    return u


class SoporteTests(TestCase):
    def setUp(self):
        self.alfa = Empresa.objects.create(nombre='Alfa', slug='alfa')
        self.ana = U.objects.create_user('ana', 'clave-ana-12345', empresa_cuenta=self.alfa)
        self.dueno = Membresia.objects.create(usuario=self.ana, empresa=self.alfa, rol=Rol.DUENO)
        self.soporte = soporte()

    def entrar_por_ruta(self, c=None):
        c = c or Client()
        r = c.post('/alfa/', {'username': 'soporte', 'password': CLAVE})
        self.assertEqual(r.status_code, 302)
        return c

    def test_entra_por_el_enlace_de_la_empresa_en_modo_soporte(self):
        c = self.entrar_por_ruta()
        r = c.get(reverse('clientes:lista'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.wsgi_request.empresa, self.alfa)
        self.assertTrue(r.wsgi_request.membresia.soporte)
        self.assertEqual(r.wsgi_request.membresia.rol, Rol.DUENO)
        self.assertContains(r, 'Modo soporte')
        self.assertContains(r, 'Cerrar sesión')

    def test_no_aparece_en_equipo_ni_cuenta_en_el_limite(self):
        c = self.entrar_por_ruta()
        r = c.get(reverse('empresas:equipo'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self.soporte, [m.usuario for m in r.context['miembros']])
        self.assertFalse(Membresia.objects.filter(usuario=self.soporte).exists())
        self.assertEqual(self.alfa.usuarios_activos(), 1)

    def test_no_entra_al_panel_de_plataforma_ni_admin(self):
        c = self.entrar_por_ruta()
        self.assertEqual(c.get(reverse('plataforma:lista')).status_code, 403)
        self.assertNotEqual(c.get('/admin/').status_code, 200)

    def test_clave_incorrecta_o_cuenta_desactivada(self):
        r = Client().post('/alfa/', {'username': 'soporte', 'password': 'otra-cosa-123'})
        self.assertEqual(r.status_code, 200)
        self.soporte.is_active = False
        self.soporte.save()
        r = Client().post('/alfa/', {'username': 'soporte', 'password': CLAVE})
        self.assertEqual(r.status_code, 200)

    def test_una_cuenta_normal_de_plataforma_no_entra_a_empresas(self):
        U.objects.create_user('pepe', CLAVE)            # sin empresa, sin soporte
        r = Client().post('/alfa/', {'username': 'pepe', 'password': CLAVE})
        self.assertEqual(r.status_code, 200)

    def test_el_nombre_soporte_esta_reservado_en_equipo(self):
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.agregar(self.alfa, self.dueno, 'soporte', 'X', 'Y', Rol.VENDEDOR)

    def test_entra_a_empresa_suspendida(self):
        Empresa.objects.filter(pk=self.alfa.pk).update(estado=Empresa.Estado.SUSPENDIDA)
        self.assertEqual(Client().get('/alfa/').status_code, 403)          # sin ?soporte=1: aviso de suspendida
        c = Client()
        self.assertEqual(c.post('/alfa/?soporte=1', {'username': 'soporte', 'password': CLAVE}).status_code, 302)
        self.assertEqual(c.get(reverse('clientes:lista')).status_code, 200)
        # un usuario de la empresa no pasa aunque use ?soporte=1
        c2 = Client()
        c2.post('/alfa/?soporte=1', {'username': 'ana', 'password': 'clave-ana-12345'})
        self.assertNotEqual(c2.get(reverse('clientes:lista')).status_code, 200)

    @override_settings(BASE_DOMAIN=BASE, ALLOWED_HOSTS=['.gestion.test', 'testserver'])
    def test_entra_por_subdominio(self):
        c = Client(HTTP_HOST=f'alfa.{BASE}')
        self.assertEqual(c.post('/', {'username': 'soporte', 'password': CLAVE}).status_code, 302)
        r = c.get(reverse('clientes:lista'))
        self.assertEqual((r.status_code, r.wsgi_request.empresa), (200, self.alfa))
        self.assertTrue(r.wsgi_request.membresia.soporte)

    @override_settings(BASE_DOMAIN=BASE, ALLOWED_HOSTS=['.gestion.test', 'testserver'])
    def test_superusuario_desde_el_panel_va_al_subdominio(self):
        root = U.objects.create_superuser('root', CLAVE)
        c = Client(HTTP_HOST=f'admin.{BASE}')
        c.force_login(root)
        r = c.post(reverse('plataforma:entrar', args=[self.alfa.pk]))
        self.assertRedirects(r, f'http://alfa.{BASE}/?soporte=1', fetch_redirect_response=False)
        # y en el subdominio el superusuario entra con su misma cuenta
        c2 = Client(HTTP_HOST=f'alfa.{BASE}')
        self.assertEqual(c2.post('/', {'username': 'root', 'password': CLAVE}).status_code, 302)
        self.assertTrue(c2.get(reverse('clientes:lista')).wsgi_request.membresia.soporte)


class ComandoCrearSoporteTests(TestCase):
    def correr(self, *claves, **opts):
        with mock.patch('getpass.getpass', side_effect=list(claves)):
            call_command('crear_soporte', stdout=StringIO(), **opts)

    def test_crea_y_actualiza(self):
        self.correr(CLAVE, CLAVE)
        u = U.objects.get(username='soporte', empresa_cuenta__isnull=True)
        self.assertTrue(u.es_soporte and u.check_password(CLAVE))
        self.assertFalse(u.is_superuser or u.is_staff)
        self.correr('otra-clave-segura-9', 'otra-clave-segura-9')
        u.refresh_from_db()
        self.assertTrue(u.check_password('otra-clave-segura-9'))

    def test_rechaza_claves_distintas_o_debiles(self):
        with self.assertRaises(CommandError):
            self.correr(CLAVE, 'distinta-123456')
        with self.assertRaises(CommandError):
            self.correr('12345678', '12345678')
        self.assertFalse(U.objects.filter(username='soporte').exists())

    def test_desactivar(self):
        self.correr(CLAVE, CLAVE)
        call_command('crear_soporte', desactivar=True, stdout=StringIO())
        self.assertFalse(U.objects.get(username='soporte').is_active)
