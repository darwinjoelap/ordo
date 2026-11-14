"""«Cargar con IA»: pedido (texto/foto/PDF) → candidatos del inventario → revisión → agregar."""
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core import gemini
from apps.core.tenancy import usando_empresa
from apps.inventario.models import Categoria, Marca, Producto, Unidad
from apps.ventas import carga_ia, servicios
from apps.ventas.models import ItemPresupuesto, Presupuesto, UsoIA

from .test_fase4 import Base

SIN_IA = override_settings(GEMINI_API_KEY='', IA_MODO='')
CON_IA = override_settings(GEMINI_API_KEY='clave-de-prueba', IA_MODO='')


class BaseIA(Base):
    def setUp(self):
        super().setUp()
        self.perfil.carga_ia_presupuestos = True
        self.perfil.save()
        with self.empresa_ctx():
            un = Unidad.objects.get(abreviatura='UN')
            saco = Unidad.objects.create(nombre='Saco', abreviatura='SAC')
            m = Marca.objects.create(nombre='Agrofert')
            self.urea = Producto.objects.create(codigo='U46', nombre='Urea 46% saco 50 kg', categoria=self.cat,
                                                unidad=saco, marca=m, precio_costo_usd=Decimal('20'),
                                                precio_venta_usd=Decimal('30'))
            self.glifo = Producto.objects.create(codigo='GLI-48', nombre='Glifosato 48% galón', categoria=self.cat,
                                                 unidad=un, precio_costo_usd=Decimal('8'),
                                                 precio_venta_usd=Decimal('12'))
            self.glifo_l = Producto.objects.create(codigo='GLI-1L', nombre='Glifosato 48% litro', categoria=self.cat,
                                                   unidad=un, precio_costo_usd=Decimal('3'),
                                                   precio_venta_usd=Decimal('4'))
            self.p = servicios.crear(self.cliente, self.vendedor, self.empresa)
        self.client.force_login(self.vendedor)
        self.url = reverse('ventas:carga_ia', args=[self.p.pk])

    def items(self):
        with self.empresa_ctx():
            return {i.producto.codigo: i.cantidad for i in ItemPresupuesto.objects.filter(presupuesto=self.p)
                    .select_related('producto')}


