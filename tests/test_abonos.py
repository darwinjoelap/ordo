"""Pagos parciales (abonos), comisión al pago completo y estado de cuenta del cliente."""
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from uuid import uuid4

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from io import BytesIO

from apps.comisiones import servicios as comisiones
from apps.comisiones.models import Comision, MovimientoComision, PorcentajeCategoria, PorcentajeVendedor
from apps.core.tenancy import usando_empresa
from apps.empresas.models import Membresia, Rol
from apps.tasas import servicios as tasas
from apps.tasas.models import TasaCambio
from apps.ventas import servicios as ventas
from apps.ventas.models import Abono, Presupuesto

from .test_fase4 import Base as BaseVentas
from .test_fase5 import Base

A = Abono.Estado


def confirmar_pendientes(p, usuario):
    for abono in Abono.objects.filter(presupuesto=p, estado=A.PENDIENTE):
        p = ventas.revisar_abono(abono, usuario, A.CONFIRMADO)
    return p


class AbonosConValidacionTests(Base):
    """La empresa exige validación: la venta va a «Por validar» solo cuando está pagada completa."""

    def setUp(self):
        super().setUp()
        self.perfil.requiere_validacion = True
        self.perfil.comision_requiere_pago = True
        self.perfil.save()

    def confirmada(self, n=5):                       # Glucosa $20 × 5 = 100 + IVA 16 = 116
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, n, None, self.perfil, True)
            return ventas.confirmar(p, self.vendedor, self.empresa)

    def test_abonos_hasta_pagar(self):
        p = self.confirmada()
        self.assertEqual((p.estado, p.saldo_usd), ('POR_PAGAR', Decimal('116.00')))
        with self.empresa_ctx():
            clave = uuid4()
            for _ in range(2):
                p = ventas.registrar_abono(p, Decimal('50'), 'USD', 'ZELLE', self.vendedor, clave=clave)
            self.assertEqual((p.abonado_usd, p.saldo_usd, ventas.saldo_para_registrar(p)), (0, 116, 66))
            abono = Abono.objects.get(presupuesto=p)
            with self.assertRaisesRegex(ventas.ErrorVenta, 'rol'):
                ventas.revisar_abono(abono, self.vendedor, A.CONFIRMADO)
            p = confirmar_pendientes(p, self.dueno)
            self.assertEqual((p.estado, p.pagado, p.abonado_usd, p.saldo_usd, p.abono_parcial),
                             ('POR_PAGAR', False, Decimal('50.00'), Decimal('66.00'), True))
            with self.assertRaisesRegex(ventas.ErrorVenta, 'supera'):
                ventas.registrar_abono(p, Decimal('70'), 'USD', 'ZELLE', self.vendedor)
            with self.assertRaisesRegex(ventas.ErrorVenta, 'validar|cobrar'):
                ventas.validar(p, self.dueno)
            p = ventas.registrar_abono(p, Decimal('66'), 'USD', 'PAGO_MOVIL', self.vendedor)
            self.assertFalse(p.pagado)
            p = confirmar_pendientes(p, self.dueno)
            self.assertEqual((p.estado, p.pagado, p.saldo_usd, p.metodo_pago), ('POR_VALIDAR', True, 0, 'MIXTO'))
            with self.assertRaisesRegex(ventas.ErrorVenta, 'pagada'):
                ventas.registrar_abono(p, Decimal('1'), 'USD', 'ZELLE', self.vendedor)
            ultimo = Abono.objects.filter(presupuesto=p).last()
            p = ventas.anular_abono(ultimo, self.dueno, 'Pago no recibido')
            self.assertEqual((p.estado, p.pagado, p.saldo_usd), ('POR_PAGAR', False, Decimal('66.00')))
            ultimo.refresh_from_db()
            self.assertEqual((ultimo.estado, ultimo.confirmado_por, ultimo.cerrado_por),
                             (A.REVERTIDO, self.dueno, self.dueno))

    def test_abono_en_bolivares_con_la_tasa(self):
        p = self.confirmada()
        with self.empresa_ctx():
            p = ventas.registrar_abono(p, Decimal('5000'), 'BS', 'PAGO_MOVIL', self.vendedor, tasa=Decimal('100'))
            a = Abono.objects.get(presupuesto=p)
            self.assertEqual((a.monto_usd, a.tasa_bs, p.saldo_usd), (Decimal('50.00'), Decimal('100'), Decimal('116.00')))
            tasas.registrar(Decimal('200'), TasaCambio.Fuente.MANUAL)
            p = ventas.registrar_abono(p, Decimal('13200'), 'BS', 'PAGO_MOVIL', self.vendedor)      # tasa del día
            self.assertTrue(confirmar_pendientes(p, self.dueno).pagado)

    def test_redondeo_de_un_centavo_cierra_la_venta(self):
        p = self.confirmada()
        with self.empresa_ctx():
            p = ventas.registrar_abono(p, Decimal('115.995'), 'USD', 'ZELLE', self.vendedor)
            self.assertTrue(confirmar_pendientes(p, self.dueno).pagado)

    def test_registrar_pago_completo_sigue_funcionando(self):
        p = self.confirmada()
        with self.empresa_ctx():
            p = ventas.registrar_abono(p, Decimal('16'), 'USD', 'ZELLE', self.vendedor)
            p = ventas.registrar_pago(p, True, 'ZELLE', usuario=self.dueno)
            self.assertEqual((p.pagado, p.abonado_usd, Abono.objects.filter(presupuesto=p).count()), (False, 0, 2))
            with self.assertRaisesRegex(ventas.ErrorVenta, 'individualmente'):
                ventas.registrar_pago(p, False, usuario=self.vendedor)
            self.assertTrue(confirmar_pendientes(p, self.dueno).pagado)

    def test_rechazar_y_retirar_conserva_el_historial_y_libera_el_cupo(self):
        p = self.confirmada()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('70'), 'USD', 'ZELLE', self.vendedor)
            abono = Abono.objects.get(presupuesto=p)
            ventas.revisar_abono(abono, self.dueno, A.RECHAZADO, 'Referencia incorrecta')
            self.assertEqual(ventas.saldo_para_registrar(p), 116)
            ventas.registrar_abono(p, Decimal('116'), 'USD', 'ZELLE', self.vendedor)
            otro = Abono.objects.get(presupuesto=p, estado=A.PENDIENTE)
            ventas.anular_abono(otro, self.vendedor, 'Monto incorrecto')
            self.assertEqual(ventas.saldo_para_registrar(p), 116)
            self.assertEqual(set(Abono.objects.values_list('estado', flat=True)), {A.RECHAZADO, A.RETIRADO})

    def test_apagar_la_regla_no_confirma_abonos_pendientes(self):
        p = self.confirmada()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('116'), 'USD', 'ZELLE', self.vendedor)
            self.perfil.requiere_validacion = False
            self.perfil.save()
            self.assertFalse(Presupuesto.objects.get(pk=p.pk).pagado)
            with self.assertRaises(ventas.ErrorVenta):
                ventas.registrar_pago(p, False, usuario=self.vendedor)
            p = confirmar_pendientes(p, self.dueno)
            self.assertEqual(p.estado, Presupuesto.Estado.POR_VALIDAR)

    def test_cobranza_excluye_pendientes_y_conserva_reversion(self):
        p = self.confirmada()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('50'), 'USD', 'ZELLE', self.vendedor)
        self.client.force_login(self.dueno)
        url = reverse('ventas:cobranza')
        self.assertEqual(self.client.get(url).context['tot']['usd'], 0)
        with self.empresa_ctx():
            confirmar_pendientes(p, self.dueno)
            abono = Abono.objects.get(presupuesto=p)
        self.assertEqual(self.client.get(url).context['tot']['usd'], 50)
        self.client.force_login(self.vendedor)
        revisar = reverse('ventas:revisar_abono', args=[p.pk, abono.pk])
        self.assertEqual(self.client.post(revisar, {'accion': 'revertir', 'motivo': 'Prueba'}).status_code, 403)
        self.client.force_login(self.dueno)
        self.client.post(revisar, {'accion': 'revertir', 'motivo': 'Abono duplicado'})
        self.client.post(revisar, {'accion': 'revertir', 'motivo': 'Reintento'})
        reporte = self.client.get(url)
        self.assertEqual(reporte.context['tot']['usd'], 0)
        self.assertEqual([a.monto_usd for a in reporte.context['filas']], [50, -50])
        self.assertContains(reporte, 'Reversión')

    def test_comision_proporcional_devenga_y_liquida_una_vez(self):
        self.perfil.modalidad_comision = 'PROPORCIONAL'
        self.perfil.save()
        p = self.confirmada()
        hoy = timezone.localdate()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('29'), 'USD', 'ZELLE', self.vendedor)
            abono = Abono.objects.get(presupuesto=p)
            self.assertFalse(MovimientoComision.objects.exists())
            for _ in range(2):
                ventas.revisar_abono(abono, self.dueno, A.CONFIRMADO)
            self.assertEqual(MovimientoComision.objects.get().monto_usd, Decimal('1.25'))
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), 0)
            self.perfil.modalidad_comision = 'VALIDADA'
            self.perfil.save()
            ventas.registrar_abono(p, Decimal('8700'), 'BS', 'PAGO_MOVIL', self.vendedor, tasa=Decimal('100'))
            ultimo = Abono.objects.get(presupuesto=p, estado=A.PENDIENTE)
            for _ in range(2):
                p = ventas.revisar_abono(ultimo, self.dueno, A.CONFIRMADO, validar_venta=True)
            self.assertEqual(p.estado, Presupuesto.Estado.VALIDADA)
            self.assertEqual(Comision.objects.count(), 1)
            self.assertEqual(MovimientoComision.objects.count(), 2)
            liq = comisiones.liquidar(self.perfil, self.vendedor, hoy, self.dueno, self.empresa)
            self.assertEqual(liq.total_usd, Decimal('5.00'))
            comisiones.marcar_pagada(liq)
            p = ventas.revisar_abono(abono, self.dueno, A.REVERTIDO, 'Registro duplicado')
            self.assertEqual((p.estado, p.saldo_usd), (Presupuesto.Estado.VALIDADA, Decimal('29.00')))
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('-1.25'))
            liq.refresh_from_db()
            self.assertTrue(liq.pagada)
            self.assertEqual(liq.total_usd, Decimal('5.00'))

    def test_otra_empresa_no_ve_ni_confirma_el_abono(self):
        p = self.confirmada()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('50'), 'USD', 'ZELLE', self.vendedor,
                                   referencia='REF-PRIVADA')
            abono = Abono.objects.get(presupuesto=p)
        Membresia.objects.create(empresa=self.otra, usuario=self.vendedor2, rol=Rol.DUENO)
        self.client.force_login(self.vendedor2)
        sesion = self.client.session
        sesion['empresa_id'] = self.otra.pk
        sesion.save()
        cola = self.client.get(reverse('ventas:abonos_por_validar'))
        self.assertContains(cola, 'No hay abonos pendientes')
        url = reverse('ventas:revisar_abono', args=[p.pk, abono.pk])
        self.assertEqual(self.client.post(url, {'accion': 'confirmar'}).status_code, 404)
        reporte = self.client.get(reverse('ventas:cobranza_excel'))
        hoja = load_workbook(BytesIO(reporte.content)).active
        self.assertNotIn('REF-PRIVADA', [v for fila in hoja.values for v in fila])

    def test_revision_desde_bandeja_y_detalle_cierra_el_cobro_y_valida_una_vez(self):
        self.perfil.modalidad_comision = 'PROPORCIONAL'
        self.perfil.save()
        p = self.confirmada()
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('29'), 'USD', 'ZELLE', self.vendedor, referencia='REF-PRIMER-ABONO')
            ventas.registrar_abono(p, Decimal('87'), 'USD', 'EFECTIVO_USD', self.vendedor)
        primero, ultimo = Abono.todos.filter(presupuesto=p)
        cola = reverse('ventas:abonos_por_validar')
        primero_url = reverse('ventas:revisar_abono', args=[p.pk, primero.pk])
        ultimo_url = reverse('ventas:revisar_abono', args=[p.pk, ultimo.pk])
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(cola), primero_url)
        self.assertContains(self.client.get(cola), 'REF-PRIMER-ABONO')
        r = self.client.post(primero_url, {'accion': 'confirmar', 'volver': 'abonos_por_validar'})
        self.assertRedirects(r, cola)
        p.refresh_from_db()
        self.assertEqual((p.estado, p.saldo_usd), (Presupuesto.Estado.POR_PAGAR, Decimal('87')))
        self.assertEqual(self.stock(), (10, 5))
        r = self.client.get(reverse('comisiones:inicio'))
        self.assertEqual(r.context['totales']['devengado_por_validar'], Decimal('1.25'))
        self.assertEqual(r.context['totales']['disponible'], 0)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Confirmar y validar venta')
        for _ in range(2):
            self.client.post(ultimo_url, {'accion': 'confirmar'})
        p.refresh_from_db()
        self.assertEqual((p.estado, p.pagado, p.validado_por), (Presupuesto.Estado.VALIDADA, True, self.dueno))
        self.assertEqual(self.stock(), (5, 0))
        self.assertEqual(MovimientoComision.todos.filter(comision__presupuesto=p).count(), 2)


