"""
Devoluciones de ventas validadas: total/parcial, stock por lote, ajuste de comisión, reembolso y pantallas.
"""
from decimal import Decimal

from django.urls import reverse

from apps.comisiones import servicios as comisiones
from apps.comisiones.models import AjusteComision, Comision
from apps.inventario.models import Lote, MovimientoInventario
from apps.ventas import servicios as ventas
from apps.ventas.models import Devolucion, ItemDevolucion, ItemPresupuesto, Presupuesto, Reserva

from .test_fase5 import HOY, Base

E = Presupuesto.Estado


class BaseDev(Base):
    def item(self, p, producto=None):
        return ItemPresupuesto.todos.get(presupuesto=p, producto=producto or self.prod)

    def devolver(self, p, cantidad, reingresa=True, motivo='Empaque dañado', reembolso=None, extra=None):
        lineas = {self.item(p).pk: (cantidad, reingresa)}
        lineas.update(extra or {})
        with self.empresa_ctx():
            return ventas.devolver(p, self.dueno, lineas, motivo, reembolso=reembolso)

    def lote(self, numero):
        return Lote.todos.get(numero_lote=numero)


class StockYMontosTests(BaseDev):
    def test_parcial_vuelve_a_los_lotes_de_origen(self):
        p = self.venta([(self.prod, 7)])           # FEFO: 5 de L-CERCA + 2 de L-LEJOS
        self.assertEqual(self.stock(), (3, 0))
        dev = self.devolver(p, 3)
        self.assertEqual(self.stock(), (6, 0))
        # empieza por el último lote tomado
        self.assertEqual(self.lote('L-LEJOS').cantidad_actual, 5)
        self.assertEqual(self.lote('L-CERCA').cantidad_actual, 1)
        self.assertEqual(MovimientoInventario.todos.filter(tipo='DEVOLUCION').count(), 2)
        self.assertEqual((dev.subtotal_usd, dev.iva_usd, dev.total_usd, dev.total_bs),
                         (Decimal('60.00'), Decimal('9.60'), Decimal('69.60'), Decimal('6960.00')))
        self.assertTrue(dev.numero.startswith('DV-'))
        p.refresh_from_db()
        self.assertEqual(p.estado, E.VALIDADA)
        self.assertEqual(p.devuelto_usd, Decimal('69.60'))

    def test_completa_en_dos_pasos_cierra_al_centavo(self):
        p = self.venta([(self.prod, 7)], descuento='7')    # 140 − 7 % = 130,20 + IVA 20,83 = 151,03
        self.assertEqual(p.total_usd, Decimal('151.03'))
        d1 = self.devolver(p, 3)
        self.assertEqual(d1.total_usd, Decimal('64.73'))
        p.refresh_from_db()
        d2 = self.devolver(p, 4)
        self.assertEqual(d2.total_usd, Decimal('86.30'))
        p.refresh_from_db()
        self.assertEqual(p.estado, E.DEVUELTA)
        self.assertEqual(p.devuelto_usd, p.total_usd)
        self.assertEqual(d1.total_bs + d2.total_bs, p.total_bs)
        self.assertEqual(self.stock(), (10, 0))
        with self.assertRaises(ventas.ErrorVenta):    # ya no es VALIDADA
            self.devolver(p, 1)

    def test_no_reingresa_queda_registrada_sin_sumar_stock(self):
        p = self.venta([(self.prod, 4)])
        self.devolver(p, 2, reingresa=False)
        self.assertEqual(self.stock(), (6, 0))
        self.assertFalse(MovimientoInventario.todos.filter(tipo='DEVOLUCION').exists())
        linea = ItemDevolucion.todos.get()
        self.assertFalse(linea.reingresa)
        self.assertIsNotNone(linea.lote)

    def test_validaciones(self):
        p = self.venta([(self.prod, 2)])
        for args in [dict(cantidad=3), dict(cantidad=0), dict(cantidad=1, motivo='  '),
                     dict(cantidad=1, reembolso={'monto_usd': Decimal('999'), 'metodo': 'EFECTIVO_USD'}),
                     dict(cantidad=1, reembolso={'monto_usd': None, 'metodo': ''})]:
            with self.subTest(args=args), self.assertRaises(ventas.ErrorVenta):
                self.devolver(p, **args)
        self.assertFalse(Devolucion.todos.exists())
        self.devolver(p, 2)
        p.refresh_from_db()
        self.assertEqual(p.estado, E.DEVUELTA)

    def test_solo_ventas_validadas(self):
        self.perfil.requiere_validacion = True
        self.perfil.save()
        p = self.venta([(self.prod, 1)])
        self.assertEqual(p.estado, E.POR_VALIDAR)
        with self.assertRaises(ventas.ErrorVenta):
            self.devolver(p, 1)

    def test_reembolso_por_defecto_es_el_total_y_se_puede_registrar_despues(self):
        p = self.venta([(self.prod, 2)])
        d = self.devolver(p, 1, reembolso={'monto_usd': None, 'metodo': 'PAGO_MOVIL', 'referencia': '123'})
        self.assertEqual((d.reembolsado, d.reembolso_usd, d.reembolso_bs), (True, Decimal('23.20'), Decimal('2320.00')))
        d2 = self.devolver(p, 1)
        self.assertFalse(d2.reembolsado)
        with self.empresa_ctx():
            ventas.registrar_reembolso(d2, Decimal('10'), 'EFECTIVO_USD')
            with self.assertRaises(ventas.ErrorVenta):
                ventas.registrar_reembolso(d2, Decimal('10'), 'EFECTIVO_USD')
        d2.refresh_from_db()
        self.assertEqual(d2.reembolso_usd, Decimal('10.00'))

    def test_venta_sin_reservas_va_al_lote_mas_reciente(self):
        p = self.venta([(self.prod, 2)])
        Reserva.todos.all().delete()                   # como una venta migrada
        self.devolver(p, 2)
        self.assertEqual(self.lote('L-CERCA').cantidad_actual, 5)   # el último ingresado
        self.assertEqual(self.stock(), (10, 0))

    def test_consumo_del_panel_de_pedido_es_neto(self):
        from apps.compras import sugerencias
        p = self.venta([(self.prod, 6)])
        self.devolver(p, 6)
        with self.empresa_ctx():
            filas = [f for g in sugerencias.calcular(solo_necesarios=False).values() for f in g]
        fila = next(f for f in filas if f.producto.pk == self.prod.pk)
        self.assertEqual(fila.fuente, 'estimado')     # no quedó consumo real


