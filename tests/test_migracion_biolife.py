"""
Fase 7: importación de BioLifeVentas (comando importar_biolifeventas).
El archivo de muestra se generó con scripts/biolifeventas_exportar.py sobre una copia de los modelos de
BioLifeVentas con datos de prueba (ver tests/datos/biolifeventas_semilla.py).
"""
import json
from io import StringIO
from pathlib import Path

from django.contrib.auth import authenticate
from django.core.management import CommandError, call_command
from django.test import RequestFactory, TestCase

from apps.clientes.models import Cliente
from apps.core.migracion_biolife import ErrorMigracion, Importador
from apps.core.tenancy import usando_empresa
from apps.empresas.models import Empresa, Membresia
from apps.inventario.models import Lote, MovimientoInventario, Producto
from apps.usuarios.models import Usuario
from apps.ventas.models import ItemPresupuesto, Presupuesto, Reserva

ARCHIVO = Path(__file__).parent / 'datos' / 'biolifeventas_muestra.json'


class MigracionBiolifeTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre='BioLife', slug='biolife')
        self.datos = json.loads(ARCHIVO.read_text(encoding='utf-8'))

    def importar(self, **kw):
        return Importador(json.loads(ARCHIVO.read_text(encoding='utf-8')), self.empresa).ejecutar(**kw)

    def test_simular_no_guarda_nada_pero_verifica(self):
        imp = self.importar(simular=True)
        self.assertTrue(imp.ok, imp.verificacion)
        self.assertFalse(Producto.todos.exists())
        self.assertFalse(Usuario.objects.filter(empresa_cuenta=self.empresa).exists())

    def test_importacion_completa_cuadra(self):
        imp = self.importar()
        self.assertTrue(imp.ok, imp.verificacion)
        self.assertEqual(Producto.todos.filter(empresa=self.empresa).count(), 3)
        self.assertEqual(Presupuesto.todos.filter(estado='VALIDADA').count(), 2)

    def test_usuarios_con_su_misma_clave_y_rol(self):
        self.importar()
        r = RequestFactory().get('/')
        r.empresa_login = self.empresa
        self.assertIsNotNone(authenticate(r, username='luis', password='clave-luis-1'))
        self.assertIsNotNone(authenticate(r, username='Admin', password='clave-admin-1'))   # se guarda en minúsculas
        roles = dict(Membresia.objects.filter(empresa=self.empresa).values_list('usuario__username', 'rol'))
        self.assertEqual(roles, {'admin': 'DUENO', 'ana': 'ADMIN', 'luis': 'VENDEDOR', 'pedro': 'VENDEDOR'})
        self.assertFalse(Membresia.objects.get(usuario__username='pedro').activa)
        self.assertFalse(Usuario.objects.get(username='admin').is_superuser)

    def test_usuario_existente_se_reutiliza(self):
        u = Usuario.objects.create_user('luis', password='clave-ordo-123', empresa_cuenta=self.empresa)
        imp = self.importar()
        u.refresh_from_db()
        self.assertTrue(u.check_password('clave-ordo-123'))
        self.assertTrue(any('luis' in a for a in imp.avisos))

    def test_venta_con_lotes_partidos_queda_en_una_linea(self):
        self.importar()
        with usando_empresa(self.empresa):
            p = Presupuesto.objects.get(numero='202600001')
            glu = ItemPresupuesto.objects.get(presupuesto=p, producto__codigo='GLU-01')
            reservas = sorted((r.lote.numero_lote, r.cantidad) for r in Reserva.objects.filter(item=glu))
        self.assertEqual(glu.cantidad, 30)
        self.assertEqual(reservas, [('G-A', 20), ('G-B', 10)])
        self.assertEqual((p.facturado, p.numero_factura, p.numero_control, p.pagado, p.metodo_pago),
                         (True, '000123', '00-0456', True, 'ZELLE'))
        self.assertEqual(glu.costo_usd.to_eng_string(), '9.67')          # costo ponderado de los lotes

    def test_venta_sin_iva_y_con_descuento(self):
        self.importar()
        p = Presupuesto.todos.get(numero='202600002')
        self.assertEqual((p.iva_pct, p.descuento_pct, str(p.total_usd)), (0, 7, '92.95'))

    def test_kardex_con_fechas_y_saldos_que_terminan_en_el_lote(self):
        self.importar()
        for lote in Lote.todos.filter(empresa=self.empresa):
            ultimo = MovimientoInventario.todos.filter(lote=lote).order_by('fecha', 'pk').last()
            self.assertEqual((ultimo.saldo_actual, ultimo.saldo_apartado), (lote.cantidad_actual, lote.cantidad_apartada))
        ingreso = MovimientoInventario.todos.filter(tipo='INGRESO').order_by('fecha').first()
        self.assertLess(ingreso.fecha.date().isoformat(), self.datos['exportado_en'][:10])   # fecha histórica

    def test_clientes_con_vendedor_y_cartera_abierta(self):
        self.importar()
        self.assertEqual(Cliente.todos.get(nombre='Clínica Sol').vendedor.username, 'luis')
        self.empresa.perfil.refresh_from_db()
        self.assertTrue(self.empresa.perfil.vendedores_ven_todos_los_clientes)

    def test_los_presupuestos_nuevos_siguen_el_correlativo(self):
        from django.utils import timezone

        from apps.ventas import servicios as ventas
        self.importar()
        self.empresa.refresh_from_db()
        anio = str(timezone.localdate().year)
        ultimo = max([int(b['numero'][4:]) for b in self.datos['presupuestos'] if b['numero'].startswith(anio)] or [0])
        with usando_empresa(self.empresa):
            cliente = Cliente.objects.first()
            vendedor = Usuario.objects.get(username='luis')
            p1 = ventas.crear(cliente, vendedor, self.empresa)
            p2 = ventas.crear(cliente, vendedor, self.empresa)
        self.assertEqual(p1.numero, f'{anio}{ultimo + 1:05d}')
        self.assertEqual(p2.numero, f'{anio}{ultimo + 2:05d}')

    def test_rechaza_empresa_con_datos_salvo_vaciar(self):
        self.importar()
        with self.assertRaises(ErrorMigracion):
            self.importar()
        imp = self.importar(vaciar=True)                 # reemplaza y vuelve a cuadrar
        self.assertTrue(imp.ok)
        self.assertEqual(Producto.todos.filter(empresa=self.empresa).count(), 3)

    def test_rechaza_archivo_ajeno_o_inconsistente(self):
        with self.assertRaises(ErrorMigracion):
            Importador({'origen': 'otro'}, self.empresa)
        datos = json.loads(ARCHIVO.read_text(encoding='utf-8'))
        datos['lotes'][0]['cantidad_apartada'] = 999
        with self.assertRaisesMessage(ErrorMigracion, 'inconsistentes'):
            Importador(datos, self.empresa).ejecutar()
        self.assertFalse(Producto.todos.exists())       # nada a medias

    def test_comando(self):
        salida = StringIO()
        call_command('importar_biolifeventas', str(ARCHIVO), '--empresa', 'biolife', '--simular', stdout=salida)
        self.assertIn('Todo cuadra', salida.getvalue())
        with self.assertRaises(CommandError):
            call_command('importar_biolifeventas', str(ARCHIVO), '--empresa', 'no-existe', stdout=StringIO())


class PantallaMigracionTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre='BioLife', slug='biolife')
        self.root = Usuario.objects.create_superuser('root', password='clave-segura-123')
        self.url = f'/plataforma/{self.empresa.pk}/migrar/'

    def subir(self, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        archivo = SimpleUploadedFile('export.json', ARCHIVO.read_bytes(), content_type='application/json')
        return self.client.post(self.url, {'archivo': archivo, **extra})

    def test_simular_y_guardar(self):
        self.client.force_login(self.root)
        r = self.subir(guardar='0')
        self.assertContains(r, 'Todo cuadra')
        self.assertFalse(Producto.todos.exists())
        r = self.subir(guardar='1')
        self.assertContains(r, 'Migración guardada')
        self.assertEqual(Producto.todos.filter(empresa=self.empresa).count(), 3)
        self.assertContains(self.client.get(self.url), 'ya tiene datos')

    def test_solo_plataforma(self):
        dueno = Usuario.objects.create_user('d', password='clave-segura-123', empresa_cuenta=self.empresa)
        Membresia.objects.create(usuario=dueno, empresa=self.empresa, rol='DUENO')
        self.client.force_login(dueno)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class NumeracionCorridaTests(TestCase):
    def test_formato_corrido_sin_migracion_y_formato_por_defecto(self):
        from django.utils import timezone

        from apps.core.secuencias import siguiente_numero_presupuesto
        empresa = Empresa.objects.create(nombre='Nueva', slug='nueva')
        anio = timezone.localdate().year
        with usando_empresa(empresa):
            self.assertEqual(siguiente_numero_presupuesto(empresa.perfil), f'P-{anio}-00001')
            empresa.perfil.formato_numero_presupuesto = 'CORRIDO'
            empresa.perfil.save()
            self.assertEqual(siguiente_numero_presupuesto(empresa.perfil), f'{anio}00001')
            self.assertEqual(siguiente_numero_presupuesto(empresa.perfil), f'{anio}00002')
