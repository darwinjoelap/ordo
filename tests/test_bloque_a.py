"""
Paridad con BioLifeVentas (bloque A): facturación, reporte de facturación, lotes en el PDF,
analítica de ventas y lista de ventas por fechas.
"""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from apps.inventario import servicios as inventario
from apps.inventario.models import Lote
from apps.ventas import reportes, servicios as ventas
from apps.ventas.models import ItemPresupuesto, Presupuesto
from apps.ventas.pdf import _celdas_lote, lotes_por_item

from .test_fase5 import HOY, Base

E = Presupuesto.Estado


class FacturacionTests(Base):
    def facturar(self, p, numero='F-001', control='00-001', facturado=True):
        with self.empresa_ctx():
            return ventas.registrar_facturacion(p, facturado, numero, control)

    def test_registrar_corregir_y_quitar(self):
        p = self.venta([(self.prod, 1)])
        p = self.facturar(p)
        self.assertEqual((p.facturado, p.numero_factura, p.numero_control, p.fecha_facturacion),
                         (True, 'F-001', '00-001', HOY))
        p = self.facturar(p, numero='F-002')
        self.assertEqual(p.numero_factura, 'F-002')
        p = self.facturar(p, facturado=False)
        self.assertEqual((p.facturado, p.numero_factura, p.fecha_facturacion), (False, '', None))

    def test_validaciones(self):
        p = self.venta([(self.prod, 1)])
        with self.assertRaises(ventas.ErrorVenta):
            self.facturar(p, numero='  ')
        self.facturar(p, numero='F-9')
        otra = self.venta([(self.prod, 1)])
        with self.assertRaisesMessage(ventas.ErrorVenta, p.numero):     # número de factura repetido
            self.facturar(otra, numero='f-9')
        self.perfil.requiere_validacion = True
        self.perfil.save()
        sin_validar = self.venta([(self.prod, 1)])
        with self.assertRaises(ventas.ErrorVenta):
            self.facturar(sin_validar, numero='F-10')

    def test_pantalla_y_permisos(self):
        p = self.venta([(self.prod, 1)])
        url = reverse('ventas:facturacion', args=[p.pk])
        self.client.force_login(self.vendedor)
        self.assertNotContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'name="numero_factura"')
        self.assertEqual(self.client.post(url, {'facturado': '1', 'numero_factura': 'X'}).status_code, 403)
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'name="numero_factura"')
        self.client.post(url, {'facturado': '1', 'numero_factura': 'F-77', 'numero_control': 'C-1',
                               'fecha_facturacion': '2026-01-15'})
        p.refresh_from_db()
        self.assertEqual((p.numero_factura, str(p.fecha_facturacion)), ('F-77', '2026-01-15'))


class ReporteFacturacionTests(Base):
    def setUp(self):
        super().setUp()
        self.a = self.venta([(self.prod, 2)])          # 46,40
        self.b = self.venta([(self.prod, 1)])          # 23,20
        with self.empresa_ctx():
            ventas.registrar_facturacion(self.a, True, 'F-1', 'C-1')
            ventas.registrar_pago(self.b, True, 'ZELLE')
            ventas.devolver(self.a, self.dueno, {ItemPresupuesto.todos.get(presupuesto=self.a).pk: (1, True)}, 'x')

    def filtros(self, **kw):
        f = {'desde': HOY, 'hasta': HOY, 'por': 'venta', 'factura': '', 'pago': '', 'vendedor': ''}
        f.update(kw)
        return f

    def test_filtros_y_totales_netos(self):
        with self.empresa_ctx():
            base = Presupuesto.objects.all()
            t = reportes.totales_facturacion(reportes.filtrar_facturacion(base, self.filtros()))
            self.assertEqual((t['n'], t['neto'], t['fact'], t['sin'], t['pag']),
                             (2, Decimal('46.40'), Decimal('23.20'), Decimal('23.20'), Decimal('23.20')))
            solo = reportes.filtrar_facturacion(base, self.filtros(factura='si'))
            self.assertEqual(list(solo), [self.a])
            self.assertEqual(list(reportes.filtrar_facturacion(base, self.filtros(factura='no', pago='si'))), [self.b])
            por_factura = reportes.filtrar_facturacion(base, self.filtros(por='factura'))
            self.assertEqual(list(por_factura), [self.a])
            ayer = reportes.filtrar_facturacion(base, self.filtros(desde=HOY - timedelta(days=5),
                                                                    hasta=HOY - timedelta(days=1)))
            self.assertFalse(ayer.exists())

    def test_pantalla_pdf_excel_y_permisos(self):
        url = reverse('ventas:reporte_facturacion')
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.dueno)
        r = self.client.get(url)
        self.assertContains(r, 'F-1')
        self.assertContains(r, self.b.numero)
        self.assertTrue(self.client.get(url + '?formato=pdf').content.startswith(b'%PDF'))
        xlsx = self.client.get(url + '?formato=excel&factura=si')
        self.assertTrue(xlsx.content.startswith(b'PK'))
        from io import BytesIO

        from openpyxl import load_workbook
        hoja = load_workbook(BytesIO(xlsx.content)).active
        self.assertEqual(hoja['F4'].value, 'F-1')
        self.assertIsNone(hoja['B5'].value)                  # solo la facturada