class ComisionTests(BaseDev):
    def test_ajuste_proporcional_con_porcentaje_congelado(self):
        p = self.venta([(self.prod, 4)])               # 80 × 5 % = 4,00
        self.devolver(p, 1)
        a = AjusteComision.todos.get()
        self.assertEqual(a.monto_usd, Decimal('-1.00'))
        self.assertEqual(a.vendedor, self.vendedor)

    def test_devolucion_total_anula_exactamente(self):
        p = self.venta([(self.prod, 3)], descuento='3.3')
        c = Comision.todos.get(presupuesto=p)
        self.devolver(p, 1)
        p.refresh_from_db()
        self.devolver(p, 2)
        total = sum(a.monto_usd for a in AjusteComision.todos.all())
        self.assertEqual(total, -c.monto_usd)

    def test_sin_liquidar_se_netea_en_la_misma_liquidacion(self):
        p = self.venta([(self.prod, 4)])
        self.devolver(p, 1)
        with self.empresa_ctx():
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('3.00'))
            liq = comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
        self.assertEqual(liq.total_usd, Decimal('3.00'))
        self.assertEqual(AjusteComision.todos.get().liquidacion, liq)

    def test_ya_pagada_se_descuenta_en_la_proxima(self):
        p = self.venta([(self.prod, 4)])
        with self.empresa_ctx():
            liq = comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
            comisiones.marcar_pagada(liq)
        self.devolver(p, 4)
        liq.refresh_from_db()
        self.assertEqual(liq.total_usd, Decimal('4.00'))           # lo pagado no cambia
        with self.empresa_ctx():
            with self.assertRaises(comisiones.ErrorComision):      # saldo negativo: espera nuevas comisiones
                comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
        self.venta([(self.prod, 5)])                               # +5,00
        with self.empresa_ctx():
            liq2 = comisiones.liquidar(self.perfil, self.vendedor, HOY, self.dueno, self.empresa)
            self.assertEqual(liq2.total_usd, Decimal('1.00'))
            comisiones.anular(liq2)                                # el ajuste vuelve a quedar pendiente
        self.assertIsNone(AjusteComision.todos.get().liquidacion)

    def test_si_exige_cobro_el_ajuste_espera_a_su_comision(self):
        self.perfil.comision_requiere_pago = True
        self.perfil.save()
        p = self.venta([(self.prod, 4)])
        self.devolver(p, 1)
        with self.empresa_ctx():
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('0'))
            self.assertFalse(comisiones.ajustes_aplicables(self.perfil, self.vendedor).exists())


