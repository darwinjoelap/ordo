"""
Pruebas de la Fase 2: empresas, membresías, aislamiento, permisos y panel Mi empresa.
"""
import os
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, models
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.core.tenancy import EmpresaModel, usando_empresa
from apps.empresas.models import Empresa, Membresia, PerfilEmpresa, Rol

MEDIA_TMP = tempfile.mkdtemp(prefix='ordo-test-media-')
ALMACEN_LOCAL = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def imagen(nombre='logo.png', formato='PNG', tamano=(1200, 400), color=(5, 61, 116, 255)):
    buffer = BytesIO()
    modo = 'RGBA' if formato == 'PNG' else 'RGB'
    Image.new(modo, tamano, color[:len(modo)]).save(buffer, format=formato)
    tipo = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif'}[formato]
    return SimpleUploadedFile(nombre, buffer.getvalue(), content_type=tipo)


def crear_usuario(email, **extra):
    return get_user_model().objects.create_user(email, 'clave-segura-123', **extra)


class BaseEmpresas(TestCase):
    def setUp(self):
        self.a = Empresa.objects.create(nombre='Farmacia Alfa')
        self.b = Empresa.objects.create(nombre='Ferretería Beta')
        self.dueno_a = crear_usuario('dueno@alfa.com')
        self.vendedor_a = crear_usuario('vende@alfa.com')
        Membresia.objects.create(usuario=self.dueno_a, empresa=self.a, rol=Rol.DUENO)
        Membresia.objects.create(usuario=self.vendedor_a, empresa=self.a, rol=Rol.VENDEDOR)


class EmpresaTests(BaseEmpresas):
    def test_empresa_nueva_crea_perfil_y_slug(self):
        self.assertEqual(self.a.slug, 'farmacia-alfa')
        self.assertEqual(self.a.perfil.nombre_comercial, 'Farmacia Alfa')

    def test_slug_repetido_se_numera(self):
        otra = Empresa.objects.create(nombre='Farmacia Alfa')
        self.assertEqual(otra.slug, 'farmacia-alfa-2')

    def test_empresa_suspendida_no_esta_activa(self):
        self.a.estado = Empresa.Estado.SUSPENDIDA
        self.assertFalse(self.a.esta_activa)

    def test_comando_crear_empresa(self):
        call_command('crear_empresa', 'Tienda Gamma', 'nuevo@gamma.com', '--password', 'clave-segura-123')
        e = Empresa.objects.get(slug='tienda-gamma')
        m = Membresia.objects.get(empresa=e)
        self.assertEqual((m.usuario.email, m.rol), ('nuevo@gamma.com', Rol.DUENO))


