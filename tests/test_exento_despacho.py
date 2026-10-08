"""IVA con productos exentos (E), nota de despacho y «&» en los PDF."""
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.core.pdf import texto_seguro
from apps.ventas import pdf as pdf_ventas
from apps.ventas import servicios as ventas
from apps.ventas.models import Despacho, Presupuesto, partir_iva

from .test_fase5 import Base


class AmpersandTests(Base):
    def test_escapa_datos_y_respeta_marcado(self):
        self.assertEqual(texto_seguro('Agroservicios J&M'), 'Agroservicios J&amp;M')
        self.assertEqual(texto_seguro('<b>A&B</b><br/>x &amp; y < 5'), '<b>A&amp;B</b><br/>x &amp; y &lt; 5')

    def test_encabezado_con_ampersand(self):
        self.perfil.nombre_comercial = 'Agroservicios J&M'
        self.perfil.razon_social = 'Agroservicios J&M, C.A <x'
        self.perfil.save()
        from apps.core.pdf import encabezado_empresa
        tabla = encabezado_empresa(self.empresa, titulo='PRUEBA')[0]
        textos = [par.getPlainText() for par in tabla._cellvalues[0][-2]]
        self.assertEqual(textos[0], 'Agroservicios J&M')
        self.assertEqual(textos[1], 'Agroservicios J&M, C.A <x')


class ExentoTests(Base):
    """Glucosa $20 (se marca exenta) · Centrífuga $200 (gravada) · IVA 16 %."""

    def setUp(self):
        super().setUp()
        with self.empresa_ctx():
            self.prod.exento_iva = True
            self.prod.save()

    def borrador(self, items, descuento=None):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            for prod, cant in items:
                ventas.agregar_item(p, prod, cant, None, self.perfil, True)
            if descuento is not None:
                ventas.actualizar_items(p, {}, [], self.perfil, True, descuento_pct=Decimal(descuento))
            return Presupuesto.objects.get(pk=p.pk)

    def test_iva_solo_sobre_lo_gravado(self):
        p = self.borrador([(self.prod, 5), (self.equipo, 1)])          # 100 exento + 200 gravado
        self.assertEqual((p.subtotal_usd, p.base_usd, p.exento_usd), (Decimal('300.00'), Decimal('300.00'), Decimal('100.00')))
        self.assertEqual(p.iva_usd, Decimal('32.00'))
        self.assertEqual(p.total_usd, Decimal('332.00'))

    def test_descuento_se_reparte(self):
        p = self.borrador([(self.prod, 5), (self.equipo, 1)], descuento='10')
        self.assertEqual((p.base_usd, p.exento_usd, p.iva_usd, p.total_usd),
                         (Decimal('270.00'), Decimal('90.00'), Decimal('28.80'), Decimal('298.80')))

    def test_todo_exento_y_sin_exentos(self):
        self.assertEqual(self.borrador([(self.prod, 2)]).iva_usd, 0)
        p = self.borrador([(self.equipo, 1)])
        self.assertEqual((p.exento_usd, p.iva_usd), (0, Decimal('32.00')))

    def test_partir_iva(self):
        m = partir_iva(Decimal('300'), Decimal('100'), Decimal('0'), Decimal('16'))
        self.assertEqual((m['exento'], m['gravable'], m['iva'], m['total']),
                         (Decimal('100.00'), Decimal('200.00'), Decimal('32.00'), Decimal('332.00')))

    def test_devolucion_de_exento_no_devuelve_iva(self):
        p = self.venta([(self.prod, 5), (self.equipo, 1)])
        with self.empresa_ctx():
            item = p.items.get(producto=self.prod)
            dev = ventas.devolver(p, self.dueno, {item.pk: (2, True)}, 'Sobraron')
        self.assertEqual((dev.base_usd, dev.iva_usd, dev.total_usd), (Decimal('40.00'), 0, Decimal('40.00')))

    def test_pantalla_y_pdf_marcan_e(self):
        p = self.borrador([(self.prod, 5), (self.equipo, 1)])
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Exento (E)')
        self.assertContains(r, 'Base imponible')
        textos = []
        real = pdf_ventas.Paragraph
        with mock.patch.object(pdf_ventas, 'Paragraph', side_effect=lambda t, *a, **k: (textos.append(str(t)), real(t, *a, **k))[1]):
            r = self.client.get(reverse('ventas:pdf', args=[p.pk]))
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(any('Glucosa' in t and '(E)' in t for t in textos))
        self.assertFalse(any('Centrífuga' in t and '(E)' in t for t in textos))
        self.assertTrue(any('exento de IVA' in t for t in textos))

    def test_ficha_del_producto(self):
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('inventario:producto_editar', args=[self.prod.pk])), 'name="exento_iva"')