class ComisionProporcionalDevolucionesTests(Base):
    def test_devuelve_lineas_y_reembolsa_sobre_el_cobro_confirmado(self):
        self.perfil.modalidad_comision = 'PROPORCIONAL'
        self.perfil.save()
        with self.empresa_ctx():
            self.equipo.exento_iva = True
            self.equipo.save(update_fields=['exento_iva'])
            PorcentajeCategoria.objects.create(categoria=self.cat2, porcentaje=Decimal('8'))
            p = self.venta([(self.prod, 1), (self.equipo, 1)], descuento='10')
            p = ventas.registrar_abono(p, Decimal('100.44'), 'USD', 'ZELLE', self.vendedor)
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('7.65'))
            item = p.items.get(producto=self.equipo)
            dev = ventas.devolver(p, self.dueno, {item.pk: (1, True)}, 'Devolución parcial')
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('0.90'))
            ventas.registrar_reembolso(dev, Decimal('90'), 'ZELLE')
            p.refresh_from_db()
            self.assertEqual((p.abonado_usd, p.saldo_usd), (Decimal('10.44'), Decimal('10.44')))
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Decimal('0.45'))
            item = p.items.get(producto=self.prod)
            ventas.devolver(p, self.dueno, {item.pk: (1, True)}, 'Devolución total')
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), 0)
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('ventas:cobranza')).context['tot']['usd'], Decimal('10.44'))