class LotesEnPdfTests(Base):
    def presupuesto_emitido(self, cantidad, producto=None):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, producto or self.prod, cantidad, None, self.perfil, True)
            return ventas.emitir(p)

    def info(self, p):
        items = list(ItemPresupuesto.todos.filter(presupuesto=p).select_related('producto__marca'))
        with self.empresa_ctx():
            return items, lotes_por_item(p, items)

    def test_referencial_fefo_en_la_misma_linea(self):
        p = self.presupuesto_emitido(7)
        items, info = self.info(p)
        d = info[items[0].pk]
        self.assertTrue(d['referencial'])
        self.assertEqual([(n, c) for n, _, c in d['lotes']], [('L-CERCA', 5), ('L-LEJOS', 2)])
        self.assertEqual(d['falta'], 0)
        lote, venc = _celdas_lote(items[0].producto, d)
        self.assertEqual(lote.text, 'L-CERCA (5)<br/>L-LEJOS (2)')       # misma fila, un renglón por lote
        self.assertEqual(venc.text.count('<br/>'), 1)

    def test_sin_stock_suficiente(self):
        p = self.presupuesto_emitido(12)
        items, info = self.info(p)
        self.assertEqual(info[items[0].pk]['falta'], 2)
        self.assertIn('SIN STOCK</b> (faltan 2)', _celdas_lote(items[0].producto, info[items[0].pk])[0].text)

    def test_venta_usa_los_lotes_reales(self):
        p = self.venta([(self.prod, 3)])
        items, info = self.info(p)
        self.assertFalse(info[items[0].pk]['referencial'])
        self.assertEqual([(n, c) for n, _, c in info[items[0].pk]['lotes']], [('L-CERCA', 3)])

    def test_producto_sin_lotes_no_muestra_nada(self):
        p = self.presupuesto_emitido(1, producto=self.equipo)
        items, info = self.info(p)
        self.assertNotIn(items[0].pk, info)
        self.assertEqual(_celdas_lote(items[0].producto, None)[0].text, 'N/A')

    def test_un_solo_lote_sin_parentesis(self):
        p = self.presupuesto_emitido(3)
        items, info = self.info(p)
        self.assertEqual(_celdas_lote(items[0].producto, info[items[0].pk])[0].text, 'L-CERCA')

    def test_lote_vencido_no_se_ofrece_ni_se_aparta(self):
        Lote.todos.filter(numero_lote='L-CERCA').update(fecha_vencimiento=HOY - timedelta(days=1))
        p = self.presupuesto_emitido(6)
        items, info = self.info(p)
        self.assertEqual([(n, c) for n, _, c in info[items[0].pk]['lotes']], [('L-LEJOS', 5)])
        self.assertEqual(info[items[0].pk]['falta'], 1)
        with self.empresa_ctx():
            with self.assertRaises(inventario.StockInsuficiente):
                inventario.apartar_fefo(self.prod, 6, self.dueno)
            reservas = inventario.apartar_fefo(self.prod, 2, self.dueno)
        self.assertEqual([r.lote.numero_lote for r in reservas], ['L-LEJOS'])

    def test_pdf_se_genera_en_las_tres_monedas(self):
        p = self.presupuesto_emitido(7)
        self.client.force_login(self.vendedor)
        for moneda in ('usd', 'bs', 'ambas'):
            r = self.client.get(reverse('ventas:pdf', args=[p.pk]) + f'?moneda={moneda}')
            self.assertTrue(r.content.startswith(b'%PDF'), moneda)


