"""Orden de compra: costos y cantidades escritos a mano (coma decimal, vacíos, miles)."""
from decimal import Decimal

from django.urls import reverse

from apps.compras.models import ItemOrdenCompra, OrdenCompra
from apps.core.numeros import numero

from .test_fase3b import ComprasBase


class NumeroTests(ComprasBase):
    def test_lectura_tolerante(self):
        casos = {'12,50': '12.50', '12.50': '12.50', '1.234,50': '1234.50', '1,234.50': '1234.50', '$ 7': '7',
                 '': None, 'abc': None, 'NaN': None}
        for texto, esperado in casos.items():
            self.assertEqual(numero(texto), Decimal(esperado) if esperado else None, texto)

    def test_actualizar_orden_con_coma_y_vacios(self):
        self.client.post(reverse('compras:crear'), {'proveedor': self.prov.pk})
        orden = OrdenCompra.todos.get()
        url = reverse('compras:agregar_item', args=[orden.pk])
        self.client.post(url, {'producto': self.p1.pk, 'cantidad': 2, 'costo': '9,75'})
        self.client.post(url, {'producto': self.p2.pk, 'cantidad': 1, 'costo': '3'})
        i1, i2 = (ItemOrdenCompra.todos.get(orden=orden, producto=p) for p in (self.p1, self.p2))
        self.assertEqual(i1.costo_unitario_usd, Decimal('9.75'))
        r = self.client.post(reverse('compras:actualizar_items', args=[orden.pk]), {
            'proveedor': self.prov.pk, f'cantidad_{i1.pk}': '4', f'costo_{i1.pk}': '1.234,50',
            f'cantidad_{i2.pk}': '3', f'costo_{i2.pk}': ''}, follow=True)
        self.assertContains(r, 'el costo «vacío» no es un número')
        self.assertContains(r, 'Se guardó lo demás')
        i1.refresh_from_db()
        i2.refresh_from_db()
        self.assertEqual((i1.cantidad_pedida, i1.costo_unitario_usd), (4, Decimal('1234.50')))
        self.assertEqual((i2.cantidad_pedida, i2.costo_unitario_usd), (1, Decimal('3.00')))    # no cambió


class FormulariosConComaTests(ComprasBase):
    def test_producto_e_ingreso_con_coma(self):
        url = reverse('inventario:producto_editar', args=[self.p1.pk])
        r = self.client.get(url)
        self.assertContains(r, 'inputmode="decimal"')
        self.assertNotContains(r, 'name="precio_venta_usd" step')
        r = self.client.post(url, {'codigo': 'P1', 'nombre': 'Uno', 'categoria': self.p1.categoria_id,
                                   'unidad': self.p1.unidad_id, 'precio_costo_usd': '1.234,50',
                                   'precio_venta_usd': '15,75', 'stock_minimo': '5', 'factor_venta_dias': '0,5',
                                   'activo': 'on'})
        self.assertEqual(r.status_code, 302)
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.precio_costo_usd, self.p1.precio_venta_usd, self.p1.factor_venta_dias),
                         (Decimal('1234.50'), Decimal('15.75'), Decimal('0.50')))
        r = self.client.post(url, {'codigo': 'P1', 'nombre': 'Uno', 'categoria': self.p1.categoria_id,
                                   'unidad': self.p1.unidad_id, 'precio_costo_usd': 'doce',
                                   'precio_venta_usd': '1', 'stock_minimo': '5', 'factor_venta_dias': '1'})
        self.assertEqual(r.status_code, 200)                     # texto inválido: error en el formulario