@skipUnless(connection.vendor == 'postgresql', 'Requiere bloqueos de fila de PostgreSQL')
class AbonosConcurrentesTests(TransactionTestCase):
    def setUp(self):
        BaseVentas.setUp(self)

    def _en_paralelo(self, operacion):
        inicio = Barrier(2, timeout=15)

        def ejecutar():
            close_old_connections()
            try:
                with usando_empresa(self.empresa):
                    inicio.wait()
                    return operacion()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            tareas = [ejecutor.submit(ejecutar) for _ in range(2)]
            return [t.result(timeout=20) for t in tareas]

    def test_confirmacion_y_liquidacion_concurrentes(self):
        self.perfil.modalidad_comision = 'PROPORCIONAL'
        self.perfil.save()
        with usando_empresa(self.empresa):
            PorcentajeVendedor.objects.create(vendedor=self.vendedor, porcentaje=Decimal('5'))
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 5, None, self.perfil, True)
            p = ventas.confirmar(p, self.vendedor, self.empresa)
            ventas.registrar_abono(p, Decimal('116'), 'USD', 'ZELLE', self.vendedor)
            abono = Abono.objects.get(presupuesto=p)

        def confirmar():
            return ventas.revisar_abono(abono, self.dueno, A.CONFIRMADO, validar_venta=True).estado

        self.assertEqual(self._en_paralelo(confirmar), [Presupuesto.Estado.VALIDADA] * 2)
        self.assertEqual(MovimientoComision.todos.count(), 1)

        def liquidar():
            try:
                liq = comisiones.liquidar(self.perfil, self.vendedor, timezone.localdate(), self.dueno, self.empresa)
            except comisiones.ErrorComision:
                return None
            return liq.total_usd

        self.assertCountEqual(self._en_paralelo(liquidar), [None, Decimal('5.00')])


