"""Panel de pedido por clasificación (totales y PDF), visor de PDF de la PWA y recepción con productos que no llegaron."""
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.compras import servicios as compras
from apps.compras import sugerencias
from apps.compras.models import ItemOrdenCompra, OrdenCompra
from apps.inventario.models import Categoria, Lote, Producto, Subcategoria, Unidad

from .test_fase3b import ComprasBase


class ClasificacionTests(ComprasBase):
    def setUp(self):
        super().setUp()
        with self.en_empresa():
            un = Unidad.objects.get(abreviatura='UN')
            self.cat_a = Categoria.objects.create(nombre='Analizadores')
            self.sub_q = Subcategoria.objects.create(categoria=self.p1.categoria, nombre='Química')
            self.sub_h = Subcategoria.objects.create(categoria=self.p1.categoria, nombre='Hematología')
            Producto.todos.filter(pk=self.p1.pk).update(subcategoria=self.sub_q)                    # R › Química
            Producto.todos.filter(pk=self.p2.pk).update(subcategoria=self.sub_h, stock_minimo=4)    # R › Hematología
            self.p3 = Producto.objects.create(codigo='P3', nombre='Tres', categoria=self.cat_a, unidad=un,
                                              proveedor_habitual=self.prov, stock_minimo=7)          # Analizadores
            self.p4 = Producto.objects.create(codigo='P4', nombre='Cuatro', categoria=self.p1.categoria, unidad=un,
                                              subcategoria=self.sub_q, stock_minimo=2)               # R › Química

    def test_agrupa_alfabeticamente_con_total_de_unidades(self):
        with self.en_empresa():
            grupos = sugerencias.calcular(30)
            clas = sugerencias.por_clasificacion(grupos)
            self.assertEqual([c for c, _, _ in clas], ['Analizadores', 'R › Hematología', 'R › Química'])
            totales = {c: t for c, _, t in clas}
            self.assertEqual(totales['Analizadores'], 7)
            self.assertEqual(totales['R › Hematología'], 4)
            self.assertEqual(totales['R › Química'], 30 + 2)        # p1: 1/día × 30 días; p4: stock mínimo
            quimica = [s.producto.nombre for s, _ in clas[2][1]]
            self.assertEqual(quimica, ['Cuatro', 'Uno'])            # productos en orden alfabético
            # Con las cantidades escritas en el panel: solo entran los productos indicados
            clas = sugerencias.por_clasificacion(grupos, {self.p1.pk: 12, self.p3.pk: 0})
            self.assertEqual([(c, t) for c, _, t in clas], [('R › Química', 12)])

    def test_panel_muestra_totales_por_clasificacion(self):
        r = self.client.get(reverse('compras:panel_pedido'), {'dias': 30})
        self.assertContains(r, 'Total por clasificación')
        self.assertContains(r, 'data-clas="R › Química"')
        self.assertContains(r, 'Total del proveedor')
        self.assertContains(r, reverse('compras:panel_pedido_pdf') + '?dias=30')
        html = r.content.decode()
        self.assertLess(html.index('Analizadores'), html.index('R › Hematología'))

    def test_pdf_del_panel(self):
        url = reverse('compras:panel_pedido_pdf')
        r = self.client.get(url, {'dias': 30})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        # Lo que recibe el PDF: clasificaciones en orden, cantidades del panel (?c=) y texto de filtros
        with mock.patch('apps.compras.views.panel_pedido_pdf', return_value=b'%PDF') as pdf:
            self.client.get(url, {'dias': 45})
            _, clas, dias, filtros = pdf.call_args.args
            self.assertEqual(([c for c, _, _ in clas], dias, filtros),
                             (['Analizadores', 'R › Hematología', 'R › Química'], 45, ''))
            self.client.get(url, {'dias': 30, 'categoria': self.cat_a.pk, 'c': f'{self.p3.pk}:25,basura,{self.p1.pk}:9'})
            _, clas, dias, filtros = pdf.call_args.args
            self.assertEqual([(c, t) for c, _, t in clas], [('Analizadores', 25)])   # p1 queda fuera por el filtro
            self.assertEqual(filtros, 'Categoría: Analizadores')
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(url).status_code, 403)


class VisorPdfTests(ComprasBase):
    def test_visor_solo_rutas_internas(self):
        r = self.client.get(reverse('core:visor_pdf'), {'u': '/ventas/5/pdf/?moneda=usd'})
        self.assertContains(r, 'data-url="/ventas/5/pdf/?moneda=usd"')
        self.assertContains(r, 'pdf.min')
        for malo in ('', 'https://malo.com/x.pdf', '//malo.com/x.pdf', '/\\malo.com', 'javascript:alert(1)'):
            self.assertEqual(self.client.get(reverse('core:visor_pdf'), {'u': malo}).status_code, 404, malo)

    def test_enlaces_pdf_marcados_para_el_visor(self):
        with self.en_empresa():
            orden = compras.crear_orden(self.prov, self.dueno, [(self.p1, 3, Decimal('10'))])
        self.assertContains(self.client.get(reverse('compras:detalle', args=[orden.pk])), 'data-pdf', count=2)
        self.assertContains(self.client.get(reverse('inventario:lista_precios')), 'data-pdf')