class PantallasTests(BaseDev):
    def test_flujo_desde_la_venta(self):
        p = self.venta([(self.prod, 3)])
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Registrar devolución')
        self.assertEqual(self.client.get(reverse('ventas:devolver', args=[p.pk])).status_code, 200)
        item = self.item(p)
        r = self.client.post(reverse('ventas:devolver', args=[p.pk]), {
            f'cantidad_{item.pk}': '1', f'reingresa_{item.pk}': '1', 'motivo': 'Vencido',
            'reembolso': '1', 'reembolso_metodo': 'ZELLE'})
        dev = Devolucion.todos.get()
        self.assertRedirects(r, reverse('ventas:devolucion', args=[dev.pk]))
        self.assertTrue(dev.reembolsado)
        self.assertContains(self.client.get(reverse('ventas:devolucion', args=[dev.pk])), dev.numero)
        self.assertContains(self.client.get(reverse('ventas:devoluciones')), dev.numero)
        self.assertTrue(self.client.get(reverse('ventas:devolucion_pdf', args=[dev.pk])).content.startswith(b'%PDF'))
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'neto de la venta')
        self.assertContains(self.client.get(reverse('comisiones:vendedor', args=[self.vendedor.pk])), dev.numero)

    def test_error_mantiene_el_formulario(self):
        p = self.venta([(self.prod, 3)])
        self.client.force_login(self.dueno)
        item = self.item(p)
        r = self.client.post(reverse('ventas:devolver', args=[p.pk]), {f'cantidad_{item.pk}': '9', 'motivo': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'como máximo 3')
        self.assertFalse(Devolucion.todos.exists())

    def test_permisos(self):
        p = self.venta([(self.prod, 3)])
        dev = self.devolver(p, 1)
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(reverse('ventas:devolver', args=[p.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('ventas:devoluciones')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Registrar devolución')
        r = self.client.get(reverse('ventas:devolucion', args=[dev.pk]))       # su venta: la ve
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Registrar reembolso')
        self.client.force_login(self.vendedor2)                                # venta ajena: no
        self.assertEqual(self.client.get(reverse('ventas:devolucion', args=[dev.pk])).status_code, 404)

    def test_tablero_muestra_ventas_netas(self):
        p = self.venta([(self.prod, 2)])                  # 46,40
        self.devolver(p, 1)                               # −23,20
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('core:inicio'))
        self.assertEqual(r.context['ventas_mes']['usd'], Decimal('23.20'))
        self.assertEqual(r.context['ventas_mes']['n'], 1)
