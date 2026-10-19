"""Servicios: producto sin inventario, descripción técnica en el PDF, agenda, realizado, cobro y reportes."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.inventario import servicios as inventario
from apps.inventario.models import Lote, Producto, Unidad
from apps.ventas import agenda
from apps.ventas import servicios as ventas
from apps.ventas.models import ItemPresupuesto, Presupuesto

from .test_fase5 import Base

FIRMA = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
E = Presupuesto.Estado


class ServiciosBase(Base):
    def setUp(self):
        super().setUp()
        self.perfil.maneja_servicios = True
        self.perfil.save()
        with self.empresa_ctx():
            self.ha = Unidad.objects.create(nombre='Hectárea', abreviatura='HA')
            self.fumigacion = Producto.objects.create(
                codigo='SRV-01', nombre='Fumigación aérea', tipo=Producto.Tipo.SERVICIO, categoria=self.cat2,
                unidad=self.ha, precio_venta_usd=Decimal('15'), precio_costo_usd=Decimal('6'),
                descripcion='Aplicación con dron.\nIncluye informe.')

    def venta_servicio(self, items=None):
        """Venta confirmada (sin validación: queda Validada y por cobrar)."""
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            for prod, cant in (items or [(self.fumigacion, 10)]):
                ventas.agregar_item(p, prod, cant, None, self.perfil, True)
            return ventas.confirmar(p, self.vendedor, self.empresa)

    def linea(self, p):
        with self.empresa_ctx():
            return ItemPresupuesto.objects.select_related('producto', 'presupuesto').get(
                presupuesto=p, producto=self.fumigacion)


class SinInventarioTests(ServiciosBase):
    def test_se_vende_sin_stock_y_no_toca_lotes(self):
        p = self.venta_servicio([(self.fumigacion, 10), (self.prod, 2)])
        self.assertEqual(p.estado, E.VALIDADA)
        self.assertEqual(p.subtotal_usd, Decimal('150.00') + 2 * self.prod.precio_venta_usd)
        with self.empresa_ctx():
            self.assertFalse(Lote.objects.filter(producto=self.fumigacion).exists())
            self.assertEqual(self.linea(p).descripcion_tecnica, 'Aplicación con dron.\nIncluye informe.')

    def test_no_admite_ingresos_y_queda_fuera_del_inventario(self):
        with self.empresa_ctx():
            with self.assertRaisesRegex(inventario.ErrorInventario, 'servicio'):
                inventario.ingresar(self.fumigacion, 5, Decimal('1'), self.dueno)
            self.assertNotIn(self.fumigacion, Producto.objects.fisicos())
            self.assertFalse(self.fumigacion.alerta_stock_minimo)

    def test_cada_agregado_es_una_linea_nueva(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.fumigacion, 5, None, self.perfil, True)
            ventas.agregar_item(p, self.fumigacion, 3, None, self.perfil, True)
            self.assertEqual(ItemPresupuesto.objects.filter(presupuesto=p).count(), 2)

    def test_apagado_no_deja_agregar(self):
        self.perfil.maneja_servicios = False
        self.perfil.save()
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            with self.assertRaisesRegex(ventas.ErrorVenta, 'desactivados'):
                ventas.agregar_item(p, self.fumigacion, 1, None, self.perfil, True)

    def test_devolucion_no_reingresa(self):
        p = self.venta_servicio()
        with self.empresa_ctx():
            i = self.linea(p)
            dev = ventas.devolver(p, self.dueno, {i.pk: (10, True)}, 'No se pudo hacer')
            fila = dev.items.get()
            self.assertEqual((fila.lote, fila.reingresa), (None, False))
            self.assertEqual(Presupuesto.objects.get(pk=p.pk).estado, E.DEVUELTA)

    def test_descripcion_y_fecha_editables_en_el_presupuesto(self):
        manana = timezone.localdate() + timedelta(days=1)
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            i = ventas.agregar_item(p, self.fumigacion, 4, None, self.perfil, True)
            ventas.actualizar_items(p, {i.pk: (4, i.precio_usd)}, [], self.perfil, True,
                                    servicios_datos={i.pk: {'descripcion': 'Lote norte, 4 ha', 'fecha': manana}})
            i.refresh_from_db()
            self.assertEqual((i.descripcion_tecnica, i.fecha_servicio), ('Lote norte, 4 ha', manana))
            self.assertEqual(i.estado_servicio, 'PROGRAMADO')


class EjecucionTests(ServiciosBase):
    def test_programar_realizar_y_deshacer(self):
        p = self.venta_servicio()
        hoy = timezone.localdate()
        with self.empresa_ctx():
            i = self.linea(p)
            self.assertEqual(i.estado_servicio, 'PENDIENTE')
            agenda.programar(i, hoy - timedelta(days=1), responsable_nombre='  Técnico   Pérez ')
            i = self.linea(p)
            self.assertEqual((i.estado_servicio, i.responsable_visible), ('ATRASADO', 'Técnico Pérez'))
            with self.assertRaisesRegex(ventas.ErrorVenta, 'futura'):
                agenda.realizar(i, self.vendedor, timezone.now() + timedelta(days=1))
            agenda.realizar(i, self.vendedor, nota='Listo', recibe_nombre='Ana', recibe_cedula='v-1', firma=FIRMA)
            i = self.linea(p)
            self.assertEqual((i.estado_servicio, i.recibe_cedula), ('REALIZADO', 'V-1'))
            self.assertTrue(Presupuesto.objects.get(pk=p.pk).entregado)          # venta solo de servicios
            with self.assertRaisesRegex(ventas.ErrorVenta, 'ya está'):
                agenda.realizar(i, self.vendedor)
            with self.assertRaisesRegex(ventas.ErrorVenta, 'Deshaz'):
                agenda.programar(i, hoy)
            agenda.deshacer(i)
            i = self.linea(p)
            self.assertEqual((i.estado_servicio, i.nota_servicio, i.recibe_firma), ('ATRASADO', '', ''))
            self.assertFalse(Presupuesto.objects.get(pk=p.pk).entregado)

    def test_solo_se_realiza_en_venta_confirmada(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.fumigacion, 1, None, self.perfil, True)
            i = self.linea(p)
            agenda.programar(i, timezone.localdate())          # se puede programar desde el presupuesto
            with self.assertRaisesRegex(ventas.ErrorVenta, 'confirmada'):
                agenda.realizar(self.linea(p), self.vendedor)

    def test_venta_mixta_la_entrega_la_lleva_la_mercancia(self):
        p = self.venta_servicio([(self.fumigacion, 2), (self.prod, 1)])
        with self.empresa_ctx():
            agenda.realizar(self.linea(p), self.vendedor)
            self.assertFalse(Presupuesto.objects.get(pk=p.pk).entregado)

    def test_agenda_y_cobro(self):
        hoy = timezone.localdate()
        p1, p2, p3 = self.venta_servicio(), self.venta_servicio(), self.venta_servicio()
        with self.empresa_ctx():
            agenda.programar(self.linea(p1), hoy)
            agenda.programar(self.linea(p2), hoy + timedelta(days=1))
            agenda.realizar(self.linea(p3), self.vendedor)
            qs = agenda.de_ventas(Presupuesto.objects.all())
            r = agenda.resumen(qs)
            self.assertEqual((r['hoy'], r['manana'], r['atrasados'], r['por_programar'], r['por_cobrar']), (1, 1, 0, 0, 1))
            ventas.registrar_pago(Presupuesto.objects.get(pk=p3.pk), True, 'ZELLE', usuario=self.dueno)
            self.assertEqual(agenda.resumen(qs)['por_cobrar'], 0)
            datos = agenda.reporte(qs, hoy, hoy)
            self.assertEqual((datos['n'], datos['total'], datos['por_cobrar']), (1, Decimal('150.00'), Decimal('0')))

    def test_whatsapp(self):
        self.assertEqual(agenda.telefono_whatsapp('0414-123.45.67'), '584141234567')
        self.assertEqual(agenda.telefono_whatsapp('+58 412 1234567'), '584121234567')
        self.assertEqual(agenda.telefono_whatsapp('123'), '')
        p = self.venta_servicio()
        self.perfil.mensaje_servicio = 'Hola {cliente}: {servicio} el {fecha} {mal}'      # variable inválida
        with self.empresa_ctx():
            i = self.linea(p)
            agenda.programar(i, timezone.localdate())
            enlace = agenda.enlace_whatsapp(self.linea(p), self.perfil)
            self.assertIn('Fumigaci%C3%B3n', enlace)          # cae en la plantilla por defecto sin romperse


class PantallasTests(ServiciosBase):
    def test_flujo_por_pantallas(self):
        p = self.venta_servicio([(self.fumigacion, 10), (self.prod, 1)])
        i = self.linea(p)
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Productos y servicios')
        self.assertContains(r, 'Incluye informe.')
        hoy = timezone.localdate()
        url = reverse('ventas:servicio', args=[i.pk])
        self.client.post(url, {'accion': 'programar', 'fecha': hoy.isoformat(), 'hora': '08:30',
                               'responsable': str(self.vendedor.pk)})
        r = self.client.get(reverse('ventas:agenda_servicios'))
        self.assertContains(r, 'Fumigación aérea')
        self.assertContains(r, 'wa.me')
        self.assertContains(self.client.get(reverse('core:inicio')), 'Por programar')
        self.client.post(url, {'accion': 'realizar', 'fecha_realizado': hoy.isoformat(), 'nota': 'OK', 'firma': FIRMA})
        self.assertIsNotNone(ItemPresupuesto.todos.get(pk=i.pk).realizado_en)
        r = self.client.post(url, {'accion': 'deshacer'}, follow=True)
        self.assertContains(r, 'Solo el dueño')                     # el vendedor no deshace
        self.assertTrue(self.client.get(reverse('ventas:constancia_servicio', args=[i.pk])).content.startswith(b'%PDF'))
        self.assertTrue(self.client.get(reverse('ventas:pdf', args=[p.pk])).content.startswith(b'%PDF'))
        self.assertEqual(self.client.get(reverse('ventas:reporte_servicios')).status_code, 403)   # reportes: gestión

    def test_reporte_y_otro_vendedor(self):
        p = self.venta_servicio()
        with self.empresa_ctx():
            agenda.realizar(self.linea(p), self.vendedor)
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:reporte_servicios')), 'Fumigación aérea')
        self.assertTrue(self.client.get(reverse('ventas:reporte_servicios_pdf')).content.startswith(b'%PDF'))
        self.assertEqual(self.client.get(reverse('ventas:reporte_servicios_excel')).status_code, 200)
        self.client.force_login(self.vendedor2)
        self.assertEqual(self.client.get(reverse('ventas:servicio', args=[self.linea(p).pk])).status_code, 404)

    def test_apagado_oculta_todo(self):
        self.perfil.maneja_servicios = False
        self.perfil.save()
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('ventas:agenda_servicios')).status_code, 404)
        self.assertNotContains(self.client.get(reverse('core:inicio')), 'Agenda de servicios')
        r = self.client.get(reverse('inventario:producto_crear'))
        self.assertNotContains(r, 'name="tipo"')

    def test_inventario_separa_productos_y_servicios(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('inventario:lista'))
        self.assertNotContains(r, 'Fumigación aérea')
        r = self.client.get(reverse('inventario:lista') + '?tipo=SERVICIO')
        self.assertContains(r, 'Fumigación aérea')
        self.assertContains(self.client.get(reverse('inventario:detalle', args=[self.fumigacion.pk])), 'Descripción técnica')


class FichaServicioTests(ServiciosBase):
    def test_ficha_de_servicio_sin_campos_de_producto(self):
        self.client.force_login(self.dueno)
        url = reverse('inventario:producto_crear')
        self.assertContains(self.client.get(url + '?tipo=SERVICIO'), 'Nuevo servicio')
        r = self.client.post(url, {'tipo': 'SERVICIO', 'codigo': 'srv-9', 'nombre': 'Poda', 'unidad': self.ha.pk,
                                   'marca': '', 'precio_costo_usd': '1', 'precio_venta_usd': '5', 'factor_venta_dias': '30',
                                   'stock_minimo': '7', 'maneja_lotes': 'on', 'descripcion': 'Poda técnica', 'activo': 'on'})
        self.assertEqual(r.status_code, 302)
        with self.empresa_ctx():
            s = Producto.objects.get(codigo='SRV-9')
            self.assertEqual((s.categoria.nombre, s.stock_minimo, s.maneja_lotes, s.marca), ('Servicios', 0, False, None))
        r = self.client.post(url, {'tipo': 'PRODUCTO', 'codigo': 'P-9', 'nombre': 'X', 'unidad': self.ha.pk,
                                   'precio_costo_usd': '1', 'precio_venta_usd': '5', 'factor_venta_dias': '30',
                                   'stock_minimo': '0', 'activo': 'on'})
        self.assertContains(r, 'Este campo es obligatorio')          # el producto sí exige categoría
