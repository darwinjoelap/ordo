"""
Pruebas de la Fase 4: clientes, presupuestos, apartado, confirmación, validación, tasa BCV y PDF.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.core.tenancy import usando_empresa
from apps.empresas.models import Empresa, Membresia, Rol
from apps.inventario import servicios as inventario
from apps.inventario.models import Categoria, Lote, Producto, Unidad
from apps.tasas import servicios as tasas
from apps.tasas.models import TasaCambio
from apps.ventas import servicios
from apps.ventas.models import ItemPresupuesto, Presupuesto, Reserva

E = Presupuesto.Estado
HOY = timezone.localdate()

HTML_BCV = '''<html><body><div id="euro"><strong> 45,12345678 </strong></div>
<div id="dolar" class="col-sm-12"><div class="field-content"><div class="row recuadrotsmc">
<div class="col-sm-6 col-xs-6"><span> USD</span></div>
<div class="col-sm-6 col-xs-6 centrado"><strong> 1.234,56780000 </strong></div></div></div></div></body></html>'''


class Base(TestCase):
    def setUp(self):
        cache.clear()
        U = get_user_model()
        self.empresa = Empresa.objects.create(nombre='Alfa')
        self.otra = Empresa.objects.create(nombre='Beta')
        self.dueno = U.objects.create_user('d@alfa.com', 'clave-segura-123')
        self.vendedor = U.objects.create_user('v@alfa.com', 'clave-segura-123')
        self.vendedor2 = U.objects.create_user('v2@alfa.com', 'clave-segura-123')
        for u, rol in [(self.dueno, Rol.DUENO), (self.vendedor, Rol.VENDEDOR), (self.vendedor2, Rol.VENDEDOR)]:
            Membresia.objects.create(usuario=u, empresa=self.empresa, rol=rol)
        self.perfil = self.empresa.perfil
        with usando_empresa(self.empresa):
            self.cat = Categoria.objects.create(nombre='Reactivos')
            un = Unidad.objects.get(abreviatura='UN')
            self.prod = Producto.objects.create(codigo='GLU', nombre='Glucosa', categoria=self.cat, unidad=un,
                                                maneja_lotes=True, maneja_vencimiento=True,
                                                precio_costo_usd=Decimal('10.00'), precio_venta_usd=Decimal('20.00'))
            inventario.ingresar(self.prod, 5, Decimal('10'), self.dueno, numero_lote='L-LEJOS',
                                fecha_vencimiento=HOY + timedelta(days=300))
            inventario.ingresar(self.prod, 5, Decimal('10'), self.dueno, numero_lote='L-CERCA',
                                fecha_vencimiento=HOY + timedelta(days=30))
            self.cliente = Cliente.objects.create(nombre='Clínica Sol', rif='J-1', vendedor=self.vendedor)
            self.cliente2 = Cliente.objects.create(nombre='Lab Luna', rif='J-2', vendedor=self.vendedor2)
        TasaCambio.objects.create(fecha=HOY, bs_por_usd=Decimal('100.0000'))

    def empresa_ctx(self):
        return usando_empresa(self.empresa)

    def stock(self):
        with self.empresa_ctx():
            p = Producto.objects.con_stock().get(pk=self.prod.pk)
            return p.stock_total, p.stock_apartado

    def presupuesto(self, cantidad=3, vendedor=None, precio=None):
        with self.empresa_ctx():
            p = servicios.crear(self.cliente, vendedor or self.vendedor, self.empresa)
            servicios.agregar_item(p, self.prod, cantidad, precio, self.perfil, False)
            p.refresh_from_db()
            return p


class PreciosTests(Base):
    def test_fijo_ignora_el_precio_del_vendedor_pero_no_del_admin(self):
        self.perfil.modo_precio = 'FIJO'
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('5'), False), (Decimal('20.00'), False))
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('5'), True), (Decimal('5.00'), False))

    def test_libre_acepta_cualquier_precio(self):
        self.perfil.modo_precio = 'LIBRE'
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('1'), False), (Decimal('1.00'), False))

    def test_rango_marca_fuera_de_rango(self):
        self.perfil.modo_precio = 'RANGO'
        self.perfil.margen_minimo_pct = Decimal('20')
        self.perfil.margen_maximo_pct = Decimal('150')
        self.assertEqual(servicios.rango_precio(self.perfil, self.prod), (Decimal('12.00'), Decimal('25.00')))
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('15'), False)[1], False)
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('11'), False)[1], True)
        self.assertEqual(servicios.resolver_precio(self.perfil, self.prod, Decimal('26'), False)[1], True)

    def test_precio_negativo_rechazado(self):
        self.perfil.modo_precio = 'LIBRE'
        with self.assertRaises(servicios.ErrorVenta):
            servicios.resolver_precio(self.perfil, self.prod, Decimal('-1'), False)

    def test_totales_con_descuento_e_iva(self):
        p = self.presupuesto(cantidad=3)            # 3 × 20 = 60
        with self.empresa_ctx():
            servicios.actualizar_items(p, {}, [], self.perfil, True, descuento_pct=Decimal('10'))
        p.refresh_from_db()
        self.assertEqual(p.subtotal_usd, Decimal('60.00'))
        self.assertEqual(p.descuento_usd, Decimal('6.00'))
        self.assertEqual(p.iva_usd, Decimal('8.64'))     # 16 % de 54
        self.assertEqual(p.total_usd, Decimal('62.64'))


class FlujoTests(Base):
    def test_emitir_congela_la_tasa(self):
        p = self.presupuesto()
        with self.empresa_ctx():
            servicios.emitir(p)
        p.refresh_from_db()
        self.assertEqual(p.estado, E.EMITIDO)
        self.assertEqual(p.tasa_bs, Decimal('100'))
        self.assertEqual(p.total_bs, p.total_usd * 100)

    def test_no_se_emite_vacio(self):
        with self.empresa_ctx():
            p = servicios.crear(self.cliente, self.vendedor, self.empresa)
            with self.assertRaises(servicios.ErrorVenta):
                servicios.emitir(p)

    def test_flujo_completo_descuenta_stock_al_validar(self):
        self.perfil.requiere_validacion = True
        self.perfil.save()
        p = self.presupuesto(cantidad=7)
        with self.empresa_ctx():
            servicios.apartar(p, self.vendedor, self.empresa)
            self.assertEqual(self.stock(), (10, 7))
            # FEFO: primero el lote que vence antes
            reservas = {r.lote.numero_lote: r.cantidad for r in Reserva.objects.select_related('lote')}
            self.assertEqual(reservas, {'L-CERCA': 5, 'L-LEJOS': 2})
            p = servicios.confirmar(p, self.vendedor, self.empresa)
            self.assertEqual(p.estado, E.POR_VALIDAR)
            self.assertEqual(self.stock(), (10, 7))          # todavía no sale
            p = servicios.validar(p, self.dueno)
        self.assertEqual(p.estado, E.VALIDADA)
        self.assertEqual(self.stock(), (3, 0))
        self.assertEqual(p.validado_por, self.dueno)

    def test_sin_validacion_confirmar_valida_directo(self):
        self.perfil.requiere_validacion = False
        self.perfil.save()
        p = self.presupuesto(cantidad=2)
        with self.empresa_ctx():
            p = servicios.confirmar(p, self.vendedor, self.empresa)
        self.assertEqual(p.estado, E.VALIDADA)
        self.assertEqual(self.stock(), (8, 0))

    def test_senal_venta_validada(self):
        recibidas = []
        servicios.venta_validada.connect(lambda sender, presupuesto, usuario, **kw: recibidas.append(presupuesto.pk),
                                         weak=False, dispatch_uid='prueba')
        try:
            self.perfil.requiere_validacion = False
            self.perfil.save()
            p = self.presupuesto(cantidad=1)
            with self.empresa_ctx():
                servicios.confirmar(p, self.vendedor, self.empresa)
            self.assertEqual(recibidas, [p.pk])
        finally:
            servicios.venta_validada.disconnect(dispatch_uid='prueba')

    def test_apartar_sin_stock_es_todo_o_nada(self):
        with self.empresa_ctx():
            un = Unidad.objects.get(abreviatura='UN')
            otro = Producto.objects.create(codigo='X', nombre='Sin stock', categoria=self.cat, unidad=un,
                                           precio_venta_usd=Decimal('5'))
            p = self.presupuesto(cantidad=2)
            servicios.agregar_item(p, otro, 1, None, self.perfil, False)
            with self.assertRaises(servicios.ErrorVenta):
                servicios.apartar(p, self.vendedor, self.empresa)
        p.refresh_from_db()
        self.assertEqual(p.estado, E.BORRADOR)
        self.assertEqual(self.stock(), (10, 0))
        self.assertFalse(Reserva.todos.exists())

    def test_rechazo_devuelve_a_apartado(self):
        p = self.presupuesto(cantidad=2)
        with self.empresa_ctx():
            p = servicios.confirmar(p, self.vendedor, self.empresa)
            with self.assertRaises(servicios.ErrorVenta):
                servicios.rechazar(p, self.dueno, '  ', empresa=self.empresa)
            p = servicios.rechazar(p, self.dueno, 'Precio mal', True, self.empresa)
        self.assertEqual(p.estado, E.APARTADO)
        self.assertEqual(p.motivo_rechazo, 'Precio mal')
        self.assertEqual(self.stock(), (10, 2))

    def test_rechazo_liberando_stock(self):
        p = self.presupuesto(cantidad=2)
        with self.empresa_ctx():
            p = servicios.confirmar(p, self.vendedor, self.empresa)
            p = servicios.rechazar(p, self.dueno, 'Cliente desistió', False, self.empresa)
        self.assertEqual(p.estado, E.RECHAZADA)
        self.assertEqual(self.stock(), (10, 0))

    def test_cancelar_libera_y_desapartar_permite_editar(self):
        p = self.presupuesto(cantidad=4)
        with self.empresa_ctx():
            p = servicios.apartar(p, self.vendedor, self.empresa)
            p = servicios.desapartar(p, self.vendedor)
            self.assertEqual(p.estado, E.EMITIDO)
            self.assertEqual(self.stock(), (10, 0))
            p = servicios.apartar(p, self.vendedor, self.empresa)
            p = servicios.cancelar(p, self.vendedor)
        self.assertEqual(p.estado, E.CANCELADO)
        self.assertEqual(self.stock(), (10, 0))

    def test_no_se_edita_apartado(self):
        p = self.presupuesto(cantidad=1)
        with self.empresa_ctx():
            servicios.apartar(p, self.vendedor, self.empresa)
            p.refresh_from_db()
            with self.assertRaises(servicios.ErrorVenta):
                servicios.agregar_item(p, self.prod, 1, None, self.perfil, False)

    def test_vencer_apartados(self):
        p = self.presupuesto(cantidad=3)
        with self.empresa_ctx():
            servicios.apartar(p, self.vendedor, self.empresa)
        Presupuesto.todos.filter(pk=p.pk).update(apartado_hasta=timezone.now() - timedelta(hours=1))
        self.assertEqual(servicios.vencer_apartados(), 1)
        p.refresh_from_db()
        self.assertEqual(p.estado, E.VENCIDO)
        self.assertEqual(self.stock(), (10, 0))

    def test_numeracion_por_empresa(self):
        p1, p2 = self.presupuesto(), self.presupuesto()
        self.assertNotEqual(p1.numero, p2.numero)
        self.assertTrue(p2.numero.endswith('00002'))
        with usando_empresa(self.otra):
            c = Cliente.objects.create(nombre='Otro')
            q = servicios.crear(c, self.dueno, self.otra)
        self.assertTrue(q.numero.endswith('00001'))

    def test_pago_y_entrega(self):
        self.perfil.requiere_validacion = False
        self.perfil.save()
        p = self.presupuesto(cantidad=1)
        with self.empresa_ctx():
            p = servicios.confirmar(p, self.vendedor, self.empresa)
            p = servicios.registrar_pago(p, True, 'ZELLE')
            p = servicios.registrar_entrega(p, True)
        self.assertTrue(p.pagado and p.entregado)
        self.assertEqual(p.fecha_pago, HOY)


class VistasTests(Base):
    def test_vendedor_ve_solo_lo_suyo(self):
        mio = self.presupuesto(vendedor=self.vendedor)
        ajeno = self.presupuesto(vendedor=self.vendedor2)
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:lista'))
        self.assertContains(r, mio.numero)
        self.assertNotContains(r, ajeno.numero)
        self.assertEqual(self.client.get(reverse('ventas:detalle', args=[ajeno.pk])).status_code, 404)
        r = self.client.get(reverse('clientes:lista'))
        self.assertContains(r, 'Clínica Sol')
        self.assertNotContains(r, 'Lab Luna')

    def test_opcion_vendedores_ven_todos_los_clientes(self):
        self.perfil.vendedores_ven_todos_los_clientes = True
        self.perfil.save()
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse('clientes:lista')), 'Lab Luna')

    def test_dueno_ve_todo(self):
        ajeno = self.presupuesto(vendedor=self.vendedor2)
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:lista')), ajeno.numero)

    def test_vendedor_no_puede_validar(self):
        p = self.presupuesto()
        with self.empresa_ctx():
            servicios.confirmar(p, self.vendedor, self.empresa)
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(reverse('ventas:por_validar')).status_code, 403)
        self.client.post(reverse('ventas:accion', args=[p.pk, 'validar']))
        p.refresh_from_db()
        self.assertEqual(p.estado, E.POR_VALIDAR)

    def test_flujo_por_la_web(self):
        self.client.force_login(self.vendedor)
        r = self.client.post(reverse('ventas:nuevo'), {'cliente': self.cliente.pk})
        p = Presupuesto.todos.get()
        self.assertRedirects(r, reverse('ventas:detalle', args=[p.pk]))
        r = self.client.get(reverse('ventas:buscar_productos', args=[p.pk]), {'q': 'gluc'})
        self.assertContains(r, 'Glucosa')
        self.client.post(reverse('ventas:agregar_item', args=[p.pk]), {'producto': self.prod.pk, 'cantidad': 2})
        self.assertContains(self.client.get(reverse('ventas:detalle', args=[p.pk])), 'Glucosa')
        self.client.post(reverse('ventas:accion', args=[p.pk, 'confirmar']))
        p.refresh_from_db()
        self.assertEqual(p.estado, E.POR_VALIDAR)
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('ventas:por_validar')), p.numero)
        r = self.client.post(reverse('ventas:accion', args=[p.pk, 'validar']), {'volver': '/ventas/por-validar/'})
        self.assertRedirects(r, reverse('ventas:por_validar'))
        p.refresh_from_db()
        self.assertEqual(p.estado, E.VALIDADA)
        r = self.client.get(reverse('core:inicio'))
        self.assertContains(r, 'Ventas validadas del mes')

    def test_vendedor_en_modo_fijo_no_cambia_precio_por_la_web(self):
        self.perfil.modo_precio = 'FIJO'
        self.perfil.save()
        p = self.presupuesto(cantidad=1)
        self.client.force_login(self.vendedor)
        self.client.post(reverse('ventas:agregar_item', args=[p.pk]),
                         {'producto': self.prod.pk, 'cantidad': 1, 'precio': '1.00'})
        self.assertEqual(ItemPresupuesto.todos.get().precio_usd, Decimal('20.00'))

    def test_pdf_en_las_tres_monedas(self):
        p = self.presupuesto()
        with self.empresa_ctx():
            servicios.emitir(p)
        self.client.force_login(self.vendedor)
        for moneda in ('ambas', 'usd', 'bs'):
            r = self.client.get(reverse('ventas:pdf', args=[p.pk]), {'moneda': moneda})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content.startswith(b'%PDF'))

    def test_lista_de_precios_en_bs(self):
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('inventario:lista_precios'), {'generar': 1, 'en_bs': 1})
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_crear_cliente_desde_presupuesto(self):
        self.client.force_login(self.vendedor)
        r = self.client.post(reverse('clientes:crear') + '?volver=presupuesto', {'nombre': 'Nuevo', 'rif': 'j-9',
                                                                                'activo': 'on'})
        c = Cliente.todos.get(nombre='Nuevo')
        self.assertRedirects(r, f'/ventas/nuevo/?cliente={c.pk}')
        self.assertEqual(c.vendedor, self.vendedor)
        self.assertEqual(c.rif, 'J-9')
        r = self.client.post(reverse('clientes:crear'), {'nombre': 'Duplicado', 'rif': 'J-9'})
        self.assertContains(r, 'Ya existe un cliente con ese RIF')

    def test_tasa_en_la_barra(self):
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('core:inicio')), '100,00')


class TasaTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_lee_el_html_del_bcv(self):
        self.assertEqual(tasas.leer_tasa_html(HTML_BCV), Decimal('1234.5678'))

    def test_html_sin_bloque_falla(self):
        with self.assertRaises(ValueError):
            tasas.leer_tasa_html('<html></html>')

    def test_tasa_vigente_y_cache(self):
        self.assertIsNone(tasas.tasa_vigente())
        tasas.registrar(Decimal('50'), TasaCambio.Fuente.MANUAL)
        self.assertEqual(tasas.tasa_vigente().bs_por_usd, Decimal('50'))
        tasas.registrar(Decimal('51'), TasaCambio.Fuente.MANUAL)     # mismo día: actualiza
        self.assertEqual(TasaCambio.objects.count(), 1)
        self.assertEqual(tasas.tasa_vigente().bs_por_usd, Decimal('51'))

    def test_comando_programado_no_se_cae_sin_red(self):
        from unittest import mock
        with mock.patch('apps.tasas.servicios.requests.get', side_effect=OSError('sin red')):
            call_command('tareas_programadas', stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
