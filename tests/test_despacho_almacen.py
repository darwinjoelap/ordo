"""Gestión de despacho por almacén: bandeja, entregas parciales, tránsito con el vendedor y bitácora."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.empresas.models import Membresia, Rol
from apps.ventas import entregas as srv
from apps.ventas import servicios as ventas
from apps.ventas.models import Entrega, Presupuesto

from .test_fase5 import Base

FIRMA = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='


class DespachoBase(Base):
    def setUp(self):
        super().setUp()
        self.perfil.despacho_por_almacen = True
        self.perfil.save()
        self.almacen = get_user_model().objects.create_user('a@alfa.com', 'clave-segura-123')
        Membresia.objects.create(usuario=self.almacen, empresa=self.empresa, rol=Rol.ALMACEN)
        self.p = self.venta([(self.prod, 5), (self.equipo, 1)])
        with self.empresa_ctx():
            self.items = {i.producto_id: i for i in self.p.items.all()}

    def cant(self, prod, n):
        return {self.items[prod.pk].pk: n}


class ServicioTests(DespachoBase):
    def test_entrega_parcial_y_total(self):
        with self.empresa_ctx():
            srv.registrar(self.p, self.almacen, self.cant(self.prod, 3), 'CLIENTE', 'Ana', 'v-1', firma=FIRMA)
            p = Presupuesto.objects.get(pk=self.p.pk)
            self.assertEqual((p.entregado, srv.estado(p)), (False, 'PARCIAL'))
            with self.assertRaisesRegex(ventas.ErrorVenta, 'como máximo 2'):
                srv.registrar(p, self.almacen, self.cant(self.prod, 3), 'CLIENTE', 'Ana', 'V-1')
            with self.assertRaisesRegex(ventas.ErrorVenta, 'cédula'):
                srv.registrar(p, self.almacen, self.cant(self.prod, 2), 'CLIENTE', 'Ana', '')
            srv.registrar(p, self.almacen, {**self.cant(self.prod, 2), **self.cant(self.equipo, 1)}, 'TRANSPORTISTA', 'Luis', 'V-2')
            p = Presupuesto.objects.get(pk=self.p.pk)
            self.assertEqual((p.entregado, srv.estado(p), Entrega.objects.count()), (True, 'ENTREGADO', 2))
            self.assertEqual(Entrega.objects.first().recibe_cedula, 'V-1')

    def test_en_transito_con_el_vendedor(self):
        with self.empresa_ctx():
            e = srv.registrar(self.p, self.almacen, {**self.cant(self.prod, 5), **self.cant(self.equipo, 1)}, 'VENDEDOR')
            p = Presupuesto.objects.get(pk=self.p.pk)
            self.assertEqual((e.recibe_usuario, e.en_transito, p.entregado, srv.estado(p)), (self.vendedor, True, False, 'EN_TRANSITO'))
            srv.confirmar_cliente(e, self.vendedor, 'Pedro', 'v-9', FIRMA)
            p = Presupuesto.objects.get(pk=self.p.pk)
            self.assertTrue(p.entregado)
            with self.assertRaises(ventas.ErrorVenta):
                srv.confirmar_cliente(e, self.vendedor, 'Pedro', 'V-9')

    def test_anular_y_firma_invalida(self):
        with self.empresa_ctx():
            with self.assertRaisesRegex(ventas.ErrorVenta, 'firma'):
                srv.registrar(self.p, self.almacen, self.cant(self.prod, 1), 'CLIENTE', 'Ana', 'V1', firma='<script>')
            e = srv.registrar(self.p, self.almacen, {**self.cant(self.prod, 5), **self.cant(self.equipo, 1)}, 'CLIENTE', 'Ana', 'V1')
            self.assertTrue(Presupuesto.objects.get(pk=self.p.pk).entregado)
            srv.anular(e)
            self.assertFalse(Presupuesto.objects.get(pk=self.p.pk).entregado)

    def test_no_vuelve_a_apartado_con_entregas(self):
        self.perfil.requiere_validacion = True
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
            p = ventas.confirmar(p, self.vendedor, self.empresa)
            srv.registrar(p, self.almacen, {p.items.get().pk: 1}, 'CLIENTE', 'Ana', 'V1')
            with self.assertRaisesRegex(ventas.ErrorVenta, 'entregas'):
                ventas.desconfirmar(p, self.vendedor, self.empresa)


class PantallasTests(DespachoBase):
    def test_almacen_despacha(self):
        self.client.force_login(self.almacen)
        self.assertContains(self.client.get(reverse('ventas:bandeja_despacho')), self.p.numero)
        self.assertContains(self.client.get(reverse('core:inicio')), 'Por despachar')
        url = reverse('ventas:despachar', args=[self.p.pk])
        r = self.client.get(url)
        self.assertContains(r, 'Registrar entrega')
        self.assertNotContains(r, '$ ')                                   # almacén no ve precios
        datos = {f'cant_{self.items[self.prod.pk].pk}': '2', f'cant_{self.items[self.equipo.pk].pk}': '0',
                 'recibe': 'CLIENTE', 'nombre': 'Ana Ruiz', 'cedula': 'V-5', 'firma': FIRMA}
        r = self.client.post(url, datos, follow=True)
        self.assertContains(r, 'registrada')
        e = Entrega.todos.get()
        self.assertTrue(self.client.get(reverse('ventas:constancia_entrega', args=[self.p.pk, e.pk])).content.startswith(b'%PDF'))
        self.assertEqual(self.client.get(reverse('ventas:despacho', args=[self.p.pk])).status_code, 200)   # nota de despacho
        self.assertEqual(self.client.post(reverse('ventas:anular_entrega', args=[self.p.pk, e.pk])).status_code, 403)

    def test_vendedor_ve_bitacora_y_confirma(self):
        with self.empresa_ctx():
            e = srv.registrar(self.p, self.almacen, self.cant(self.prod, 5), 'VENDEDOR')
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:detalle', args=[self.p.pk]))
        self.assertContains(r, 'Confirmar entrega al cliente')
        self.assertNotContains(r, 'Marcar entregado')
        self.assertIn(self.client.get(reverse('ventas:bandeja_despacho')).status_code, (302, 403))
        self.client.post(reverse('ventas:pago_entrega', args=[self.p.pk]), {'entregado': '1'})
        self.assertFalse(Presupuesto.todos.get(pk=self.p.pk).entregado)        # ya no se marca a mano
        self.client.post(reverse('ventas:confirmar_cliente', args=[self.p.pk, e.pk]), {'nombre': 'Pedro', 'cedula': 'V-3'})
        self.assertIsNotNone(Entrega.todos.get().cliente_en)

    def test_desactivado_no_cambia_nada(self):
        self.perfil.despacho_por_almacen = False
        self.perfil.save()
        self.client.force_login(self.almacen)
        self.assertEqual(self.client.get(reverse('ventas:bandeja_despacho')).status_code, 404)
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[self.p.pk])), 'Marcar entregado')