@SIN_IA
class ModoPruebaTests(BaseIA):
    def test_texto_propone_productos_y_se_agregan_al_confirmar(self):
        r = self.client.post(self.url, {'texto': '2 sacos urea\n3 glifosato galon\n1 tornillo dorado'})
        self.assertEqual(r.status_code, 200)
        lineas = r.context['resultado'].lineas
        self.assertEqual([(x.cantidad, x.producto) for x in lineas[:2]], [(2, self.urea), (3, self.glifo)])
        self.assertIsNone(lineas[2].producto)                # no está en el inventario
        self.assertContains(r, 'No se encontró en tu inventario')
        uso = UsoIA.todos.get()
        self.assertEqual((uso.lineas, uso.sugeridas, uso.modelo, uso.costo_usd), (3, 2, 'prueba', 0))

        datos = {'n': 3, 'uso': uso.pk, 'incluir_0': '1', 'producto_0': self.urea.pk, 'cantidad_0': '2',
                 'incluir_1': '1', 'producto_1': self.glifo.pk, 'cantidad_1': '5'}
        r = self.client.post(reverse('ventas:carga_ia_agregar', args=[self.p.pk]), datos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.items(), {'U46': 2, 'GLI-48': 5})
        uso.refresh_from_db()
        self.assertEqual(uso.agregadas, 2)

    def test_codigo_exacto_al_inicio_de_la_linea(self):
        r = self.client.post(self.url, {'texto': '4 U46'})
        x = r.context['resultado'].lineas[0]
        self.assertEqual((x.producto, x.confianza, x.cantidad), (self.urea, 'exacto', 4))

    def test_fotos_no_se_aceptan_sin_ia(self):
        foto = SimpleUploadedFile('pedido.jpg', b'\xff\xd8\xff', content_type='image/jpeg')
        r = self.client.post(self.url, {'texto': '', 'archivos': [foto]})
        self.assertContains(r, 'modo de prueba')
        self.assertFalse(UsoIA.todos.exists())

    def test_apagado_en_mi_empresa_no_existe(self):
        self.perfil.carga_ia_presupuestos = False
        self.perfil.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        r = self.client.get(reverse('ventas:detalle', args=[self.p.pk]))
        self.assertNotContains(r, 'Cargar con IA')

    def test_boton_visible_si_esta_activo(self):
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[self.p.pk])), 'Cargar con IA')

    def test_no_agrega_productos_ajenos_ni_en_presupuesto_cerrado(self):
        with usando_empresa(self.otra):
            ajeno = Producto.objects.create(codigo='X', nombre='Ajeno', categoria=Categoria.objects.create(nombre='C'),
                                            unidad=Unidad.objects.create(nombre='U', abreviatura='U'))
        r = self.client.post(reverse('ventas:carga_ia_agregar', args=[self.p.pk]),
                             {'n': 1, 'incluir_0': '1', 'producto_0': ajeno.pk, 'cantidad_0': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.items(), {})
        Presupuesto.todos.filter(pk=self.p.pk).update(estado=Presupuesto.Estado.CANCELADO)
        self.p.refresh_from_db()
        self.assertFalse(self.p.editable)
        self.assertRedirects(self.client.get(self.url), reverse('ventas:detalle', args=[self.p.pk]),
                             fetch_redirect_response=False)


@CON_IA
class ConIATests(BaseIA):
    def respuestas(self, *datos):
        return mock.patch.object(gemini, 'json_estructurado', side_effect=[
            gemini.Respuesta(d, 1000, 200, 'gemini-3.5-flash-lite') for d in datos])

    def test_dos_pasos_y_codigo_inventado_se_ignora(self):
        leer = {'lineas': [{'texto': 'urea', 'codigo': 'U46', 'cantidad': 2},
                           {'texto': 'glifo 48', 'codigo': '', 'cantidad': 1, 'unidad': 'galón'},
                           {'texto': 'glifo litro', 'codigo': '', 'cantidad': 2.5}]}
        elegir = {'elecciones': [{'linea': 1, 'codigo': 'GLI-48', 'confianza': 'alta'},
                                 {'linea': 2, 'codigo': 'NO-EXISTE', 'confianza': 'alta'}]}
        with self.respuestas(leer, elegir) as llamada:
            r = self.client.post(self.url, {'texto': 'pedido'})
        lineas = r.context['resultado'].lineas
        self.assertEqual((lineas[0].producto, lineas[0].confianza), (self.urea, 'exacto'))
        self.assertEqual((lineas[1].producto, lineas[1].confianza), (self.glifo, 'alta'))
        self.assertIsNone(lineas[2].producto)                  # el código que «eligió» no estaba entre los candidatos
        self.assertIn(self.glifo_l, lineas[2].candidatos)
        self.assertEqual(lineas[2].cantidad, 2)                # 2,5 → se redondea y se avisa
        self.assertIn('se redondeó', lineas[2].nota)
        # En el paso 2 solo van las líneas sin código exacto, con sus candidatos (no el inventario completo)
        texto_paso2 = llamada.call_args_list[1].args[1][0]['text']
        self.assertNotIn('Línea 0', texto_paso2)
        self.assertIn('GLI-48 | Glifosato 48% galón', texto_paso2)
        self.assertNotIn('U46', texto_paso2)
        uso = UsoIA.todos.get()
        self.assertEqual((uso.tokens_entrada, uso.tokens_salida), (2000, 400))
        self.assertEqual(uso.costo_usd, Decimal('0.001600'))     # (2000 × 0,30 + 400 × 2,50) / 1 000 000

    def test_todo_con_codigo_exacto_no_llama_al_segundo_paso(self):
        with self.respuestas({'lineas': [{'texto': 'Urea', 'codigo': 'u46', 'cantidad': 1}]}) as llamada:
            r = self.client.post(self.url, {'texto': 'x'})
        self.assertEqual(llamada.call_count, 1)
        self.assertEqual(r.context['resultado'].lineas[0].producto, self.urea)

    def test_fotos_y_pdf_van_a_la_ia_y_no_se_guardan(self):
        foto = SimpleUploadedFile('pedido.jpg', b'\xff\xd8\xffFOTO', content_type='image/jpeg')
        pdf = SimpleUploadedFile('oc.pdf', b'%PDF-1.4', content_type='application/pdf')
        with self.respuestas({'lineas': [{'texto': 'urea', 'codigo': 'U46', 'cantidad': 3}]}) as llamada:
            r = self.client.post(self.url, {'texto': '', 'archivos': [foto, pdf]})
        partes = llamada.call_args_list[0].args[1]
        self.assertEqual([p['inline_data']['mime_type'] for p in partes if 'inline_data' in p],
                         ['image/jpeg', 'application/pdf'])
        self.assertEqual(r.status_code, 200)
        uso = UsoIA.todos.get()
        self.assertEqual((uso.origen, uso.archivos), (UsoIA.Origen.ARCHIVO, 2))

    def test_tipo_no_permitido_y_demasiados_archivos(self):
        txt = SimpleUploadedFile('a.exe', b'MZ', content_type='application/octet-stream')
        self.assertContains(self.client.post(self.url, {'archivos': [txt]}), 'solo se aceptan')
        muchos = [SimpleUploadedFile(f'{i}.jpg', b'\xff\xd8', content_type='image/jpeg') for i in range(6)]
        self.assertContains(self.client.post(self.url, {'archivos': muchos}), 'Máximo 5')

    def test_error_de_la_ia_se_registra_y_se_avisa(self):
        with mock.patch.object(gemini, 'json_estructurado', side_effect=gemini.ErrorIA('La IA no respondió bien (503).')):
            r = self.client.post(self.url, {'texto': 'urea'})
        self.assertContains(r, 'no respondió bien')
        uso = UsoIA.todos.get()
        self.assertFalse(uso.ok)


class CatalogoTests(BaseIA):
    def test_busqueda_sin_acentos_y_por_prefijo(self):
        with self.empresa_ctx():
            cat = carga_ia.catalogo(self.perfil)
        self.assertEqual(cat.candidatos(carga_ia.Linea(texto='glifos 48 galon'))[0], self.glifo)
        self.assertEqual(cat.exacto('gli 48'), self.glifo)
        self.assertEqual(cat.candidatos(carga_ia.Linea(texto='')), [])


class InventarioRealTests(BaseIA):
    """Pedido real de discos de antibiograma (nombres mal escritos y con concentraciones distintas)."""
    CATALOGO = [('AK-SDA', 'AMIKACINA 30mcg x50 DSCOS'), ('AMP-SDA', 'AMPICILIN 10 mcg x50 DISCOS'),
                ('AMC-SDA', 'AMOXICILINA AC CLAVULANICO 10mcg x50 DISCOS'),
                ('SAM-SDA', 'AMPICILIN SULBACTAM 10/10 mcg x50 DISCOS'), ('ATM-SDA', 'AZTREONAM 30mcg x50 DISCOS'),
                ('IPM-SDA', 'IMIPENEM 10mcg x50 DISCOS'), ('MRP-SDA', 'MEROPENEM 10mcg x50 DISCOS'),
                ('SXT-SDA', 'SULFATRIMETROPIM 25mcg x50 DISCOS'), ('OFL-SDA', 'OFLOXACINO 5 MCG x50 DISCOS'),
                ('NOR-SDA', 'NORFLOXACINA 10mcg x50 DISCOS'), ('LEV-SDA', 'LEVOFLOXACINA 5mcg x50 DISCOS'),
                ('CXM-SDA', 'CEFUROXIMA 30mcg x50 DISCOS'), ('CTX-SDA', 'CEFOTAXIMA 30mcg x50 DISCOS'),
                ('MH-ACCU', 'MUELLER HINTON AGAR x 500 gr'), ('BAS-LIO', 'BLOOD BASE AGAR x500gr')]

    def test_el_correcto_queda_primero(self):
        with self.empresa_ctx():
            un = Unidad.objects.get(abreviatura='UN')
            for codigo, nombre in self.CATALOGO:
                Producto.objects.create(codigo=codigo, nombre=nombre, categoria=self.cat, unidad=un)
            cat = carga_ia.catalogo(self.perfil)
        for pedido, esperado in [('AZTREONAN 30 MCG X 50 DISCOS', 'ATM-SDA'), ('AMIKACINA 30 MCG X 50 DISCOS', 'AK-SDA'),
                                 ('IMIPENEN 10 MCG X 50 DISCOS', 'IPM-SDA'), ('MEROPENEN 10 MCG X 50 DISCOS', 'MRP-SDA'),
                                 ('TRIMETROPIN SULFA 25 MCG X 50 DISCOS', 'SXT-SDA'),
                                 ('OFLOXACINA X 50 DISCOS', 'OFL-SDA'), ('AMPICILINA X 50 DISCOS', 'AMP-SDA'),
                                 ('AMPICILINA SULBACTAM X 50 DISCOS', 'SAM-SDA'), ('CEFUROXIME X 50 DISCOS', 'CXM-SDA'),
                                 ('Agar Muller Hinton', 'MH-ACCU')]:
            with self.subTest(pedido):
                self.assertEqual(cat.candidatos(carga_ia.Linea(texto=pedido))[0].codigo, esperado)
        self.assertEqual(cat.candidatos(carga_ia.Linea(texto='Hemoglobina soluble')), [])

    def test_sin_cantidad_y_grupo(self):
        lineas = carga_ia._lineas_de({'lineas': [{'texto': 'Agar CLED', 'cantidad': 0, 'grupo': 'Bacteriología'}]})
        self.assertEqual((lineas[0].cantidad, lineas[0].grupo), (1, 'Bacteriología'))
        self.assertIn('no dice la cantidad', lineas[0].nota)


class PresentacionesTests(BaseIA):
    def test_cajas_se_cuentan_en_unidades_con_aviso(self):
        x = carga_ia._lineas_de({'lineas': [{'texto': 'PH AN30 1X6 LT', 'cantidad': 2, 'unidad': 'Caj'},
                                            {'texto': 'MAGNEZINC 1X4 GL', 'cantidad': 1, 'unidad': 'Uni'}]})
        self.assertEqual((x[0].cantidad, x[1].cantidad), (12, 1))
        self.assertIn('2 cajas de 6', x[0].nota)

    def test_unidades_escritas_de_otra_forma(self):
        self.assertEqual(carga_ia.normalizar('Vida Forte 20LT BIDON'), 'vida forte 20 l bidon')
        self.assertEqual(carga_ia.normalizar('Subiol 30GRS'), 'subiol 30 g')

    def test_duplicado_sin_precio_va_despues(self):
        with self.empresa_ctx():
            un = Unidad.objects.get(abreviatura='UN')
            Producto.objects.create(codigo='B1', nombre='Crixus bs', categoria=self.cat, unidad=un)
            con = Producto.objects.create(codigo='B2', nombre='Crixus bs', categoria=self.cat, unidad=un,
                                          precio_venta_usd=Decimal('33'))
            cat = carga_ia.catalogo(self.perfil)
        self.assertEqual(cat.candidatos(carga_ia.Linea(texto='CRIXUS BS GL (INSUBIOL)'))[0], con)