class ComisionAlPagoCompletoTests(Base):
    """Sin validación: la venta se valida al confirmar; la comisión espera al pago COMPLETO."""

    def setUp(self):
        super().setUp()
        self.perfil.comision_requiere_pago = True
        self.perfil.save()

    def test_abono_parcial_no_libera_la_comision(self):
        p = self.venta([(self.prod, 5)])                  # validada, sin pagar
        with self.empresa_ctx():
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), 0)
            p = ventas.registrar_abono(p, Decimal('100'), 'USD', 'ZELLE', self.vendedor)
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), 0)
            ventas.registrar_abono(p, Decimal('16'), 'USD', 'ZELLE', self.vendedor)
            self.assertEqual(comisiones.saldo_disponible(self.perfil, self.vendedor), Comision.objects.get(presupuesto=p).monto_usd)

    def test_el_vendedor_ve_el_aviso(self):
        p = self.venta([(self.prod, 5)])
        with self.empresa_ctx():
            ventas.registrar_abono(p, Decimal('100'), 'USD', 'ZELLE', self.vendedor)
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'pagada por completo')
        self.assertContains(r, 'Los abonos parciales no la liberan')
        r = self.client.get(reverse('comisiones:detalle_vendedor'))
        self.assertContains(r, 'Espera pago completo')


