"""Subdominio por empresa (<slug>.BASE_DOMAIN), como Ordo Salud, con la ruta /<slug>/ como respaldo."""
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.core.subdominios import enlace
from apps.empresas.models import Empresa, Membresia, Rol

U = get_user_model()
CLAVE = 'clave-segura-123'
BASE = 'gestion.test'
HOSTS = ['.gestion.test', 'localhost', 'testserver']


@override_settings(BASE_DOMAIN=BASE, ALLOWED_HOSTS=HOSTS)
class SubdominioTests(TestCase):
    def setUp(self):
        self.alfa = Empresa.objects.create(nombre='Alfa', slug='alfa')
        self.beta = Empresa.objects.create(nombre='Beta', slug='beta')
        self.ana_a = U.objects.create_user('ana', CLAVE, empresa_cuenta=self.alfa)
        self.ana_b = U.objects.create_user('ana', CLAVE, empresa_cuenta=self.beta)      # mismo usuario, otra empresa
        Membresia.objects.create(usuario=self.ana_a, empresa=self.alfa, rol=Rol.DUENO)
        Membresia.objects.create(usuario=self.ana_b, empresa=self.beta, rol=Rol.DUENO)

    def en(self, sub):
        return Client(HTTP_HOST=f'{sub}.{BASE}')

    def test_la_raiz_del_subdominio_es_su_login(self):
        r = self.en('alfa').get('/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['empresa_marca'], self.alfa)
        self.assertEqual(self.en('alfa').get('/cuenta/entrar/').context['empresa_marca'], self.alfa)

    def test_entra_y_trabaja_sin_ruta(self):
        c = self.en('alfa')
        self.assertEqual(c.post('/', {'username': 'ana', 'password': CLAVE}).status_code, 302)
        r = c.get(reverse('clientes:lista'))
        self.assertEqual((r.status_code, r.wsgi_request.empresa), (200, self.alfa))

    def test_el_host_decide_la_empresa_del_usuario(self):
        c = self.en('beta')
        c.post('/', {'username': 'ana', 'password': CLAVE})
        self.assertEqual(c.get(reverse('clientes:lista')).wsgi_request.empresa, self.beta)

    def test_la_sesion_de_una_empresa_no_sirve_en_otra(self):
        c = self.en('alfa')
        c.post('/', {'username': 'ana', 'password': CLAVE})
        intruso = self.en('beta')
        intruso.cookies['sessionid'] = c.cookies['sessionid'].value
        self.assertEqual(intruso.get(reverse('clientes:lista')).status_code, 403)

    def test_inexistente_y_plataforma_bloqueada(self):
        self.assertEqual(self.en('nadie').get('/').status_code, 404)
        self.assertEqual(self.en('alfa').get('/plataforma/').status_code, 404)
        self.assertEqual(self.en('alfa').get('/admin/').status_code, 404)

    def test_admin_es_la_plataforma(self):
        self.assertRedirects(self.en('admin').get('/'), '/cuenta/entrar/?plataforma=1', fetch_redirect_response=False)
        U.objects.create_superuser('root@ordo.app', CLAVE)
        c = self.en('admin')
        self.assertEqual(c.post('/cuenta/entrar/?plataforma=1', {'username': 'root@ordo.app', 'password': CLAVE}).status_code, 302)
        r = c.get(reverse('plataforma:lista'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'http://alfa.gestion.test/')        # el enlace que se le da a la empresa

    def test_el_superusuario_da_soporte_en_el_subdominio(self):
        root = U.objects.create_superuser('root@ordo.app', CLAVE)
        c = self.en('alfa')
        c.force_login(root)
        r = c.get(reverse('clientes:lista'))
        self.assertEqual((r.status_code, r.wsgi_request.empresa), (200, self.alfa))

    def test_dominio_base_con_ruta_redirige_al_subdominio(self):
        r = Client(HTTP_HOST=BASE).get('/alfa/')
        self.assertRedirects(r, 'http://alfa.gestion.test/', fetch_redirect_response=False)

    def test_la_ruta_sigue_funcionando_en_otro_host(self):
        # la dirección de Railway sigue sirviendo como respaldo
        self.assertEqual(Client(HTTP_HOST='localhost').get('/alfa/').status_code, 200)

    def test_suspendida_en_su_subdominio(self):
        otro = next(v for v in Empresa.Estado.values if v != Empresa.Estado.ACTIVA)
        Empresa.objects.filter(pk=self.alfa.pk).update(estado=otro)
        c = self.en('alfa')
        c.force_login(self.ana_a)
        r = c.get(reverse('clientes:lista'))
        self.assertEqual(r.status_code, 403)
        self.assertTemplateUsed(r, 'empresas/suspendida.html')

    def test_enlace(self):
        self.assertEqual(enlace(RequestFactory().get('/', secure=True), 'agro'), 'https://agro.gestion.test/')


class SinDominioBaseTests(TestCase):
    def test_sin_base_domain_el_enlace_es_por_ruta(self):
        self.assertEqual(enlace(RequestFactory().get('/'), 'agro'), 'http://testserver/agro/')
