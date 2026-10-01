"""
Paridad con BioLifeVentas (bloque B): venta sin IVA, tasa manual en Plataforma, alertas del tablero,
pendientes de cobro/entrega, inventario apartado y disponible sin lotes vencidos.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from apps.inventario.models import Lote, Producto
from apps.tasas.models import TasaCambio
from apps.tasas.servicios import tasa_vigente
from apps.ventas import servicios as ventas

from .test_fase5 import HOY, Base


class SinIvaTests(Base):
    def test_exenta_y_vuelta_al_iva_de_la_empresa(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 2, None, self.perfil, True)
            ventas.actualizar_items(p, {}, [], self.perfil, True, sin_iva=True)
        p.refresh_from_db()
        self.assertEqual((p.iva_pct, p.iva_usd, p.total_usd, p.total_bs), (Decimal('0'), Decimal('0'), Decimal('40.00'),
                                                                          Decimal('0')))
        with self.empresa_ctx():
            ventas.actualizar_items(p, {}, [], self.perfil, True, sin_iva=False)
        p.refresh_from_db()
        self.assertEqual((p.iva_pct, p.total_usd), (Decimal('16'), Decimal('46.40')))

    def test_desde_la_pantalla_y_pdf(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
        self.client.force_login(self.vendedor)                     # modo LIBRE por defecto: puede
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'iva_enviado': '1', 'sin_iva': '1'})
        p.refresh_from_db()
        self.assertEqual(p.iva_usd, Decimal('0'))
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Exento')
        self.assertTrue(self.client.get(reverse('ventas:pdf', args=[p.pk])).content.startswith(b'%PDF'))
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'iva_enviado': '1'})   # desmarcado
        p.refresh_from_db()
        self.assertEqual(p.iva_pct, Decimal('16'))

    def test_modo_fijo_el_vendedor_no_cambia_el_iva(self):
        self.perfil.modo_precio = 'FIJO'
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
        self.client.force_login(self.vendedor)
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'iva_enviado': '1', 'sin_iva': '1'})
        p.refresh_from_db()
        self.assertEqual(p.iva_pct, Decimal('16'))


class TasaPlataformaTests(Base):
    def setUp(self):
        super().setUp()
        self.root = get_user_model().objects.create_superuser('root', password='clave-segura-123')

    def test_solo_superusuario(self):
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('plataforma:tasas')).status_code, 403)

    def test_carga_manual_reemplaza_y_limpia_cache(self):
        self.client.force_login(self.root)
        self.assertEqual(tasa_vigente().bs_por_usd, Decimal('100'))
        r = self.client.post(reverse('plataforma:tasas'), {'valor': '1.036,5021', 'fecha': HOY.isoformat()})
        self.assertRedirects(r, reverse('plataforma:tasas'))
        t = TasaCambio.objects.get(fecha=HOY)
        self.assertEqual((t.bs_por_usd, t.fuente, t.registrada_por), (Decimal('1036.5021'), 'MANUAL', self.root))
        self.assertEqual(tasa_vigente().bs_por_usd, Decimal('1036.5021'))
        self.assertContains(self.client.get(reverse('plataforma:tasas')), 'Carga manual')

    def test_rechaza_valores_invalidos(self):
        self.client.force_login(self.root)
        for datos in [{'valor': '0'}, {'valor': 'abc'}, {'valor': '50', 'fecha': (HOY + timedelta(days=1)).isoformat()}]:
            self.client.post(reverse('plataforma:tasas'), datos)
        self.assertEqual(TasaCambio.objects.count(), 1)

    def test_consulta_bcv_fallida_no_rompe(self):
        from unittest import mock
        self.client.force_login(self.root)
        with mock.patch('apps.tasas.servicios.descargar_bcv', side_effect=OSError('sin red')):
            r = self.client.post(reverse('plataforma:tasas'), {'accion': 'bcv'}, follow=True)
        self.assertContains(r, 'No se pudo consultar el BCV')


class TableroYPendientesTests(Base):
    def test_por_cobrar_y_por_entregar(self):
        p = self.venta([(self.prod, 1)])
        self.venta([(self.prod, 1)])
        with self.empresa_ctx():
            ventas.registrar_pago(p, True, 'ZELLE')
            ventas.registrar_entrega(p, True)
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('core:inicio'))
        self.assertEqual(r.context['por_cobrar']['n'], 1)
        self.assertEqual(r.context['por_entregar'], 1)
        lista = self.client.get(reverse('ventas:lista'), {'estado': 'ventas', 'pendiente': 'pago'})
        self.assertNotContains(lista, p.numero)
        self.assertEqual(lista.context['totales']['n'], 1)

    def test_alertas_de_lotes(self):
        Lote.todos.filter(numero_lote='L-CERCA').update(fecha_vencimiento=HOY - timedelta(days=1))
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('core:inicio'))
        self.assertEqual(r.context['n_lotes_vencidos'], 1)
        self.assertContains(r, 'L-CERCA')


class DisponibleSinVencidosTests(Base):
    def test_lotes_vencidos_no_cuentan_como_disponibles(self):
        Lote.todos.filter(numero_lote='L-CERCA').update(fecha_vencimiento=HOY - timedelta(days=1))
        with self.empresa_ctx():
            anotado = Producto.objects.con_stock().get(pk=self.prod.pk)
            simple = Producto.objects.get(pk=self.prod.pk)
            self.assertEqual((anotado.stock_total, anotado.stock_vencido, anotado.stock_disponible), (10, 5, 5))
            self.assertEqual(simple.stock_disponible, 5)


class ApartadosTests(Base):
    def test_reporte(self):
        self.perfil.requiere_validacion = True
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 7, None, self.perfil, True)
            ventas.apartar(p, self.vendedor, self.empresa)
            q = ventas.crear(self.cliente2, self.vendedor2, self.empresa)
            ventas.agregar_item(q, self.prod, 1, None, self.perfil, True)
            ventas.apartar(q, self.vendedor2, self.empresa)
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:reporte_apartados'))
        self.assertContains(r, p.numero)
        self.assertContains(r, 'L-LEJOS')
        self.assertEqual(r.context['productos'][0]['cantidad'], 8)
        self.client.force_login(self.vendedor2)                    # solo lo suyo
        r = self.client.get(reverse('ventas:reporte_apartados'))
        self.assertNotContains(r, p.numero)
        self.assertContains(r, q.numero)