class RecepcionConFaltantesTests(ComprasBase):
    """En BioLifeVentas, si un producto de la orden no llegaba, no dejaba registrar la recepción."""

    def setUp(self):
        super().setUp()
        with self.en_empresa():
            Producto.todos.filter(pk=self.p2.pk).update(maneja_vencimiento=True)
            self.orden = compras.crear_orden(self.prov, self.dueno, [(self.p1, 10, Decimal('9')),
                                                                     (self.p2, 4, Decimal('3'))])
            compras.cambiar_estado(self.orden, 'ENVIADA')
            self.i1, self.i2 = (ItemOrdenCompra.objects.get(orden=self.orden, producto=p) for p in (self.p1, self.p2))
        self.url = reverse('compras:recibir', args=[self.orden.pk])

    def estado(self):
        return OrdenCompra.todos.get(pk=self.orden.pk).estado

    def test_producto_que_no_llego_en_cero_sin_lote_ni_vencimiento(self):
        # p2 exige lote y vencimiento, pero no llegó: en 0 y con sus campos vacíos
        r = self.client.post(self.url, {f'cantidad_{self.i1.pk}': 10, f'costo_{self.i1.pk}': '9',
                                        f'cantidad_{self.i2.pk}': 0, f'lote_{self.i2.pk}': '',
                                        f'vence_{self.i2.pk}': '', f'costo_{self.i2.pk}': ''})
        self.assertRedirects(r, reverse('compras:detalle', args=[self.orden.pk]))
        self.assertEqual(self.estado(), 'PARCIAL')
        self.assertEqual(Lote.todos.get(producto=self.p1).cantidad_actual, 10)
        self.assertFalse(Lote.todos.filter(producto=self.p2).exists())
        # La pantalla de recepción ya solo ofrece lo pendiente
        r = self.client.get(self.url)
        self.assertContains(r, self.p2.nombre)
        self.assertNotContains(r, f'cantidad_{self.i1.pk}')

    def test_cantidad_vacia_cuenta_como_cero(self):
        r = self.client.post(self.url, {f'cantidad_{self.i1.pk}': 6, f'costo_{self.i1.pk}': '9',
                                        f'cantidad_{self.i2.pk}': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estado(), 'PARCIAL')
        self.assertEqual(ItemOrdenCompra.todos.get(pk=self.i1.pk).pendiente, 4)

    def test_cerrar_la_orden_aunque_nunca_llegue_el_faltante(self):
        self.client.post(self.url, {f'cantidad_{self.i1.pk}': 10, f'costo_{self.i1.pk}': '9',
                                    f'cantidad_{self.i2.pk}': 0})
        r = self.client.post(reverse('compras:cambiar_estado', args=[self.orden.pk]), {'estado': 'RECIBIDA'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estado(), 'RECIBIDA')
        r = self.client.get(reverse('compras:detalle', args=[self.orden.pk]))
        self.assertEqual(r.status_code, 200)
        # Lo que no llegó deja de contarse como "en camino" en el panel de pedido
        with self.en_empresa():
            todas = [s for g in sugerencias.calcular(30, solo_necesarios=False).values() for s in g]
            self.assertEqual({s.producto.pk: s.en_camino for s in todas}[self.p2.pk], 0)

    def test_todo_en_cero_no_registra_nada(self):
        r = self.client.post(self.url, {f'cantidad_{self.i1.pk}': 0, f'cantidad_{self.i2.pk}': 0})
        self.assertContains(r, 'Indica al menos una cantidad')
        self.assertEqual(self.estado(), 'ENVIADA')


class MenuMovilTests(ComprasBase):
    def test_menu_mas_da_acceso_a_compras_en_movil(self):
        html = self.client.get(reverse('core:inicio')).content.decode()
        panel = html[html.index('id="ordo-mas"'):]
        for nombre in ('compras:lista', 'clientes:lista', 'proveedores:lista', 'comisiones:inicio', 'ventas:reportes'):
            self.assertIn(f'href="{reverse(nombre)}"', panel, nombre)
        self.client.force_login(self.vendedor)          # el vendedor no ve Compras tampoco en el panel
        html = self.client.get(reverse('core:inicio')).content.decode()
        self.assertNotIn(f'href="{reverse("compras:lista")}"', html[html.index('id="ordo-mas"'):])