class MontosBsTests(Base):
    def test_total_bs_cuadra_con_las_lineas(self):
        from apps.tasas.models import TasaCambio
        from apps.ventas.models import desglose_bs
        TasaCambio.objects.filter(fecha=HOY).update(bs_por_usd=Decimal('36.5021'))
        from django.core.cache import cache
        cache.clear()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 3, Decimal('19.99'), self.perfil, True)
            ventas.agregar_item(p, self.equipo, 1, None, self.perfil, True)
            ventas.actualizar_items(p, {}, [], self.perfil, True, descuento_pct=Decimal('7'))
            p = ventas.emitir(p)
            items = list(ItemPresupuesto.objects.filter(presupuesto=p))
        d = desglose_bs(p, items)
        self.assertEqual(p.tasa_bs, Decimal('36.5021'))
        self.assertEqual(d['lineas'][items[0].pk], Decimal('2189.04'))     # 729,68 × 3 (sin redondear el precio daría 2189,03)
        self.assertEqual(sum(d['lineas'].values()), d['subtotal'])
        self.assertEqual(p.total_bs, d['total'])
        self.assertEqual(d['total'], d['base'] + d['iva'])


class AnaliticaTests(Base):
    def setUp(self):
        super().setUp()
        self.v1 = self.venta([(self.prod, 3), (self.equipo, 1)], descuento='10')   # (60+200)·0,9 = 234
        self.v2 = self.venta([(self.prod, 2)], vendedor=self.vendedor2)            # 40
        devuelta = self.venta([(self.prod, 1)])
        with self.empresa_ctx():
            ventas.devolver(self.v1, self.dueno, {ItemPresupuesto.todos.get(presupuesto=self.v1, producto=self.prod).pk:
                                                  (1, True)}, 'x')                 # −18
            ventas.devolver(devuelta, self.dueno, {ItemPresupuesto.todos.get(presupuesto=devuelta).pk: (1, True)}, 'x')

    def test_calculo_neto_de_devoluciones(self):
        with self.empresa_ctx():
            r = reportes.calcular(Presupuesto.objects.filter(estado__in=[E.VALIDADA, E.DEVUELTA]))
        self.assertEqual(r.vendido, Decimal('256.00'))          # 36 + 180 + 40
        self.assertEqual(r.costo, Decimal('140.00'))            # 4·10 + 100
        self.assertEqual((r.n_ventas, r.unidades), (2, 5))
        self.assertEqual(r.ticket, Decimal('128.00'))
        self.assertEqual(r.margen, Decimal('45.3'))
        top = reportes._ranking(r.productos)
        self.assertEqual(top[0]['nombre'], 'Centrífuga')
        self.assertEqual(top[1]['unidades'], 4)

    def test_filtro_por_categoria(self):
        with self.empresa_ctx():
            r = reportes.calcular(Presupuesto.objects.filter(estado=E.VALIDADA), categoria_id=self.cat2.pk)
        self.assertEqual((r.vendido, r.n_ventas), (Decimal('180.00'), 1))

    def test_dueno_ve_todo_con_utilidad(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:reportes'))
        self.assertEqual(r.context['r'].vendido, Decimal('256.00'))
        self.assertContains(r, 'Utilidad bruta')
        self.assertContains(r, 'Por vendedor')

    def test_vendedor_solo_ve_lo_suyo_sin_costos(self):
        self.client.force_login(self.vendedor2)
        r = self.client.get(reverse('ventas:reportes') + f'?vendedor={self.vendedor.pk}')   # se ignora
        self.assertEqual(r.context['r'].vendido, Decimal('40.00'))
        self.assertNotContains(r, 'Utilidad bruta')
        self.assertNotContains(r, 'Por vendedor')

    def test_rango_sin_ventas(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:reportes') + '?desde=2020-01-01&hasta=2020-01-31')
        self.assertEqual(r.context['r'].n_ventas, 0)
        self.assertContains(r, 'Sin datos en el período')


class ListaPorFechasTests(Base):
    def test_filtra_ventas_por_fecha_de_validacion(self):
        p = self.venta([(self.prod, 1)])
        self.client.force_login(self.dueno)
        url = reverse('ventas:lista')
        r = self.client.get(url, {'estado': 'ventas', 'desde': HOY.isoformat(), 'hasta': HOY.isoformat()})
        self.assertContains(r, p.numero)
        r = self.client.get(url, {'estado': 'ventas', 'desde': (HOY + timedelta(days=1)).isoformat()})
        self.assertNotContains(r, p.numero)
        r = self.client.get(url, {'desde': 'basura'})             # fecha inválida: se ignora
        self.assertContains(r, p.numero)
