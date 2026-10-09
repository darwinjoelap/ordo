"""Catálogo de transportistas y vehículos y su uso en la nota de despacho."""
from django.urls import reverse

from apps.ventas.models import Despacho, Transportista, Vehiculo

from .test_fase5 import Base

DATOS = {'transportista': 'Pedro Pérez', 'cedula': 'V-1', 'telefono': '0414', 'vehiculo': 'Hilux blanca',
         'placa': 'ab 123 cd', 'empresa_transporte': '', 'direccion_entrega': '', 'observaciones': '',
         'fecha': '2026-10-09', 'con_precios': '1'}


class CatalogoTests(Base):
    def test_solo_gestion_y_almacen(self):
        self.client.force_login(self.vendedor)
        self.assertIn(self.client.get(reverse('ventas:transporte')).status_code, (302, 403))
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:transporte')), 'Transportistas')

    def test_crear_editar_validar_y_desactivar(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse('ventas:transportista_crear'), {'nombre': '  Luis   Gil ', 'cedula': 'v-9'})
        self.client.post(reverse('ventas:transportista_crear'), {'nombre': 'luis gil'})            # repetido
        self.client.post(reverse('ventas:vehiculo_crear'), {'placa': 'a1b 2c3', 'descripcion': 'NPR'})
        self.client.post(reverse('ventas:vehiculo_crear'), {'placa': 'A1B2C3'})                     # repetida
        t, v = Transportista.todos.get(), Vehiculo.todos.get()
        self.assertEqual((t.nombre, t.cedula, v.placa), ('Luis Gil', 'V-9', 'A1B2C3'))
        self.client.post(reverse('ventas:transportista_editar', args=[t.pk]), {'nombre': 'Luis Gil', 'telefono': '0412'})
        self.client.post(reverse('ventas:transporte_activar', args=['v', v.pk]))
        t.refresh_from_db(); v.refresh_from_db()
        self.assertEqual((t.telefono, v.activo), ('0412', False))


class DespachoConCatalogoTests(Base):
    def setUp(self):
        super().setUp()
        self.p = self.venta([(self.prod, 1)])
        self.url = reverse('ventas:despacho', args=[self.p.pk])
        self.client.force_login(self.vendedor)

    def test_el_catalogo_se_ofrece_en_la_nota(self):
        with self.empresa_ctx():
            Transportista.objects.create(nombre='Ana Ruiz', cedula='V-5')
            Vehiculo.objects.create(placa='XYZ1', descripcion='Camión', activo=True)
            Vehiculo.objects.create(placa='OFF1', activo=False)
        r = self.client.get(self.url)
        self.assertContains(r, 'Ana Ruiz')
        self.assertContains(r, 'XYZ1')
        self.assertNotContains(r, 'OFF1')
        self.assertContains(r, 'Escribir otro')

    def test_escrito_a_mano_se_guarda_en_el_catalogo(self):
        self.client.post(self.url, {**DATOS, 'guardar_catalogo': '1'})
        t, v = Transportista.todos.get(), Vehiculo.todos.get()
        self.assertEqual((t.nombre, t.cedula, v.placa, v.descripcion), ('Pedro Pérez', 'V-1', 'AB123CD', 'Hilux blanca'))
        self.client.post(self.url, {**DATOS, 'guardar_catalogo': '1'})                  # no duplica
        self.assertEqual((Transportista.todos.count(), Vehiculo.todos.count()), (1, 1))
        self.assertEqual(Despacho.todos.get().placa, 'AB123CD')

    def test_sin_marcar_no_se_guarda(self):
        self.client.post(self.url, DATOS)
        self.assertEqual((Transportista.todos.count(), Vehiculo.todos.count(), Despacho.todos.count()), (0, 0, 1))
