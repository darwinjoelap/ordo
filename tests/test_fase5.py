"""
Pruebas de la Fase 5: comisiones (cálculo, excepciones por categoría, cobro, liquidación y pantallas).
"""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.comisiones import servicios as comisiones
from apps.comisiones.models import Comision, LineaComision, Liquidacion, PorcentajeCategoria, PorcentajeVendedor
from apps.inventario import servicios as inventario
from apps.inventario.models import Categoria, Producto, Unidad
from apps.ventas import servicios as ventas
from apps.ventas.models import Presupuesto

from .test_fase4 import Base as BaseVentas

HOY = timezone.localdate()


class Base(BaseVentas):
    def setUp(self):
        super().setUp()
        self.perfil.requiere_validacion = False
        self.perfil.iva_porcentaje = Decimal('16')
        self.perfil.save()
        with self.empresa_ctx():
            PorcentajeVendedor.objects.create(vendedor=self.vendedor, porcentaje=Decimal('5'))
            self.cat2 = Categoria.objects.create(nombre='Equipos')
            self.equipo = Producto.objects.create(codigo='EQ', nombre='Centrífuga', categoria=self.cat2,
                                                  unidad=Unidad.objects.get(abreviatura='UN'),
                                                  precio_costo_usd=Decimal('100'), precio_venta_usd=Decimal('200'))
            inventario.ingresar(self.equipo, 3, Decimal('100'), self.dueno)

    def venta(self, items, descuento=None, vendedor=None):
        """items: [(producto, cantidad)] → venta validada."""
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, vendedor or self.vendedor, self.empresa)
            for prod, cant in items:
                ventas.agregar_item(p, prod, cant, None, self.perfil, True)
            if descuento is not None:
                ventas.actualizar_items(p, {}, [], self.perfil, True, descuento_pct=Decimal(descuento))
            return ventas.confirmar(p, self.vendedor, self.empresa)


class CalculoTests(Base):
    def test_se_genera_al_validar_sobre_base_sin_iva(self):
        p = self.venta([(self.prod, 3)])                 # 3 × 20 = 60 + IVA
        c = Comision.todos.get(presupuesto=p)
        self.assertEqual(p.total_usd, Decimal('69.60'))
        self.assertEqual(c.base_usd, Decimal('60.00'))
        self.assertEqual(c.monto_usd, Decimal('3.00'))
        self.assertEqual(c.vendedor, self.vendedor)

    def test_descuento_reduce_la_base(self):
        p = self.venta([(self.prod, 5)], descuento='10')  # 100 − 10 %
        self.assertEqual(Comision.todos.get(presupuesto=p).base_usd, Decimal('90.00'))

    def test_categoria_manda_sobre_vendedor(self):
        with self.empresa_ctx():
            PorcentajeCategoria.objects.create(categoria=self.cat2, porcentaje=Decimal('2'))
        p = self.venta([(self.prod, 1), (self.equipo, 1)])   # 20 × 5 % + 200 × 2 %
        c = Comision.todos.get(presupuesto=p)
        self.assertEqual(c.monto_usd, Decimal('5.00'))
        self.assertEqual(sorted(LineaComision.todos.filter(comision=c).values_list('origen', flat=True)),
                         ['CATEGORIA', 'VENDEDOR'])

    def test_sin_porcentaje_genera_cero(self):
        p = self.venta([(self.prod, 1)], vendedor=self.vendedor2)
        self.assertEqual(Comision.todos.get(presupuesto=p).monto_usd, Decimal('0.00'))

    def test_porcentaje_queda_congelado(self):
        p = self.venta([(self.prod, 1)])
        PorcentajeVendedor.todos.filter(vendedor=self.vendedor).update(porcentaje=Decimal('50'))
        self.assertEqual(Comision.todos.get(presupuesto=p).monto_usd, Decimal('1.00'))

    def test_no_se_genera_sin_validar_y_es_idempotente(self):
        self.perfil.requiere_validacion = True
        self.perfil.save()
        p = self.venta([(self.prod, 1)])
        self.assertEqual(p.estado, Presupuesto.Estado.POR_VALIDAR)
        self.assertFalse(Comision.todos.exists())
        with self.empresa_ctx():
            p = ventas.validar(p, self.dueno)
            comisiones.registrar(p)
        self.assertEqual(Comision.todos.count(), 1)

    def test_generar_faltantes(self):
        p = self.venta([(self.prod, 1)])
        Comision.todos.all().delete()
        self.assertEqual(comisiones.generar_faltantes(), 1)
        self.assertTrue(Comision.todos.filter(presupuesto=p).exists())


