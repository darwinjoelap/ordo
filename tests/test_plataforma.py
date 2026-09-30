"""
Panel de plataforma (superusuario): alta de empresas, enlace propio, suspensión, plan, límite de usuarios.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.empresas import equipo
from apps.empresas.models import Empresa, Membresia, Rol

U = get_user_model()
HOY = timezone.localdate()


class Base(TestCase):
    def setUp(self):
        self.root = U.objects.create_superuser('root@ordo.app', 'clave-segura-123')
        self.empresa = Empresa.objects.create(nombre='Alfa', slug='alfa')
        self.dueno = U.objects.create_user('d@alfa.com', 'clave-segura-123')
        self.m_dueno = Membresia.objects.create(usuario=self.dueno, empresa=self.empresa, rol=Rol.DUENO)


class PanelTests(Base):
    def datos(self, **extra):
        d = {'nombre_comercial': 'Biolife de Venezuela', 'razon_social': 'Biolife de Venezuela, C.A.',
             'rif': 'j-12345678-9', 'slug': 'biolife', 'plan': 'PRO', 'activa_hasta': '', 'limite_usuarios': '5',
             'notas': '', 'email_dueno': 'darwin@biolife.com', 'nombre_dueno': 'Darwin', 'apellido_dueno': 'P'}
        d.update(extra)
        return d

    def test_solo_superusuario(self):
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('plataforma:lista')).status_code, 403)

    def test_superusuario_sin_empresa_entra_al_panel(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse('plataforma:lista')), 'Alfa')

    def test_crear_empresa_con_dueno_nuevo(self):
        self.client.force_login(self.root)
        r = self.client.post(reverse('plataforma:nueva'), self.datos())
        self.assertContains(r, 'Ordo-')
        e = Empresa.objects.get(slug='biolife')
        self.assertEqual(e.perfil.razon_social, 'Biolife de Venezuela, C.A.')
        self.assertEqual(e.perfil.rif, 'J-12345678-9')
        self.assertEqual(e.limite_usuarios, 5)
        m = Membresia.objects.get(empresa=e)
        self.assertEqual((m.rol, m.usuario.email, m.usuario.debe_cambiar_clave), (Rol.DUENO, 'darwin@biolife.com', True))

    def test_enlace_reservado_repetido_o_invalido(self):
        self.client.force_login(self.root)
        for slug in ('ventas', 'alfa', 'Con Espacios', 'ab'):
            r = self.client.post(reverse('plataforma:nueva'), self.datos(slug=slug))
            self.assertEqual(r.status_code, 200)
            self.assertFalse(Empresa.objects.filter(nombre='Biolife de Venezuela').exists(), slug)

    def test_editar_y_suspender(self):
        self.client.force_login(self.root)
        self.client.post(reverse('plataforma:editar', args=[self.empresa.pk]), {
            'nombre_comercial': 'Alfa CA', 'razon_social': 'Alfa, C.A.', 'rif': 'J-1', 'slug': 'alfa-ca',
            'plan': 'BASICO', 'estado': 'SUSPENDIDA', 'activa_hasta': '', 'limite_usuarios': '', 'notas': 'x'})
        self.empresa.refresh_from_db()
        self.assertEqual((self.empresa.slug, self.empresa.estado, self.empresa.perfil.rif), ('alfa-ca', 'SUSPENDIDA', 'J-1'))
        self.client.force_login(self.dueno)
        r = self.client.get('/')
        self.assertRedirects(r, reverse('empresas:sin_empresa'))
        self.assertContains(self.client.get(reverse('empresas:sin_empresa')), 'suspendido')

    def test_mi_empresa_no_cambia_razon_social_ni_rif(self):
        p = self.empresa.perfil
        p.razon_social, p.rif = 'Alfa, C.A.', 'J-1'
        p.save()
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('empresas:mi_empresa'))
        self.assertContains(r, 'Lo actualiza el equipo de Ordo')


class EnlaceTests(Base):
    def test_login_con_marca_y_empresa_preseleccionada(self):
        otra = Empresa.objects.create(nombre='Beta', slug='beta')
        Membresia.objects.create(usuario=self.dueno, empresa=otra, rol=Rol.VENDEDOR)
        r = self.client.get('/beta/')
        self.assertContains(r, 'Beta')
        r = self.client.post('/beta/', {'username': 'd@alfa.com', 'password': 'clave-segura-123'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['empresa'], otra)          # sin pasar por "elige una empresa"

    def test_con_sesion_cambia_de_empresa(self):
        otra = Empresa.objects.create(nombre='Beta', slug='beta')
        Membresia.objects.create(usuario=self.dueno, empresa=otra, rol=Rol.VENDEDOR)
        self.client.force_login(self.dueno)
        self.assertRedirects(self.client.get('/beta/'), '/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/').context['empresa'], otra)

    def test_sin_membresia_o_suspendida(self):
        Empresa.objects.create(nombre='Beta', slug='beta')
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get('/beta/').status_code, 403)
        Empresa.objects.filter(pk=self.empresa.pk).update(activa_hasta=HOY - timedelta(days=1))
        self.assertContains(self.client.get('/alfa/'), 'suspendido', status_code=403)

    def test_enlace_inexistente_404_y_rutas_de_ordo_intactas(self):
        self.assertEqual(self.client.get('/no-existe/').status_code, 404)
        self.assertEqual(self.client.get('/salud/').status_code, 200)


class LimiteYVencimientoTests(Base):
    def test_limite_de_usuarios(self):
        Empresa.objects.filter(pk=self.empresa.pk).update(limite_usuarios=2)
        self.empresa.refresh_from_db()
        equipo.agregar(self.empresa, self.m_dueno, 'v1@alfa.com', 'a', 'b', Rol.VENDEDOR)
        with self.assertRaisesRegex(equipo.ErrorEquipo, 'permite 2'):
            equipo.agregar(self.empresa, self.m_dueno, 'v2@alfa.com', 'a', 'b', Rol.VENDEDOR)
        m1 = Membresia.objects.get(usuario__email='v1@alfa.com')
        equipo.actualizar(self.m_dueno, m1, Rol.VENDEDOR, False)
        equipo.agregar(self.empresa, self.m_dueno, 'v2@alfa.com', 'a', 'b', Rol.VENDEDOR)
        with self.assertRaises(equipo.ErrorEquipo):                   # reactivar excede el límite
            equipo.actualizar(self.m_dueno, Membresia.objects.get(pk=m1.pk), Rol.VENDEDOR, True)

    def test_aviso_de_vencimiento_para_el_dueno(self):
        Empresa.objects.filter(pk=self.empresa.pk).update(activa_hasta=HOY + timedelta(days=3))
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get('/'), 'vence en <b>3 días</b>')
