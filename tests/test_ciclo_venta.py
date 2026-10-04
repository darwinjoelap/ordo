"""Ciclo de vida unificado: al confirmar, la venta entra a la vez en «Por cobrar» (finanzas) y «Por entregar» (logística)."""
from django.urls import reverse

from apps.ventas import servicios as ventas
from apps.ventas.models import Presupuesto

from .test_fase5 import Base

E = Presupuesto.Estado


class CicloBase(Base):
    validacion = True

    def setUp(self):
        super().setUp()
        self.perfil.requiere_validacion = self.validacion
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            self.assertEqual(p.estado, E.BORRADOR)            # creación: Borrador
            ventas.agregar_item(p, self.prod, 2, None, self.perfil, True)
        self.p = p
        self.client.force_login(self.dueno)
        self.client.post(reverse('ventas:accion', args=[p.pk, 'confirmar']))
        self.p.refresh_from_db()
        self.pago = reverse('ventas:pago_entrega', args=[p.pk])

    def en(self, bandeja):
        r = self.client.get(reverse('ventas:lista'), {'estado': bandeja})
        return self.p.numero in r.content.decode()

    def inicio(self):
        c = self.client.get(reverse('core:inicio')).context
        return c['por_cobrar']['n'], c['por_entregar'], c['por_validar']['n']

    def fila(self):
        html = self.client.get(reverse('ventas:lista')).content.decode()
        i = html.index(self.p.numero)
        return html[i:html.index('</tr>', i)]


class ConValidacionTests(CicloBase):
    def test_confirmar_entra_a_las_dos_bandejas(self):
        self.assertEqual(self.p.estado, E.POR_PAGAR)
        self.assertTrue(self.en('por_cobrar') and self.en('por_entregar'))
        self.assertFalse(self.en('POR_VALIDAR'))
        self.assertEqual(self.inicio(), (1, 1, 0))

    def test_entregar_sin_cobrar(self):
        self.client.post(self.pago, {'entregado': '1'})
        self.assertTrue(self.en('por_cobrar'))
        self.assertFalse(self.en('por_entregar'))
        self.assertEqual(self.inicio(), (1, 0, 0))
        fila = self.fila()
        self.assertIn('Por cobrar', fila)
        self.assertIn('text-bg-warning', fila)                # amarillo, nunca rojo
        self.assertNotIn('Por pagar', fila)
        self.assertIn('bi-truck', fila)                       # camión aunque esté por cobrar

    def test_cobrar_sin_entregar_pasa_a_por_validar_y_sigue_por_entregar(self):
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, E.POR_VALIDAR)
        self.assertTrue(self.en('POR_VALIDAR') and self.en('por_entregar'))
        self.assertFalse(self.en('por_cobrar'))
        self.assertEqual(self.inicio(), (0, 1, 1))
        self.assertNotIn('bi-truck', self.fila())
        self.client.post(self.pago, {'entregado': '1'})
        self.assertIn('bi-truck', self.fila())                # camión también en «Por validar»
        self.assertEqual(self.inicio(), (0, 0, 1))

    def test_validada_sin_entregar_sigue_por_entregar(self):
        self.client.post(self.pago, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        self.client.post(reverse('ventas:accion', args=[self.p.pk, 'validar']))
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, E.VALIDADA)
        self.assertTrue(self.en('por_entregar'))
        self.assertIn('Pagada', self.fila())

    def test_detalle_muestra_los_dos_flujos(self):
        r = self.client.get(reverse('ventas:detalle', args=[self.p.pk]))
        self.assertContains(r, 'Por cobrar')
        self.assertContains(r, 'Por entregar')
        self.assertNotContains(r, 'alert-danger')


class SinValidacionTests(CicloBase):
    validacion = False

    def test_confirmar_valida_y_entra_a_las_dos_bandejas(self):
        self.assertEqual((self.p.estado, self.p.pagado, self.p.entregado), (E.VALIDADA, False, False))
        self.assertTrue(self.en('por_cobrar') and self.en('por_entregar'))
        self.assertEqual(self.inicio(), (1, 1, 0))
        fila = self.fila()
        self.assertIn('Por cobrar', fila)
        self.assertIn('text-bg-warning', fila)
        self.client.post(self.pago, {'entregado': '1'})
        self.assertIn('bi-truck', self.fila())
        self.assertEqual(self.inicio(), (1, 0, 0))