class DespachoTests(Base):
    DATOS = {'transportista': 'Pedro Pérez', 'cedula': 'V-1', 'telefono': '0414', 'vehiculo': 'Toyota Hilux blanca',
             'placa': 'ab123cd', 'empresa_transporte': 'Fletes J&M', 'direccion_entrega': '', 'observaciones': 'Frío',
             'fecha': '2026-10-08', 'con_precios': '1'}

    def test_borrador_no_se_despacha(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
        self.client.force_login(self.vendedor)
        self.assertRedirects(self.client.get(reverse('ventas:despacho', args=[p.pk])), reverse('ventas:detalle', args=[p.pk]))
        self.assertEqual(self.client.get(reverse('ventas:despacho_pdf', args=[p.pk])).status_code, 404)
        with self.empresa_ctx(), self.assertRaises(ventas.ErrorVenta):
            ventas.guardar_despacho(p, self.DATOS, self.vendedor)

    def test_guardar_actualizar_y_pdf(self):
        p = self.venta([(self.prod, 3)])
        self.client.force_login(self.vendedor)
        url = reverse('ventas:despacho', args=[p.pk])
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), url)
        self.assertContains(self.client.get(url), 'Guarda para poder abrir el PDF')
        self.client.post(url, {**self.DATOS, 'placa': ''})
        self.assertFalse(Despacho.todos.exists())
        self.assertRedirects(self.client.post(url, self.DATOS), url)
        d = Despacho.todos.get()
        self.assertEqual((d.presupuesto_id, d.placa, d.con_precios, str(d.fecha)), (p.pk, 'AB123CD', True, '2026-10-08'))
        datos = dict(self.DATOS, placa='XY999'); datos.pop('con_precios')
        self.client.post(url, datos)
        d = Despacho.todos.get()
        self.assertEqual((d.placa, d.con_precios), ('XY999', False))
        for _ in range(2):                                         # sin precios y con precios
            r = self.client.get(reverse('ventas:despacho_pdf', args=[p.pk]))
            self.assertEqual(r['Content-Type'], 'application/pdf')
            self.assertIn(f'Despacho-{p.numero}', r['Content-Disposition'])
            self.assertTrue(r.content.startswith(b'%PDF'))
            Despacho.todos.update(con_precios=True)
        self.assertContains(self.client.get(url), 'Pedro Pérez')

    def test_otro_vendedor_no_lo_ve(self):
        p = self.venta([(self.prod, 1)])
        with self.empresa_ctx():
            ventas.guardar_despacho(p, self.DATOS, self.vendedor)
            self.assertEqual(ventas.transportistas_recientes()[0]['placa'], 'AB123CD')


class SinStockPdfTests(Base):
    """Mi empresa → Documentos → «No mostrar SIN STOCK en los PDF»."""

    def textos_pdf(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            self.prod.maneja_lotes = True
            self.prod.save()
            ventas.agregar_item(p, self.prod, 99999, None, self.perfil, True)       # mucho más de lo que hay
            textos = []
            real = pdf_ventas.Paragraph
            with mock.patch.object(pdf_ventas, 'Paragraph', side_effect=lambda t, *a, **k: (textos.append(str(t)), real(t, *a, **k))[1]):
                pdf_ventas.presupuesto_pdf(p, self.empresa)
        return ' '.join(textos)

    def test_por_defecto_avisa(self):
        self.assertIn('SIN STOCK', self.textos_pdf())

    def test_se_puede_ocultar(self):
        self.perfil.ocultar_sin_stock = True
        self.perfil.save()
        self.empresa.perfil.refresh_from_db()
        self.assertNotIn('SIN STOCK', self.textos_pdf())

    def test_el_dueno_lo_configura(self):
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('empresas:mi_empresa')), 'name="ocultar_sin_stock"')


class ImportarExentoTests(Base):
    def test_columna_exento_en_la_importacion(self):
        from io import BytesIO

        from openpyxl import Workbook

        from apps.inventario import importacion as ip
        from apps.inventario.models import Producto

        def excel(filas, titulos):
            wb = Workbook()
            ws = wb.active
            ws.title = 'Productos'
            ws.append(titulos)
            for f in filas:
                ws.append(f)
            b = BytesIO()
            wb.save(b)
            return b.getvalue()
        with self.empresa_ctx():
            Producto.objects.filter(pk=self.prod.pk).update(exento_iva=True)
            r = ip.validar(excel([['NUEVO', 'Urea', 'Fertilizantes', 'SI'], ['NUEVO2', 'Otro', 'Fertilizantes', None]],
                                 ['codigo', 'nombre', 'categoria', 'exento_iva']))
            self.assertTrue(r.valido, r.errores)
            ip.aplicar(r, self.dueno)
            self.assertTrue(Producto.objects.get(codigo='NUEVO').exento_iva)
            self.assertFalse(Producto.objects.get(codigo='NUEVO2').exento_iva)
            r = ip.validar(excel([[self.prod.codigo, 'Glucosa', 'Reactivos']], ['codigo', 'nombre', 'categoria']))
            ip.aplicar(r, self.dueno)
            self.assertTrue(Producto.objects.get(pk=self.prod.pk).exento_iva)       # sin la columna no cambia
            exportado = ip.exportar_productos(Producto.objects.filter(codigo='NUEVO'))
            r = ip.validar(exportado)
            self.assertTrue(r.productos['NUEVO'].datos['exento_iva'])
