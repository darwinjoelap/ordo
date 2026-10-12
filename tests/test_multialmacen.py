"""Multialmacén: lo existente queda «Sin almacén», traslados sin perder datos, ventas por almacén."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from apps.inventario import servicios as inv
from apps.inventario.models import Almacen, Lote, MovimientoInventario, Producto, Traslado
from apps.ventas import servicios as ventas
from apps.ventas.models import Presupuesto, Reserva

from .test_fase5 import HOY, Base

T = MovimientoInventario.Tipo


class MultiBase(Base):
    """Glucosa: lotes L-LEJOS (5) y L-CERCA (5), creados antes de activar multialmacén → sin almacén."""

    def setUp(self):
        super().setUp()
        with self.empresa_ctx():
            self.total_antes = sum(l.cantidad_actual for l in Lote.objects.all())
        self.perfil.multialmacen = True
        self.perfil.save()
        with self.empresa_ctx():
            self.a = Almacen.objects.create(nombre='Central', principal=True)
            self.b = Almacen.objects.create(nombre='Acarigua')


class TrasladoTests(MultiBase):
    def test_lo_existente_queda_sin_almacen_y_nada_cambia(self):
        with self.empresa_ctx():
            self.assertFalse(Lote.objects.exclude(almacen__isnull=True).exists())
            self.assertEqual(sum(l.cantidad_actual for l in Lote.objects.all()), self.total_antes)

    def test_traslado_parcial_divide_el_lote(self):
        with self.empresa_ctx():
            lote = Lote.objects.get(numero_lote='L-CERCA')
            t = inv.trasladar(None, self.a, [(lote, 2)], self.dueno, 'puesta a punto')
            lote.refresh_from_db()
            nuevo = Lote.objects.get(numero_lote='L-CERCA', almacen=self.a)
            self.assertEqual((lote.cantidad_actual, lote.almacen, nuevo.cantidad_actual), (3, None, 2))
            self.assertEqual((nuevo.fecha_vencimiento, nuevo.costo_unitario_usd), (lote.fecha_vencimiento, lote.costo_unitario_usd))
            tipos = sorted(MovimientoInventario.objects.filter(referencia_tipo='Traslado').values_list('tipo', 'cantidad'))
            self.assertEqual(tipos, [(T.TRASLADO_ENT, 2), (T.TRASLADO_SAL, -2)])
            self.assertTrue(t.numero.startswith('TR-'))
            self.assertEqual(sum(l.cantidad_actual for l in Lote.objects.all()), self.total_antes)

    def test_traslado_completo_conserva_el_lote(self):
        with self.empresa_ctx():
            lote = Lote.objects.get(numero_lote='L-LEJOS')
            inv.trasladar(None, self.b, [(lote, 5)], self.dueno)
            lote.refresh_from_db()
            self.assertEqual((lote.almacen, lote.cantidad_actual), (self.b, 5))
            self.assertEqual(Lote.objects.filter(numero_lote='L-LEJOS').count(), 1)
            inv.trasladar(self.b, self.a, [(lote, 5)], self.dueno)              # y de vuelta
            lote.refresh_from_db()
            self.assertEqual(lote.almacen, self.a)

    def test_no_mueve_lo_apartado_ni_lo_ajeno(self):
        self.venta_apartada = None
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            Presupuesto.objects.filter(pk=p.pk).update(almacen=None)
            p.refresh_from_db()
            ventas.agregar_item(p, self.prod, 4, None, self.perfil, True)
            ventas.apartar(p, self.vendedor, self.empresa)                       # aparta 4 de L-CERCA
            lote = Lote.objects.get(numero_lote='L-CERCA')
            with self.assertRaisesRegex(inv.ErrorInventario, 'como máximo 1'):
                inv.trasladar(None, self.a, [(lote, 2)], self.dueno)
            with self.assertRaisesRegex(inv.ErrorInventario, 'no está en el almacén de origen'):
                inv.trasladar(self.b, self.a, [(lote, 1)], self.dueno)
            with self.assertRaisesRegex(inv.ErrorInventario, 'mismo almacén'):
                inv.trasladar(self.a, self.a, [(lote, 1)], self.dueno)
            self.assertFalse(Traslado.objects.exists())

    def test_trasladar_todo(self):
        with self.empresa_ctx():
            inv.trasladar_todo(None, self.a, self.dueno)
            self.assertFalse(Lote.objects.filter(almacen__isnull=True, cantidad_actual__gt=0).exists())
            self.assertEqual(sum(l.cantidad_actual for l in Lote.objects.filter(almacen=self.a)), self.total_antes)
            self.assertEqual(Producto.objects.con_stock(self.a).get(pk=self.prod.pk).anot_stock_total, 10)
            self.assertEqual(Producto.objects.con_stock(self.b).get(pk=self.prod.pk).anot_stock_total, 0)
            self.assertEqual(Producto.objects.con_stock().get(pk=self.prod.pk).anot_stock_total, 10)


class VentasPorAlmacenTests(MultiBase):
    def test_por_defecto_cualquiera_mientras_haya_sin_almacen(self):
        with self.empresa_ctx():
            self.assertIsNone(ventas.crear(self.cliente, self.vendedor, self.empresa).almacen)
            inv.trasladar_todo(None, self.a, self.dueno)
            self.assertEqual(ventas.crear(self.cliente, self.vendedor, self.empresa).almacen, self.a)

    def test_aparta_solo_del_almacen_elegido(self):
        with self.empresa_ctx():
            inv.trasladar(None, self.b, [(Lote.objects.get(numero_lote='L-CERCA'), 5)], self.dueno)
            inv.trasladar_todo(None, self.a, self.dueno)                       # L-LEJOS y la centrífuga
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            self.assertEqual(p.almacen, self.a)
            ventas.agregar_item(p, self.prod, 3, None, self.perfil, True)
            ventas.apartar(p, self.vendedor, self.empresa)
            self.assertEqual({r.lote.almacen_id for r in Reserva.objects.filter(item__presupuesto=p)}, {self.a.pk})
            p2 = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p2, self.prod, 6, None, self.perfil, True)
            with self.assertRaisesRegex(ventas.ErrorVenta, 'en Central'):
                ventas.apartar(p2, self.vendedor, self.empresa)

    def test_cambiar_almacen_en_pantalla(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
            item = p.items.get()
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Sale del almacén')
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {f'cantidad_{item.pk}': '1', 'almacen': self.b.pk})
        self.assertEqual(Presupuesto.todos.get(pk=p.pk).almacen_id, self.b.pk)


class PantallasTests(MultiBase):
    def test_almacenes_y_traslados(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('inventario:almacenes'))
        self.assertContains(r, 'Sin almacén')
        self.assertContains(r, 'Mover todo')
        r = self.client.post(reverse('inventario:traslado_nuevo') + '?origen=SIN',
                             {'origen': 'SIN', 'todo': '1', 'destino': self.a.pk}, follow=True)
        self.assertContains(r, 'registrado')
        t = Traslado.todos.get()
        self.assertTrue(self.client.get(reverse('inventario:traslado_pdf', args=[t.pk])).content.startswith(b'%PDF'))
        self.assertNotContains(self.client.get(reverse('inventario:almacenes')), 'Mover todo')
        self.assertContains(self.client.get(reverse('inventario:lista'), {'almacen': self.a.pk}), self.prod.nombre)
        self.assertContains(self.client.get(reverse('inventario:detalle', args=[self.prod.pk])), 'Existencia por almacén')

    def test_crear_almacen_y_principal(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse('inventario:almacen_crear'), {'nombre': 'Nuevo', 'principal': '1'})
        with self.empresa_ctx():
            self.assertEqual(Almacen.objects.get(principal=True).nombre, 'Nuevo')
            self.assertEqual(Almacen.objects.filter(principal=True).count(), 1)
        r = self.client.post(reverse('inventario:almacen_activar', args=[Almacen.todos.get(nombre='Nuevo').pk]), follow=True)
        self.assertContains(r, 'no se puede desactivar')

    def test_ingreso_va_al_almacen_elegido(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse('inventario:ingreso'), {'producto': self.equipo.pk, 'cantidad': '2', 'costo_unitario': '100',
                                                        'almacen': self.b.pk})
        with self.empresa_ctx():
            self.assertTrue(Lote.objects.filter(producto=self.equipo, almacen=self.b, cantidad_actual=2).exists())

    def test_vendedor_no_gestiona_almacenes(self):
        self.client.force_login(self.vendedor)
        self.assertIn(self.client.get(reverse('inventario:almacenes')).status_code, (302, 403))

    def test_desactivado_no_aparece(self):
        self.perfil.multialmacen = False
        self.perfil.save()
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('inventario:almacenes')).status_code, 404)
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            self.assertIsNone(p.almacen)