class MiddlewareTests(BaseEmpresas):
    def test_una_sola_empresa_se_elige_sola(self):
        self.client.force_login(self.dueno_a)
        r = self.client.get(reverse('core:inicio'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['empresa'], self.a)
        self.assertContains(r, 'Farmacia Alfa')

    def test_varias_empresas_piden_elegir(self):
        Membresia.objects.create(usuario=self.dueno_a, empresa=self.b, rol=Rol.VENDEDOR)
        self.client.force_login(self.dueno_a)
        r = self.client.get(reverse('core:inicio'))
        self.assertRedirects(r, f"{reverse('empresas:seleccionar')}?next=/")
        r = self.client.post(reverse('empresas:seleccionar'), {'empresa': self.b.pk, 'next': '/'})
        self.assertRedirects(r, '/')
        r = self.client.get('/')
        self.assertEqual(r.context['empresa'], self.b)
        self.assertEqual(r.context['membresia'].rol, Rol.VENDEDOR)

    def test_no_puede_elegir_empresa_ajena(self):
        Membresia.objects.create(usuario=self.dueno_a, empresa=Empresa.objects.create(nombre='Otra'))
        self.client.force_login(self.dueno_a)
        r = self.client.post(reverse('empresas:seleccionar'), {'empresa': self.b.pk})
        self.assertEqual(r.status_code, 404)

    def test_usuario_sin_empresa(self):
        self.client.force_login(crear_usuario('solo@nadie.com'))
        r = self.client.get('/')
        self.assertRedirects(r, reverse('empresas:sin_empresa'))

    def test_empresa_suspendida_bloquea_acceso(self):
        self.a.estado = Empresa.Estado.SUSPENDIDA
        self.a.save()
        self.client.force_login(self.dueno_a)
        self.assertRedirects(self.client.get('/'), reverse('empresas:sin_empresa'))

    def test_membresia_inactiva_bloquea_acceso(self):
        Membresia.objects.filter(usuario=self.vendedor_a).update(activa=False)
        self.client.force_login(self.vendedor_a)
        self.assertRedirects(self.client.get('/'), reverse('empresas:sin_empresa'))


class PermisosTests(BaseEmpresas):
    def test_vendedor_no_entra_a_mi_empresa(self):
        self.client.force_login(self.vendedor_a)
        r = self.client.get(reverse('empresas:mi_empresa'))
        self.assertEqual(r.status_code, 403)
        self.assertNotContains(self.client.get('/'), reverse('empresas:mi_empresa'))

    def test_dueno_entra_a_mi_empresa(self):
        self.client.force_login(self.dueno_a)
        r = self.client.get(reverse('empresas:mi_empresa'))
        self.assertContains(r, 'Mi empresa')


@override_settings(MEDIA_ROOT=MEDIA_TMP, STORAGES=ALMACEN_LOCAL)
class PanelMiEmpresaTests(BaseEmpresas):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    def datos(self, **extra):
        base = {
            'nombre_comercial': 'Alfa Salud', 'razon_social': 'Farmacia Alfa C.A.', 'rif': 'J-12345678-9',
            'color_principal': '#11988D', 'direccion_fiscal': 'Av. Lara, Barquisimeto',
            'telefono': '0251-5550000', 'telefono_2': '', 'email': 'ventas@alfa.com', 'sitio_web': '',
            'instagram': '', 'whatsapp': '', 'prefijo_numeracion': 'AF',
            'condiciones_presupuesto': 'Válido 7 días.', 'pie_documentos': 'Gracias por su compra',
            'datos_bancarios': 'Banesco 0134...', 'iva_porcentaje': '16', 'dias_validez_presupuesto': '7',
            'dias_apartado': '15', 'modo_precio': 'RANGO', 'margen_minimo_pct': '10',
            'margen_maximo_pct': '40', 'requiere_validacion': 'on', 'tab': 'identidad',
        }
        base.update(extra)
        return base

    def test_guardar_datos_y_logo(self):
        self.client.force_login(self.dueno_a)
        r = self.client.post(reverse('empresas:mi_empresa'), self.datos(logo=imagen()))
        self.assertRedirects(r, f"{reverse('empresas:mi_empresa')}?tab=identidad")
        perfil = PerfilEmpresa.objects.get(empresa=self.a)
        self.assertEqual(perfil.rif, '')              # RIF y razón social los administra la plataforma
        self.assertTrue(perfil.logo.name.startswith('ordo/farmacia-alfa/logo/'))
        with Image.open(perfil.logo_pdf.path) as img:
            self.assertEqual(img.width, 600)          # copia optimizada para PDF
        self.assertFalse(perfil.comision_requiere_pago)

    def test_rechaza_logo_gif(self):
        self.client.force_login(self.dueno_a)
        r = self.client.post(reverse('empresas:mi_empresa'), self.datos(logo=imagen('x.gif', 'GIF')))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'debe ser PNG o JPG')

    def test_rechaza_logo_mayor_a_2mb(self):
        self.client.force_login(self.dueno_a)
        ruido = Image.frombytes('RGB', (1200, 1200), os.urandom(1200 * 1200 * 3))  # no comprime: >2 MB
        buffer = BytesIO()
        ruido.save(buffer, format='PNG')
        self.assertGreater(len(buffer.getvalue()), 2 * 1024 * 1024)
        pesado = SimpleUploadedFile('grande.png', buffer.getvalue(), content_type='image/png')
        r = self.client.post(reverse('empresas:mi_empresa'), self.datos(logo=pesado))
        self.assertContains(r, 'el máximo es 2 MB')

    def test_margen_maximo_menor_que_minimo(self):
        self.client.force_login(self.dueno_a)
        r = self.client.post(reverse('empresas:mi_empresa'), self.datos(margen_minimo_pct='30', margen_maximo_pct='10'))
        self.assertContains(r, 'no puede ser menor que el mínimo')

    def test_vista_previa_htmx(self):
        self.client.force_login(self.dueno_a)
        r = self.client.post(reverse('empresas:vista_previa'), self.datos(nombre_comercial='Nombre en vivo'))
        self.assertContains(r, 'Nombre en vivo')
        self.assertEqual(PerfilEmpresa.objects.get(empresa=self.a).nombre_comercial, 'Farmacia Alfa')  # no guarda

    def test_pdf_de_prueba_con_y_sin_logo(self):
        self.client.force_login(self.dueno_a)
        r = self.client.get(reverse('empresas:pdf_prueba'))
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.client.post(reverse('empresas:mi_empresa'), self.datos(logo=imagen('logo.jpg', 'JPEG')))
        r2 = self.client.get(reverse('empresas:pdf_prueba'))
        self.assertTrue(r2.content.startswith(b'%PDF'))
        self.assertGreater(len(r2.content), len(r.content))   # ahora incluye la imagen

    def test_vendedor_no_puede_generar_pdf_de_prueba(self):
        self.client.force_login(self.vendedor_a)
        self.assertEqual(self.client.get(reverse('empresas:pdf_prueba')).status_code, 403)


