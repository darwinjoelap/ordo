"""
Mi perfil y Equipo: datos personales, cambio de contraseña, invitar, roles, desactivar, contraseña temporal.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.empresas import equipo
from apps.empresas.models import Empresa, Membresia, Rol

U = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre='Alfa')
        self.otra = Empresa.objects.create(nombre='Beta')
        self.dueno = U.objects.create_user('d@alfa.com', 'clave-segura-123')
        self.admin = U.objects.create_user('a@alfa.com', 'clave-segura-123')
        self.vend = U.objects.create_user('v@alfa.com', 'clave-segura-123')
        self.m_dueno = Membresia.objects.create(usuario=self.dueno, empresa=self.empresa, rol=Rol.DUENO)
        self.m_admin = Membresia.objects.create(usuario=self.admin, empresa=self.empresa, rol=Rol.ADMIN)
        self.m_vend = Membresia.objects.create(usuario=self.vend, empresa=self.empresa, rol=Rol.VENDEDOR)


class PerfilTests(Base):
    def test_editar_nombre_y_saludo(self):
        self.client.force_login(self.vend)
        self.client.post(reverse('usuarios:perfil'), {'accion': 'datos', 'first_name': 'Ana', 'last_name': 'Pérez',
                                                      'telefono': '0414'})
        self.vend.refresh_from_db()
        self.assertEqual(self.vend.get_full_name(), 'Ana Pérez')
        self.assertContains(self.client.get('/'), 'Hola, Ana')

    def test_cambiar_clave_sin_cerrar_sesion(self):
        self.client.force_login(self.vend)
        r = self.client.post(reverse('usuarios:perfil'), {'accion': 'clave', 'old_password': 'clave-segura-123',
                                                          'new_password1': 'OtraClave-2026!', 'new_password2': 'OtraClave-2026!'})
        self.assertRedirects(r, '/')
        self.vend.refresh_from_db()
        self.assertTrue(self.vend.check_password('OtraClave-2026!'))
        self.assertEqual(self.client.get('/').status_code, 200)     # sigue con sesión

    def test_clave_temporal_obliga_a_cambiarla(self):
        self.vend.debe_cambiar_clave = True
        self.vend.save()
        self.client.force_login(self.vend)
        self.assertRedirects(self.client.get('/ventas/'), '/cuenta/perfil/?clave=1', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/cuenta/perfil/?clave=1').status_code, 200)
        self.client.post(reverse('usuarios:perfil'), {'accion': 'clave', 'old_password': 'clave-segura-123',
                                                      'new_password1': 'OtraClave-2026!', 'new_password2': 'OtraClave-2026!'})
        self.vend.refresh_from_db()
        self.assertFalse(self.vend.debe_cambiar_clave)
        self.assertEqual(self.client.get('/ventas/').status_code, 200)


class EquipoServicioTests(Base):
    def test_agregar_usuario_nuevo_crea_clave_temporal(self):
        m, clave = equipo.agregar(self.empresa, self.m_admin, 'NUEVO@alfa.com', 'Luis', 'Gómez', Rol.VENDEDOR)
        self.assertTrue(clave.startswith('Ordo-'))
        self.assertEqual(m.usuario.email, 'nuevo@alfa.com')
        self.assertTrue(m.usuario.check_password(clave))
        self.assertTrue(m.usuario.debe_cambiar_clave)

    def test_agregar_usuario_existente_no_toca_su_clave(self):
        m, clave = equipo.agregar(self.otra, self.m_dueno, 'v@alfa.com', 'x', 'y', Rol.VENDEDOR)
        self.assertIsNone(clave)
        self.vend.refresh_from_db()
        self.assertTrue(self.vend.check_password('clave-segura-123'))
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.agregar(self.empresa, self.m_dueno, 'v@alfa.com', 'x', 'y', Rol.VENDEDOR)   # ya es miembro

    def test_admin_no_asigna_dueno_ni_toca_duenos_ni_a_si_mismo(self):
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.agregar(self.empresa, self.m_admin, 'x@alfa.com', 'x', 'y', Rol.DUENO)
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.actualizar(self.m_admin, self.m_dueno, Rol.VENDEDOR, True)
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.actualizar(self.m_admin, self.m_admin, Rol.DUENO, True)
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.actualizar(self.m_admin, self.m_vend, Rol.DUENO, True)

    def test_siempre_queda_un_dueno(self):
        otro = Membresia.objects.create(usuario=U.objects.create_user('d2@alfa.com', 'x'), empresa=self.empresa,
                                        rol=Rol.DUENO)
        equipo.actualizar(otro, self.m_dueno, Rol.ADMIN, True)            # queda "otro" como dueño
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.actualizar(self.m_dueno.__class__.objects.get(pk=self.m_dueno.pk), otro, Rol.ADMIN, True)

    def test_desactivar_quita_acceso(self):
        equipo.actualizar(self.m_admin, self.m_vend, Rol.VENDEDOR, False)
        self.client.force_login(self.vend)
        self.assertRedirects(self.client.get('/'), reverse('empresas:sin_empresa'))

    def test_restablecer_clave_solo_si_pertenece_solo_a_esta_empresa(self):
        clave = equipo.restablecer_clave(self.m_admin, self.m_vend)
        self.vend.refresh_from_db()
        self.assertTrue(self.vend.check_password(clave) and self.vend.debe_cambiar_clave)
        Membresia.objects.create(usuario=self.vend, empresa=self.otra, rol=Rol.VENDEDOR)
        with self.assertRaises(equipo.ErrorEquipo):
            equipo.restablecer_clave(self.m_admin, self.m_vend)


class EquipoVistasTests(Base):
    def test_vendedor_no_entra(self):
        self.client.force_login(self.vend)
        self.assertEqual(self.client.get(reverse('empresas:equipo')).status_code, 403)

    def test_flujo_por_la_web(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('empresas:equipo'))
        self.assertContains(r, 'v@alfa.com')
        r = self.client.post(reverse('empresas:equipo_agregar'),
                             {'email': 'n@alfa.com', 'nombre': 'Nora', 'apellido': 'Díaz', 'rol': Rol.ALMACEN})
        self.assertContains(r, 'Ordo-')
        m = Membresia.objects.get(usuario__email='n@alfa.com')
        self.assertEqual(m.rol, Rol.ALMACEN)
        self.client.post(reverse('empresas:equipo_actualizar', args=[m.pk]), {'rol': Rol.VENDEDOR, 'activa': '1'})
        m.refresh_from_db()
        self.assertEqual(m.rol, Rol.VENDEDOR)
        r = self.client.post(reverse('empresas:equipo_clave', args=[m.pk]))
        self.assertContains(r, 'Contraseña temporal')

    def test_no_se_gestiona_membresia_de_otra_empresa(self):
        ajena = Membresia.objects.create(usuario=U.objects.create_user('z@beta.com', 'x'), empresa=self.otra,
                                         rol=Rol.VENDEDOR)
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.post(reverse('empresas:equipo_clave', args=[ajena.pk])).status_code, 404)