class PantallaAbonosTests(Base):
    def setUp(self):
        super().setUp()
        self.p = self.venta([(self.prod, 5)])
        self.client.force_login(self.vendedor)

    def test_abonar_y_quitar(self):
        url = reverse('ventas:abonar', args=[self.p.pk])
        r = self.client.post(url, {'monto': '16', 'moneda': 'USD', 'metodo': 'ZELLE'}, follow=True)
        self.assertContains(r, 'Falta por cobrar')
        a = Abono.todos.get()
        self.client.post(reverse('ventas:anular_abono', args=[self.p.pk, a.pk]))
        self.assertTrue(Abono.todos.exists())                          # venta validada: el vendedor no puede quitarlo
        self.client.force_login(self.dueno)
        self.client.post(reverse('ventas:anular_abono', args=[self.p.pk, a.pk]))
        self.assertFalse(Abono.todos.exists())
        r = self.client.post(url, {'todo': '1', 'moneda': 'USD', 'metodo': 'ZELLE'}, follow=True)
        self.assertContains(r, 'pagada por completo')
        self.assertTrue(Presupuesto.todos.get(pk=self.p.pk).pagado)

    def test_datos_invalidos(self):
        url = reverse('ventas:abonar', args=[self.p.pk])
        self.assertContains(self.client.post(url, {'monto': 'abc', 'moneda': 'USD', 'metodo': 'ZELLE'}, follow=True), 'Revisa')
        self.assertContains(self.client.post(url, {'monto': '5', 'moneda': 'USD', 'metodo': ''}, follow=True), 'método')
        self.assertFalse(Abono.todos.exists())


class EstadoCuentaTests(Base):
    def setUp(self):
        super().setUp()
        self.pagada = self.venta([(self.prod, 1)])
        self.parcial = self.venta([(self.prod, 5)])
        self.debe = self.venta([(self.equipo, 1)])
        with self.empresa_ctx():
            ventas.registrar_pago(self.pagada, True, 'ZELLE', usuario=self.dueno)
            ventas.registrar_abono(self.parcial, Decimal('16'), 'USD', 'ZELLE', self.dueno)
            ventas.registrar_entrega(self.pagada, True)
            ventas.registrar_facturacion(self.pagada, True, 'F-001', 'C-1')
        self.client.force_login(self.dueno)
        self.url = reverse('clientes:detalle', args=[self.cliente.pk])

    def numeros(self, filtro):
        r = self.client.get(self.url, {'filtro': filtro})
        return {p.pk for p in r.context['pagina']}, r

    def test_filtros(self):
        self.assertEqual(self.numeros('pagadas')[0], {self.pagada.pk})
        self.assertEqual(self.numeros('abono_parcial')[0], {self.parcial.pk})
        self.assertEqual(self.numeros('por_cobrar')[0], {self.parcial.pk, self.debe.pk})
        self.assertEqual(self.numeros('facturadas')[0], {self.pagada.pk})
        self.assertEqual(self.numeros('entregadas')[0], {self.pagada.pk})
        self.assertEqual(self.numeros('por_entregar')[0], {self.parcial.pk, self.debe.pk})
        _, r = self.numeros('por_cobrar')
        self.assertEqual(r.context['totales']['saldo'], Decimal('100.00') + Decimal('232.00'))
        self.assertContains(r, 'Saldo por cobrar de este cliente')

    def test_reportes(self):
        r = self.client.get(reverse('clientes:estado_cuenta_pdf', args=[self.cliente.pk]), {'filtro': 'por_cobrar'})
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('Estado-cuenta', r['Content-Disposition'])
        r = self.client.get(reverse('clientes:estado_cuenta_excel', args=[self.cliente.pk]), {'filtro': 'abono_parcial'})
        ws = load_workbook(BytesIO(r.content)).active
        self.assertEqual(ws.cell(5, 1).value, self.parcial.numero)
        self.assertEqual(ws.cell(5, 8).value, 'Parcial')
        self.assertEqual(ws.cell(6, 1).value, 'TOTALES')

    def test_vendedor_solo_ve_sus_ventas(self):
        with self.empresa_ctx():
            otra = ventas.crear(self.cliente, self.vendedor2, self.empresa)
        self.client.force_login(self.vendedor)
        ids, _ = self.numeros('todos')
        self.assertNotIn(otra.pk, ids)