class NotaPrueba(EmpresaModel):
    """Modelo solo para pruebas (su tabla se crea y borra dentro del test)."""
    texto = models.CharField(max_length=20)

    class Meta:
        app_label = 'core'
        managed = False


class EmpresaModelTests(TransactionTestCase):
    """Aislamiento: un modelo de negocio solo ve filas de la empresa activa."""

    def test_aislamiento_entre_empresas(self):
        Nota = NotaPrueba
        with connection.schema_editor() as editor:
            editor.create_model(Nota)
        try:
            a = Empresa.objects.create(nombre='A')
            b = Empresa.objects.create(nombre='B')
            with usando_empresa(a):
                Nota.objects.create(texto='de A')
            with usando_empresa(b):
                Nota.objects.create(texto='de B')
                self.assertEqual(list(Nota.objects.values_list('texto', flat=True)), ['de B'])
            with usando_empresa(a):
                self.assertEqual(list(Nota.objects.values_list('texto', flat=True)), ['de A'])
            # Sin empresa activa: falla cerrado
            self.assertEqual(Nota.objects.count(), 0)
            self.assertEqual(Nota.todos.count(), 2)
            with self.assertRaises(ImproperlyConfigured):
                Nota(texto='huérfana').save()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(Nota)


@override_settings(MEDIA_ROOT=MEDIA_TMP, STORAGES=ALMACEN_LOCAL)
class QuitarLogoTests(PanelMiEmpresaTests.__base__):
    def test_quitar_logo(self):
        self.client.force_login(self.dueno_a)
        url = reverse('empresas:mi_empresa')
        self.client.post(url, PanelMiEmpresaTests.datos(self, logo=imagen()))
        self.assertTrue(PerfilEmpresa.objects.get(empresa=self.a).logo)
        self.client.post(url, PanelMiEmpresaTests.datos(self, quitar_logo='on'))
        perfil = PerfilEmpresa.objects.get(empresa=self.a)
        self.assertFalse(perfil.logo)
        self.assertFalse(perfil.logo_pdf)
