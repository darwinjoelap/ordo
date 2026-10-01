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
             'notas': '', 'usuario_dueno': 'Darwin', 'email_dueno': '', 'nombre_dueno': 'Darwin', 'apellido_dueno': 'P'}
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
        self.assertEqual((m.rol, m.usuario.username, m.usuario.empresa_cuenta, m.usuario.debe_cambiar_clave),
                         (Rol.DUENO, 'darwin', e, True))

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
    def test_login_por_enlace_con_usuario_de_la_empresa(self):
        otra = Empresa.objects.create(nombre='Beta', slug='beta')
        maria_b = U.objects.create_user('maria', 'clave-b-123456', empresa_cuenta=otra)
        Membresia.objects.create(usuario=maria_b, empresa=otra, rol=Rol.VENDEDOR)
        maria_a = U.objects.create_user('maria', 'clave-a-123456', empresa_cuenta=self.empresa)
        Membresia.objects.create(usuario=maria_a, empresa=self.empresa, rol=Rol.VENDEDOR)
        self.assertContains(self.client.get('/beta/'), 'Beta')
        # La clave de 'maria' de Alfa no sirve en el enlace de Beta
        self.assertContains(self.client.post('/beta/', {'username': 'maria', 'password': 'clave-a-123456'}),
                            'Usuario o contraseña incorrectos')
        r = self.client.post('/beta/', {'username': 'Maria', 'password': 'clave-b-123456'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        self.assertEqual(r.cookies['ordo_empresa'].value, 'beta')
        r = self.client.get('/')
        self.assertEqual((r.context['empresa'], r.context['user']), (otra, maria_b))
        # Al cerrar sesión, la dirección principal lleva al login de su empresa
        self.client.post(reverse('usuarios:logout'))
        self.assertRedirects(self.client.get(reverse('usuarios:login')), '/beta/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('usuarios:login') + '?plataforma=1').status_code, 200)

    def test_login_principal_solo_cuentas_de_plataforma(self):
        U.objects.create_user('pepe', 'clave-segura-123', empresa_cuenta=self.empresa)
        r = self.client.post(reverse('usuarios:login'), {'username': 'pepe', 'password': 'clave-segura-123'})
        self.assertContains(r, 'Usuario o contraseña incorrectos')
        r = self.client.post(reverse('usuarios:login'), {'username': 'root@ordo.app', 'password': 'clave-segura-123'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)

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
        equipo.agregar(self.empresa, self.m_dueno, 'v1', 'a', 'b', Rol.VENDEDOR)
        with self.assertRaisesRegex(equipo.ErrorEquipo, 'permite 2'):
            equipo.agregar(self.empresa, self.m_dueno, 'v2', 'a', 'b', Rol.VENDEDOR)
        m1 = Membresia.objects.get(usuario__username='v1')
        equipo.actualizar(self.m_dueno, m1, Rol.VENDEDOR, False)
        equipo.agregar(self.empresa, self.m_dueno, 'v2', 'a', 'b', Rol.VENDEDOR)
        with self.assertRaises(equipo.ErrorEquipo):                   # reactivar excede el límite
            equipo.actualizar(self.m_dueno, Membresia.objects.get(pk=m1.pk), Rol.VENDEDOR, True)

    def test_aviso_de_vencimiento_para_el_dueno(self):
        Empresa.objects.filter(pk=self.empresa.pk).update(activa_hasta=HOY + timedelta(days=3))
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get('/'), 'vence en <b>3 días</b>')


class SoporteTests(Base):
    def test_superusuario_va_al_panel_y_entra_a_cualquier_empresa(self):
        self.client.force_login(self.root)
        self.assertRedirects(self.client.get('/'), reverse('plataforma:lista'))
        self.client.post(reverse('plataforma:entrar', args=[self.empresa.pk]))
        r = self.client.get('/')
        self.assertEqual(r.context['empresa'], self.empresa)
        self.assertContains(r, 'Modo soporte')
        self.assertEqual(self.client.get(reverse('empresas:mi_empresa')).status_code, 200)   # permisos de Dueño
        self.assertFalse(Membresia.objects.filter(usuario=self.root).exists())                # no se crea membresía
        self.client.post(reverse('plataforma:salir'))
        self.assertRedirects(self.client.get('/'), reverse('plataforma:lista'))

    def test_superusuario_no_aparece_en_equipo_ni_cuenta_en_limite(self):
        Membresia.objects.create(usuario=self.root, empresa=self.empresa, rol=Rol.ADMIN)
        Empresa.objects.filter(pk=self.empresa.pk).update(limite_usuarios=2)
        self.empresa.refresh_from_db()
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('empresas:equipo'))
        self.assertNotContains(r, 'root@ordo.app')
        equipo.agregar(self.empresa, self.m_dueno, 'v1', 'a', 'b', Rol.VENDEDOR)    # 2 de 2: el root no cuenta

    def test_enlace_de_empresa_para_superusuario(self):
        self.client.force_login(self.root)
        self.assertRedirects(self.client.get('/alfa/'), '/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/').context['empresa'], self.empresa)

    def test_soporte_entra_a_empresa_suspendida(self):
        Empresa.objects.filter(pk=self.empresa.pk).update(estado='SUSPENDIDA')
        self.client.force_login(self.root)
        self.client.post(reverse('plataforma:entrar', args=[self.empresa.pk]))
        self.assertContains(self.client.get('/'), 'Empresa suspendida o vencida')

    def test_usuario_normal_no_puede_usar_entrar(self):
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.post(reverse('plataforma:entrar', args=[self.empresa.pk])).status_code, 403)
