"""Pantalla del presupuesto: Bs en borrador (tasa referencial), sin stock en rojo, papelera, sin IVA y búsqueda."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from apps.inventario.models import Producto, Unidad
from apps.tasas.models import TasaCambio
from apps.ventas import servicios as ventas
from apps.ventas.models import ItemPresupuesto

from .test_fase5 import Base as BaseVentas

from .test_fase5 import HOY, Base


class PresupuestoPantallaTests(Base):
    def setUp(self):
        super().setUp()
        cache.clear()
        TasaCambio.objects.all().delete()
        TasaCambio.objects.create(fecha=HOY, bs_por_usd=Decimal('100'))
        cache.clear()
        with self.empresa_ctx():
            self.agotado = Producto.objects.create(codigo='AG', nombre='Agotado X', categoria=self.cat2,
                                                   unidad=Unidad.objects.get(abreviatura='UN'),
                                                   precio_venta_usd=Decimal('10'))
            self.p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(self.p, self.prod, 2, None, self.perfil, True)      # 2 × 20
        self.client.force_login(self.vendedor)
        self.url = reverse('ventas:detalle', args=[self.p.pk])

    def test_borrador_muestra_bs_con_la_tasa_de_hoy_sin_guardarla(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'Bs 4\xa0000,00')               # subtotal de la línea: 2 × 20 × 100
        self.assertContains(r, 'referencial')
        self.p.refresh_from_db()
        self.assertIsNone(self.p.tasa_bs)                     # no se congela hasta emitir
        self.assertContains(r, 'moneda=bs')                   # PDF «Solo Bs» disponible desde el borrador

    def test_pdf_solo_bs_en_borrador(self):
        with mock.patch('apps.ventas.views.presupuesto_pdf', return_value=b'%PDF') as pdf:
            self.client.get(reverse('ventas:pdf', args=[self.p.pk]), {'moneda': 'bs'})
            p, = pdf.call_args.args[:1]
            self.assertEqual((p.tasa_bs, pdf.call_args.kwargs['moneda'], pdf.call_args.kwargs['tasa_referencial']),
                             (Decimal('100'), 'bs', True))
        for moneda in ('bs', 'usd', 'ambas'):
            r = self.client.get(reverse('ventas:pdf', args=[self.p.pk]), {'moneda': moneda})
            self.assertTrue(r.content.startswith(b'%PDF'))

    def test_sin_stock_en_rojo_al_buscar_y_al_agregar(self):
        r = self.client.get(reverse('ventas:buscar_productos', args=[self.p.pk]), {'q': 'Agotado'})
        self.assertContains(r, 'SIN STOCK')
        self.assertContains(r, 'btn btn-success')
        self.assertContains(r, 'Agregar')
        r = self.client.post(reverse('ventas:agregar_item', args=[self.p.pk]),
                             {'producto': self.agotado.pk, 'cantidad': 1}, follow=True)
        self.assertContains(r, 'sin stock suficiente')
        self.assertContains(r, 'text-danger fw-bold')
        self.assertContains(r, 'SIN STOCK')

    def test_papelera_quita_el_producto(self):
        r = self.client.get(self.url)
        item = ItemPresupuesto.todos.get(presupuesto=self.p)
        self.assertContains(r, f'name="quitar_{item.pk}"')
        self.assertContains(r, 'bi-trash')
        self.assertNotContains(r, 'type="checkbox" class="form-check-input" name="quitar_')
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]), {f'quitar_{item.pk}': '1'})
        self.assertFalse(ItemPresupuesto.todos.filter(presupuesto=self.p).exists())

    def test_sin_iva_quita_la_fila_del_iva(self):
        self.assertContains(self.client.get(self.url), 'IVA (16')
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]), {'iva_enviado': '1', 'sin_iva': '1'})
        r = self.client.get(self.url)
        self.assertNotContains(r, 'IVA (')
        self.assertNotContains(r, 'Exento')
        self.assertContains(r, 'requestSubmit')               # el interruptor guarda al tocarlo


class NombreArchivoPdfTests(Base):
    def test_nombre_corto_y_archivo(self):
        from datetime import date

        from apps.core.pdf import nombre_archivo, nombre_corto
        self.assertEqual(nombre_corto('Laboratorio Clínico La Esperanza, C.A.'), 'Laboratorio-Clinico-Esperanza')
        self.assertEqual(nombre_corto('Distribuidora Farmacéutica Internacional de Occidente'),
                         'Distribuidora-Farmaceutica')
        self.assertEqual(nombre_corto('Clínica Sol'), 'Clinica-Sol')
        self.assertEqual(nombre_archivo('202600343', 'Clinica-Sol', date(2026, 10, 2)),
                         '202600343_Clinica-Sol_2026-10-02.pdf')
        self.assertEqual(nombre_archivo('P-2026-00001', '', date(2026, 1, 5)), 'P-2026-00001_2026-01-05.pdf')

    def test_presupuesto_numero_cliente_fecha_y_sin_cache(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
            p = ventas.guardar(p)
        self.client.force_login(self.vendedor)
        url = reverse('ventas:pdf', args=[p.pk])
        r = self.client.get(url)
        esperado = f'inline; filename="{p.numero}_Clinica-Sol_{p.fecha:%Y-%m-%d}.pdf"'
        self.assertEqual(r['Content-Disposition'], esperado)
        self.assertIn('no-store', r['Cache-Control'])
        # Tras modificar el presupuesto: mismo nombre de archivo (reemplaza al anterior), contenido nuevo
        with self.empresa_ctx():
            ventas.agregar_item(p, self.equipo, 1, None, self.perfil, True)
        r2 = self.client.get(url)
        self.assertEqual(r2['Content-Disposition'], esperado)
        self.assertNotEqual(r.content, r2.content)


class OrdenAlfabeticoTests(Base):
    def test_productos_del_presupuesto_en_orden_alfabetico(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)       # Glucosa (se agrega primero)
            ventas.agregar_item(p, self.equipo, 1, None, self.perfil, True)     # Centrífuga
        self.client.force_login(self.vendedor)
        html = self.client.get(reverse('ventas:detalle', args=[p.pk])).content.decode()
        tabla = html[html.index('ordo-items'):]
        self.assertLess(tabla.index('Centrífuga'), tabla.index('Glucosa'))
        from apps.ventas import pdf as modulo
        with mock.patch.object(modulo, 'desglose_bs', wraps=modulo.desglose_bs) as espia:
            self.assertTrue(self.client.get(reverse('ventas:pdf', args=[p.pk])).content.startswith(b'%PDF'))
            self.assertEqual([i.producto.nombre for i in espia.call_args.args[1]], ['Centrífuga', 'Glucosa'])


class UnidadYObservacionTests(BaseVentas):
    def setUp(self):
        super().setUp()
        from apps.ventas import servicios as ventas
        with self.empresa_ctx():
            self.p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(self.p, self.prod, 3, None, self.perfil, True)
            self.item = self.p.items.get()
        self.client.force_login(self.vendedor)
        self.url = reverse('ventas:detalle', args=[self.p.pk])

    def textos_pdf(self):
        from unittest import mock
        from apps.ventas import pdf as pdf_ventas
        textos, real = [], pdf_ventas.Paragraph
        with mock.patch.object(pdf_ventas, 'Paragraph', side_effect=lambda t, *a, **k: (textos.append(str(t)), real(t, *a, **k))[1]):
            self.client.get(reverse('ventas:pdf', args=[self.p.pk]))
        return textos

    def test_unidad_en_pantalla_y_pdf(self):
        unidad = self.prod.unidad.abreviatura
        self.assertContains(self.client.get(self.url), f'<div class="small text-muted text-end">{unidad}</div>', html=False)
        self.assertTrue(any(t.startswith('3<br/>') and unidad in t for t in self.textos_pdf()))

    def test_observacion_desactivada_no_aparece(self):
        self.assertNotContains(self.client.get(self.url), f'name="obs_{self.item.pk}"')

    def test_observacion_por_producto(self):
        self.perfil.observaciones_por_producto = True
        self.perfil.save()
        self.assertContains(self.client.get(self.url), f'name="obs_{self.item.pk}"')
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]),
                         {f'cantidad_{self.item.pk}': '3', f'obs_{self.item.pk}': '  1 L   por hectárea  '})
        self.item.refresh_from_db()
        self.assertEqual(self.item.observacion, '1 L por hectárea')
        self.assertTrue(any('1 L por hectárea' in t and '<i>' in t for t in self.textos_pdf()))
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]), {f'cantidad_{self.item.pk}': '4'})
        self.item.refresh_from_db()
        self.assertEqual((self.item.cantidad, self.item.observacion), (4, '1 L por hectárea'))   # sin el campo no se borra


class ColumnasLoteTests(BaseVentas):
    def tabla(self, producto):
        from unittest import mock
        from apps.ventas import pdf as pdf_ventas
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, producto, 1, None, self.perfil, True)
        anchos = []
        real = pdf_ventas.Table
        with mock.patch.object(pdf_ventas, 'Table', side_effect=lambda f, *a, **k: (anchos.append(len(f[0])), real(f, *a, **k))[1]):
            pdf_ventas.presupuesto_pdf(p, self.empresa)
        return anchos

    def test_sin_lote_ni_vencimiento_no_salen_las_columnas(self):
        self.assertIn(5, self.tabla(self.equipo))        # Cód, Descripción, Cant, P. Unit, Subtotal (sin tasa: solo USD)
        self.assertIn(7, self.tabla(self.prod))          # + Lote y F. Venc.