class LiquidacionTests(Base):
    def test_liquidar_pagar_y_no_repetir(self):
        self.venta([(self.prod, 2)])
        self.venta([(self.prod, 3)])
        with self.empresa_ctx():
            liq = comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
            self.assertEqual(liq.total_usd, Decimal('5.00'))
            self.assertTrue(liq.numero.startswith('LQ-'))
            with self.assertRaises(comisiones.ErrorComision):
                comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
            comisiones.marcar_pagada(liq, metodo='Transferencia')
            with self.assertRaises(comisiones.ErrorComision):
                comisiones.anular(liq)
        liq.refresh_from_db()
        self.assertTrue(liq.pagada)

    def test_anular_devuelve_las_comisiones(self):
        self.venta([(self.prod, 2)])
        with self.empresa_ctx():
            liq = comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
            comisiones.anular(liq)
            self.assertEqual(comisiones.disponibles(self.perfil, self.vendedor).count(), 1)
        liq.refresh_from_db()
        self.assertTrue(liq.anulada)

    def test_hasta_limita_el_periodo(self):
        p = self.venta([(self.prod, 1)])
        Comision.todos.filter(presupuesto=p).update(fecha=HOY - timedelta(days=40))
        self.venta([(self.prod, 1)])
        with self.empresa_ctx():
            liq = comisiones.liquidar(self.perfil, self.vendedor, HOY - timedelta(days=30), self.dueno, self.empresa)
        self.assertEqual(Comision.todos.filter(liquidacion=liq).count(), 1)

    def test_exige_cobro(self):
        self.perfil.comision_requiere_pago = True
        self.perfil.save()
        p = self.venta([(self.prod, 1)])
        with self.empresa_ctx():
            self.assertEqual(comisiones.disponibles(self.perfil, self.vendedor).count(), 0)
            self.assertEqual(comisiones.pendientes_de_cobro(self.perfil).count(), 1)
            ventas.registrar_pago(p, True, 'ZELLE')
            self.assertEqual(comisiones.disponibles(self.perfil, self.vendedor).count(), 1)


class VistasTests(Base):
    def test_vendedor_ve_solo_lo_suyo_y_no_liquida(self):
        self.venta([(self.prod, 1)])
        otra = self.venta([(self.prod, 1)], vendedor=self.vendedor2)
        self.client.force_login(self.vendedor)
        self.assertRedirects(self.client.get(reverse('comisiones:inicio')), reverse('comisiones:detalle_vendedor'))
        r = self.client.get(reverse('comisiones:detalle_vendedor'))
        self.assertContains(r, '$ 1,00')
        self.assertNotContains(r, otra.numero)
        self.assertEqual(self.client.get(reverse('comisiones:vendedor', args=[self.vendedor2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('comisiones:configuracion')).status_code, 403)
        self.assertEqual(self.client.post(reverse('comisiones:liquidar', args=[self.vendedor.pk])).status_code, 403)
        self.assertContains(self.client.get(reverse('core:inicio')), 'Mi comisión del mes')

    def test_flujo_admin_por_la_web(self):
        self.venta([(self.prod, 4)])
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('comisiones:inicio'))
        self.assertContains(r, 'Liquidar')
        self.client.post(reverse('comisiones:liquidar', args=[self.vendedor.pk]), {'hasta': HOY.isoformat()})
        liq = Liquidacion.todos.get()
        self.client.post(reverse('comisiones:liquidacion', args=[liq.pk]), {'accion': 'pagar', 'metodo_pago': 'Zelle'})
        liq.refresh_from_db()
        self.assertTrue(liq.pagada)
        r = self.client.get(reverse('comisiones:liquidacion_pdf', args=[liq.pk]))
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.client.force_login(self.vendedor)     # el vendedor ve su liquidación
        self.assertEqual(self.client.get(reverse('comisiones:liquidacion', args=[liq.pk])).status_code, 200)
        self.client.force_login(self.vendedor2)    # otro vendedor no
        self.assertEqual(self.client.get(reverse('comisiones:liquidacion', args=[liq.pk])).status_code, 404)

    def test_configuracion_guarda_y_valida(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse('comisiones:configuracion'),
                         {f'v_{self.vendedor.pk}': '7,5', f'c_{self.cat2.pk}': '1'})
        self.assertEqual(PorcentajeVendedor.todos.get(vendedor=self.vendedor).porcentaje, Decimal('7.50'))
        self.assertEqual(PorcentajeCategoria.todos.get(categoria=self.cat2).porcentaje, Decimal('1.00'))
        r = self.client.post(reverse('comisiones:configuracion'), {f'v_{self.vendedor.pk}': '150'})
        self.assertContains(r, 'No se guardó nada')
        self.assertEqual(PorcentajeVendedor.todos.get(vendedor=self.vendedor).porcentaje, Decimal('7.50'))

    def test_detalle_de_venta_muestra_comision(self):
        p = self.venta([(self.prod, 2)])
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Disponible para liquidar')
