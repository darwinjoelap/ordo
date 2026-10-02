"""Pantalla del presupuesto: Bs en borrador (tasa referencial), sin stock en rojo, papelera, sin IVA y búsqueda."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.urls import reverse

from apps.inventario.models import Producto, Unidad
from apps.tasas.models import TasaCambio
from apps.ventas import servicios as ventas
from apps.ventas.models import ItemPresupuesto

from .test_fase5 import HOY, Base


class PresupuestoPantallaTests(Base):
    def setUp(self):
        super().setUp()
        cache.clear()
        TasaCambio.objects.all().delete()
        TasaCambio.objects.create(fecha=HOY, bs_por_usd=Decimal('100'))
        cache.clear()
        with self.empresa_ctx():
            self.agotado = Producto.objects.create(codigo='AG', nombre='Agotado X', categoria=self.cat2,
                                                   unidad=Unidad.objects.get(abreviatura='UN'),
                                                   precio_venta_usd=Decimal('10'))
            self.p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(self.p, self.prod, 2, None, self.perfil, True)      # 2 × 20
        self.client.force_login(self.vendedor)
        self.url = reverse('ventas:detalle', args=[self.p.pk])

    def test_borrador_muestra_bs_con_la_tasa_de_hoy_sin_guardarla(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'Bs 4\xa0000,00')               # subtotal de la línea: 2 × 20 × 100
        self.assertContains(r, 'referencial')
        self.p.refresh_from_db()
        self.assertIsNone(self.p.tasa_bs)                     # no se congela hasta emitir
        self.assertContains(r, 'moneda=bs')                   # PDF «Solo Bs» disponible desde el borrador

    def test_pdf_solo_bs_en_borrador(self):
        with mock.patch('apps.ventas.views.presupuesto_pdf', return_value=b'%PDF') as pdf:
            self.client.get(reverse('ventas:pdf', args=[self.p.pk]), {'moneda': 'bs'})
            p, = pdf.call_args.args[:1]
            self.assertEqual((p.tasa_bs, pdf.call_args.kwargs['moneda'], pdf.call_args.kwargs['tasa_referencial']),
                             (Decimal('100'), 'bs', True))
        for moneda in ('bs', 'usd', 'ambas'):
            r = self.client.get(reverse('ventas:pdf', args=[self.p.pk]), {'moneda': moneda})
            self.assertTrue(r.content.startswith(b'%PDF'))

    def test_sin_stock_en_rojo_al_buscar_y_al_agregar(self):
        r = self.client.get(reverse('ventas:buscar_productos', args=[self.p.pk]), {'q': 'Agotado'})
        self.assertContains(r, 'SIN STOCK')
        self.assertContains(r, 'btn btn-success')
        self.assertContains(r, 'Agregar')
        r = self.client.post(reverse('ventas:agregar_item', args=[self.p.pk]),
                             {'producto': self.agotado.pk, 'cantidad': 1}, follow=True)
        self.assertContains(r, 'sin stock suficiente')
        self.assertContains(r, 'text-danger fw-bold')
        self.assertContains(r, 'SIN STOCK')

    def test_papelera_quita_el_producto(self):
        r = self.client.get(self.url)
        item = ItemPresupuesto.todos.get(presupuesto=self.p)
        self.assertContains(r, f'name="quitar_{item.pk}"')
        self.assertContains(r, 'bi-trash')
        self.assertNotContains(r, 'type="checkbox" class="form-check-input" name="quitar_')
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]), {f'quitar_{item.pk}': '1'})
        self.assertFalse(ItemPresupuesto.todos.filter(presupuesto=self.p).exists())

    def test_sin_iva_quita_la_fila_del_iva(self):
        self.assertContains(self.client.get(self.url), 'IVA (16')
        self.client.post(reverse('ventas:actualizar', args=[self.p.pk]), {'iva_enviado': '1', 'sin_iva': '1'})
        r = self.client.get(self.url)
        self.assertNotContains(r, 'IVA (')
        self.assertNotContains(r, 'Exento')
        self.assertContains(r, 'requestSubmit')               # el interruptor guarda al tocarlo
