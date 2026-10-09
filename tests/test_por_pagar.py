"""Con «validar ventas» activo: Por pagar es un paso previo y estricto; a Por validar solo entra una venta pagada."""
from django.urls import reverse

from apps.ventas import servicios as ventas
from apps.ventas.models import Presupuesto

from .test_fase5 import Base

E = Presupuesto.Estado


class PorPagarTests(Base):
    def setUp(self):
        super().setUp()
        self.perfil.requiere_validacion = True
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 2, None, self.perfil, True)
        self.p = p
        self.client.force_login(self.vendedor)
        self.client.post(reverse('ventas:accion', args=[p.pk, 'confirmar']))
        self.pago = reverse('ventas:pago_entrega', args=[p.pk])

    def estado(self):
        self.p.refresh_from_db()
        return self.p.estado

    def en_cola_de_validar(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:por_validar'))
        self.client.force_login(self.vendedor)
        return self.p.numero in r.content.decode()

    def test_regla_1_confirmada_sin_pago_va_a_por_pagar(self):
        self.assertEqual(self.estado(), E.POR_PAGAR)
        self.assertFalse(self.en_cola_de_validar())
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:lista'), {'estado': 'por_cobrar'}), self.p.numero)
        self.assertNotContains(self.client.get(reverse('ventas:lista'), {'estado': 'POR_VALIDAR'}), self.p.numero)
        inicio = self.client.get(reverse('core:inicio')).context
        self.assertEqual((inicio['por_cobrar']['n'], inicio['por_validar']['n']), (1, 0))
        r = self.client.get(reverse('ventas:detalle', args=[self.p.pk]))
        self.assertContains(r, 'Por cobrar')
        self.assertNotContains(r, 'Por pagar')
        self.assertContains(r, 'text-bg-warning')

    def test_regla_2_entregada_sin_pago_sigue_en_por_pagar(self):
        self.client.post(self.pago, {'entregado': '1'})
        self.assertEqual(self.estado(), E.POR_PAGAR)
        self.assertTrue(self.p.entregado)
        self.assertFalse(self.en_cola_de_validar())

    def test_no_se_puede_validar_sin_pago(self):
        self.client.force_login(self.dueno)
        r = self.client.post(reverse('ventas:accion', args=[self.p.pk, 'validar']), follow=True)
        self.assertContains(r, 'registra el pago antes de validarla')
        self.assertEqual(self.estado(), E.POR_PAGAR)
        # ni forzando el estado en la base: validar exige el pago
        Presupuesto.todos.filter(pk=self.p.pk).update(estado=E.POR_VALIDAR)
        with self.empresa_ctx(), self.assertRaisesMessage(ventas.ErrorVenta, 'Registra el pago'):
            ventas.validar(self.p, self.dueno)

    def test_registrar_el_pago_la_envia_a_validar(self):
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'PAGO_MOVIL', 'banco_pago': 'Banesco'})
        self.assertEqual(self.estado(), E.POR_VALIDAR)
        self.assertTrue(self.en_cola_de_validar())
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('core:inicio')).context['por_cobrar']['n'], 0)
        self.client.post(reverse('ventas:accion', args=[self.p.pk, 'validar']))
        self.assertEqual(self.estado(), E.VALIDADA)

    def test_quitar_el_pago_la_saca_de_la_cola(self):
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        self.client.post(self.pago, {'pagado': '0'})
        self.assertEqual(self.estado(), E.POR_PAGAR)
        self.assertFalse(self.en_cola_de_validar())

    def test_no_se_va_a_cobrar_vuelve_a_apartado(self):
        self.client.post(self.pago, {'entregado': '1'})
        r = self.client.post(reverse('ventas:accion', args=[self.p.pk, 'desconfirmar']), follow=True)
        self.assertContains(r, 'desmarca la entrega')
        self.client.post(self.pago, {'entregado': '0'})
        self.client.post(reverse('ventas:accion', args=[self.p.pk, 'desconfirmar']))
        self.assertEqual(self.estado(), E.APARTADO)

    def test_rechazada_y_vuelta_a_confirmar_con_pago_va_directo_a_validar(self):
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        with self.empresa_ctx():
            ventas.rechazar(self.p, self.dueno, 'Revisar precio', True, self.empresa)
        self.client.post(reverse('ventas:accion', args=[self.p.pk, 'confirmar']))
        self.assertEqual(self.estado(), E.POR_VALIDAR)

    def test_sin_validacion_confirmar_valida_y_queda_por_cobrar(self):
        self.perfil.requiere_validacion = False
        self.perfil.save()
        with self.empresa_ctx():
            q = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(q, self.prod, 1, None, self.perfil, True)
            q = ventas.confirmar(q, self.vendedor, self.empresa)
        self.assertEqual((q.estado, q.pagado), (E.VALIDADA, False))
        # la que quedó «Por pagar» de antes se valida sola al cobrarla
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        self.assertEqual(self.estado(), E.VALIDADA)


class MigracionPorPagarTests(Base):
    def test_datos_existentes_sin_pago_pasan_a_por_pagar(self):
        import importlib

        from django.apps import apps
        with self.empresa_ctx():
            a = ventas.crear(self.cliente, self.vendedor, self.empresa)
            b = ventas.crear(self.cliente, self.vendedor, self.empresa)
        Presupuesto.todos.filter(pk=a.pk).update(estado='POR_VALIDAR', pagado=False, numero='A1')
        Presupuesto.todos.filter(pk=b.pk).update(estado='POR_VALIDAR', pagado=True, numero='B1')
        importlib.import_module('apps.ventas.migrations.0006_estado_por_pagar').a_por_pagar(apps, None)
        self.assertEqual(Presupuesto.todos.get(pk=a.pk).estado, 'POR_PAGAR')
        self.assertEqual(Presupuesto.todos.get(pk=b.pk).estado, 'POR_VALIDAR')


class QuienRegistroElPagoTests(Base):
    def test_guarda_y_muestra_quien_registro_el_pago(self):
        p = self.venta([(self.prod, 1)])                      # hecha por el vendedor
        self.client.force_login(self.dueno)                   # el dueño puede cobrar la venta de un vendedor
        url = reverse('ventas:pago_entrega', args=[p.pk])
        self.client.post(url, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        p.refresh_from_db()
        self.assertEqual(p.pago_registrado_por, self.dueno)
        self.assertIsNotNone(p.pago_registrado_en)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Registró')
        self.client.post(url, {'pagado': '0'})
        p.refresh_from_db()
        self.assertEqual((p.pago_registrado_por, p.pago_registrado_en), (None, None))