class TasaDeLaVentaTests(Base):
    def setUp(self):
        super().setUp()
        self.perfil.requiere_validacion = True
        self.perfil.save()

    def confirmada(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 5, None, self.perfil, True)
            p = ventas.confirmar(p, self.vendedor, self.empresa)
            Presupuesto.objects.filter(pk=p.pk).update(tasa_bs=Decimal('100'))
            return Presupuesto.objects.get(pk=p.pk)

    def test_del_dia_por_defecto(self):
        p = self.confirmada()
        with self.empresa_ctx():
            tasas.registrar(Decimal('200'), TasaCambio.Fuente.MANUAL)
            p = ventas.registrar_abono(p, Decimal('2000'), 'BS', 'PAGO_MOVIL', self.vendedor)
        self.assertEqual(Abono.todos.get().monto_usd, Decimal('10.00'))

    def test_con_la_tasa_de_la_venta(self):
        self.perfil.tasa_abonos = 'VENTA'
        self.perfil.save()
        p = self.confirmada()
        with self.empresa_ctx():
            tasas.registrar(Decimal('200'), TasaCambio.Fuente.MANUAL)
            p = ventas.registrar_abono(p, Decimal('2000'), 'BS', 'PAGO_MOVIL', self.vendedor)
            self.assertEqual((Abono.objects.get().monto_usd, Abono.objects.get().tasa_bs), (Decimal('20.00'), Decimal('100')))
            p = ventas.registrar_abono(p, Decimal('9600'), 'BS', 'PAGO_MOVIL', self.vendedor)      # 116 × 100 − 2000
            self.assertTrue(confirmar_pendientes(p, self.dueno).pagado)
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('empresas:mi_empresa')), 'name="tasa_abonos"')


class CobranzaTests(Base):
    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        self.hoy = timezone.localdate()
        self.p = self.venta([(self.prod, 5)])                          # 116
        self.p2 = self.venta([(self.equipo, 1)], vendedor=self.vendedor2)   # 232
        with self.empresa_ctx():
            ventas.registrar_abono(self.p, Decimal('16'), 'USD', 'ZELLE', self.dueno,
                                   fecha=self.hoy.replace(day=1) - timedelta(days=1))      # mes pasado
            ventas.registrar_abono(self.p, Decimal('5000'), 'BS', 'PAGO_MOVIL', self.dueno, tasa=Decimal('100'))
            ventas.registrar_abono(self.p2, Decimal('32'), 'USD', 'EFECTIVO_USD', self.dueno)

    def test_cuenta_por_fecha_del_pago(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:cobranza'))
        tot = r.context['tot']
        self.assertEqual((tot['usd'], tot['divisas'], tot['bs'], tot['n']), (Decimal('82.00'), Decimal('32.00'), Decimal('5000.00'), 2))
        self.assertContains(r, 'Los cobros confirmados aparecen en la fecha del pago')
        r = self.client.get(reverse('ventas:cobranza'), {'metodo': 'ZELLE', 'desde': '2000-01-01'})
        self.assertEqual(r.context['tot']['usd'], Decimal('16.00'))
        self.assertTrue(self.client.get(reverse('ventas:cobranza_pdf')).content.startswith(b'%PDF'))
        self.assertTrue(self.client.get(reverse('ventas:cobranza_excel')).content.startswith(b'PK'))

    def test_vendedor_solo_lo_suyo(self):
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(reverse('ventas:cobranza')).context['tot']['usd'], Decimal('50.00'))

    def test_tablero(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('core:inicio'))
        self.assertContains(r, 'Dinero ingresado este mes')
        self.assertEqual(r.context['ingresos']['usd'], Decimal('82.00'))
        self.assertEqual(r.context['por_cobrar']['usd'], Decimal('116.00') + Decimal('232.00') - Decimal('16') - Decimal('50') - Decimal('32'))
