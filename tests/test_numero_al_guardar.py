"""El número del presupuesto se asigna al guardar/emitir; borradores eliminables; la venta confirmada queda por cobrar."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.ventas import servicios as ventas
from apps.ventas.models import Presupuesto

from .test_fase5 import Base


class NumeroAlGuardarTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.vendedor)

    def borrador(self, con_producto=True):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            if con_producto:
                ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
        return p

    def numero(self, p):
        return Presupuesto.todos.get(pk=p.pk).numero

    def test_nace_sin_numero_y_agregar_productos_no_lo_asigna(self):
        p = self.borrador()
        self.assertEqual(self.numero(p), '')
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Presupuesto nuevo')
        self.assertContains(r, 'Guardar presupuesto')
        self.assertContains(self.client.get(reverse('ventas:lista')), 'Sin número')
        self.assertTrue(self.client.get(reverse('ventas:pdf', args=[p.pk])).content.startswith(b'%PDF'))

    def test_guardar_asigna_numero_y_no_cambia_despues(self):
        p = self.borrador()
        r = self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'guardar': '1'}, follow=True)
        n = self.numero(p)
        self.assertTrue(n.endswith('00001'))
        self.assertContains(r, f'guardado con el número {n}')
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'guardar': '1'})
        self.client.post(reverse('ventas:accion', args=[p.pk, 'emitir']))
        self.assertEqual(self.numero(p), n)

    def test_papelera_o_sin_iva_no_asignan_numero(self):
        p = self.borrador()
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'iva_enviado': '1', 'sin_iva': '1'})
        self.assertEqual(self.numero(p), '')

    def test_no_se_guarda_ni_emite_sin_productos(self):
        p = self.borrador(con_producto=False)
        r = self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'guardar': '1'}, follow=True)
        self.assertContains(r, 'Agrega al menos un producto')
        r = self.client.post(reverse('ventas:accion', args=[p.pk, 'emitir']), follow=True)
        self.assertContains(r, 'Agrega al menos un producto')
        self.assertEqual(self.numero(p), '')
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'disabled')

    def test_emitir_apartar_y_confirmar_asignan_numero(self):
        for accion in ('emitir', 'apartar', 'confirmar'):
            p = self.borrador()
            self.client.post(reverse('ventas:accion', args=[p.pk, accion]))
            self.assertNotEqual(self.numero(p), '', accion)
        numeros = sorted(Presupuesto.todos.exclude(numero='').values_list('numero', flat=True))
        self.assertEqual([n[-5:] for n in numeros], ['00001', '00002', '00003'])      # sin huecos

    def test_abandonar_y_eliminar_borradores_no_gasta_numeros(self):
        vacio, otro = self.borrador(con_producto=False), self.borrador()
        r = self.client.post(reverse('ventas:eliminar', args=[vacio.pk]), follow=True)
        self.assertContains(r, 'Borrador eliminado')
        self.client.post(reverse('ventas:eliminar', args=[otro.pk]))
        self.assertFalse(Presupuesto.todos.filter(pk__in=[vacio.pk, otro.pk]).exists())
        p = self.borrador()
        self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'guardar': '1'})
        self.assertTrue(self.numero(p).endswith('00001'))

    def test_eliminar_borrador_con_numero_lo_libera_si_era_el_ultimo(self):
        a, b = self.borrador(), self.borrador()
        for p in (a, b):
            self.client.post(reverse('ventas:actualizar', args=[p.pk]), {'guardar': '1'})
        item = b.items.model.todos.get(presupuesto=b)
        self.client.post(reverse('ventas:actualizar', args=[b.pk]), {f'quitar_{item.pk}': '1'})   # se queda sin productos
        r = self.client.post(reverse('ventas:eliminar', args=[b.pk]), follow=True)
        self.assertContains(r, 'Su número se usará en el próximo presupuesto')
        c = self.borrador()
        self.client.post(reverse('ventas:actualizar', args=[c.pk]), {'guardar': '1'})
        self.assertTrue(self.numero(c).endswith('00002'))                # reutiliza el 00002
        r = self.client.post(reverse('ventas:eliminar', args=[a.pk]), follow=True)   # el 00001 ya no es el último
        self.assertContains(r, 'queda sin usar')

    def test_solo_se_eliminan_borradores(self):
        p = self.borrador()
        self.client.post(reverse('ventas:accion', args=[p.pk, 'emitir']))
        r = self.client.post(reverse('ventas:eliminar', args=[p.pk]), follow=True)
        self.assertTrue(Presupuesto.todos.filter(pk=p.pk).exists())
        self.assertNotContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Eliminar borrador')
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Cancelar presupuesto')

    def test_nuevo_siempre_crea_uno_en_blanco_y_lista_los_abiertos(self):
        url = reverse('ventas:nuevo')
        viejo = self.borrador()
        self.client.post(reverse('ventas:actualizar', args=[viejo.pk]), {'guardar': '1'})
        r1 = self.client.post(url, {'cliente': self.cliente.pk})
        r2 = self.client.post(url, {'cliente': self.cliente.pk})
        self.assertNotEqual(r1.url, r2.url)                                    # nunca reabre uno anterior
        self.assertNotIn(reverse('ventas:detalle', args=[viejo.pk]), (r1.url, r2.url))
        self.assertEqual(Presupuesto.todos.filter(cliente=self.cliente).count(), 3)
        r = self.client.get(url, {'cliente': self.cliente.pk})                 # elegir cliente: no carga ninguno
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Crear presupuesto nuevo')
        self.assertContains(r, self.numero(viejo))                             # pero ofrece los abiertos
        self.assertEqual(len(r.context['abiertos']), 3)

    def test_actualizar_tasa_de_un_presupuesto_emitido_hace_dias(self):
        from django.core.cache import cache

        from apps.tasas.models import TasaCambio
        from .test_fase5 import HOY
        TasaCambio.objects.all().delete()
        TasaCambio.objects.create(fecha=HOY - timedelta(days=3), bs_por_usd=Decimal('100'))
        cache.clear()
        p = self.borrador()
        self.client.post(reverse('ventas:accion', args=[p.pk, 'emitir']))
        n = self.numero(p)
        TasaCambio.objects.create(fecha=HOY, bs_por_usd=Decimal('120'))
        cache.clear()
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Actualizar a la tasa de hoy')
        self.client.post(reverse('ventas:accion', args=[p.pk, 'actualizar_tasa']))
        p = Presupuesto.todos.get(pk=p.pk)
        self.assertEqual((p.tasa_bs, p.numero, p.estado), (Decimal('120'), n, 'EMITIDO'))
        self.assertEqual(p.total_bs, (p.total_usd * 120).quantize(Decimal('0.01')))
        self.assertNotContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Actualizar a la tasa de hoy')

    def test_cron_limpia_borradores_vacios_viejos(self):
        viejo, reciente, con_producto = self.borrador(False), self.borrador(False), self.borrador()
        hace_dos_dias = timezone.now() - timedelta(days=2)
        Presupuesto.todos.filter(pk__in=[viejo.pk, con_producto.pk]).update(creado_en=hace_dos_dias)
        self.assertEqual(ventas.limpiar_borradores_vacios(), 1)
        self.assertEqual(set(Presupuesto.todos.values_list('pk', flat=True)), {reciente.pk, con_producto.pk})


class VentaPorCobrarTests(Base):
    """Confirmar (o validar) una venta NO la marca como pagada: queda por cobrar hasta registrar el pago."""

    def test_confirmar_deja_la_venta_por_cobrar(self):
        p = self.venta([(self.prod, 2)])                      # confirmada y validada
        self.assertEqual((p.estado, p.pagado, p.fecha_pago, p.metodo_pago, p.entregado), ('VALIDADA', False, None, '', False))
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('ventas:lista'), {'estado': 'ventas', 'pendiente': 'pago'})
        self.assertContains(r, p.numero)
        self.assertContains(r, 'Por cobrar')
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Por cobrar')
        self.assertContains(r, 'Registrar pago')
        inicio = self.client.get(reverse('core:inicio'))
        self.assertEqual(inicio.context['por_cobrar']['n'], 1)

    def test_el_pago_se_registra_aparte_como_la_entrega(self):
        p = self.venta([(self.prod, 1)])
        self.client.force_login(self.dueno)
        url = reverse('ventas:pago_entrega', args=[p.pk])
        self.client.post(url, {'entregado': '1'})             # entregar no la paga
        p.refresh_from_db()
        self.assertEqual((p.entregado, p.pagado), (True, False))
        self.client.post(url, {'pagado': '1', 'metodo_pago': 'ZELLE'})
        p.refresh_from_db()
        self.assertEqual((p.pagado, p.metodo_pago), (True, 'ZELLE'))
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Pagada')
        self.assertEqual(self.client.get(reverse('core:inicio')).context['por_cobrar']['n'], 0)
        self.client.post(url, {'pagado': '0'})                # se puede revertir
        p.refresh_from_db()
        self.assertFalse(p.pagado)


class DatosDelPagoTests(Base):
    def setUp(self):
        super().setUp()
        self.p = self.venta([(self.prod, 2)])                 # 2 × 20 + IVA = 46,40
        self.client.force_login(self.dueno)
        self.url = reverse('ventas:pago_entrega', args=[self.p.pk])

    def pagar(self, **datos):
        r = self.client.post(self.url, {'pagado': '1', 'metodo_pago': 'TRANSFERENCIA', **datos}, follow=True)
        self.p.refresh_from_db()
        return r

    def test_banco_referencia_y_monto_menor_es_abono_parcial(self):
        r = self.client.post(reverse('ventas:abonar', args=[self.p.pk]), {
            'monto': '40,00', 'moneda': 'USD', 'metodo': 'TRANSFERENCIA', 'banco': 'Banesco', 'referencia': '00123456'},
            follow=True)
        self.p.refresh_from_db()
        p = self.p
        self.assertEqual((p.pagado, p.banco_pago, p.referencia_pago, p.abonado_usd, p.saldo_usd),
                         (False, 'Banesco', '00123456', Decimal('40.00'), Decimal('6.40')))
        for texto in ('Banesco', 'Ref. 00123456', 'Falta por cobrar', '6,40', 'Abono parcial'):
            self.assertContains(r, texto)

    def test_sin_monto_es_pago_exacto(self):
        r = self.pagar(banco_pago='Mercantil')
        self.assertEqual((self.p.pagado, self.p.monto_pago, self.p.moneda_pago, self.p.diferencia_pago),
                         (True, Decimal('46.40'), 'USD', Decimal('0.00')))
        self.assertNotContains(r, 'Faltan')

    def test_monto_invalido_no_registra(self):
        r = self.pagar(monto_pago='abc', moneda_pago='USD')
        self.assertContains(r, 'Revisa la fecha y el monto')
        self.assertFalse(self.p.pagado)
        self.pagar(monto_pago='0', moneda_pago='USD')
        self.assertFalse(self.p.pagado)

    def test_desmarcar_borra_los_datos_del_pago(self):
        self.pagar(banco_pago='Banesco', referencia_pago='1', monto_pago='50', moneda_pago='USD')
        self.client.post(self.url, {'pagado': '0'})
        self.p.refresh_from_db()
        self.assertEqual((self.p.pagado, self.p.banco_pago, self.p.referencia_pago, self.p.monto_pago), (False, '', '', None))

    def test_formulario_muestra_lo_por_pagar_y_los_bancos(self):
        r = self.client.get(reverse('ventas:detalle', args=[self.p.pk]))
        for texto in ('name="banco"', 'name="referencia"', 'name="monto"', 'Falta por cobrar', 'Banesco'):
            self.assertContains(r, texto)
