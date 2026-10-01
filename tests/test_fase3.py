"""
Pruebas de la Fase 3: catálogo, inventario, proveedores.
"""
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import F
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import usando_empresa
from apps.empresas.models import Empresa, Membresia, Rol
from apps.inventario import servicios
from apps.inventario.models import Categoria, Lote, MovimientoInventario, Producto, Unidad
from apps.proveedores.models import Proveedor

HOY = timezone.localdate()


def crear_usuario(email):
    return get_user_model().objects.create_user(email, 'clave-segura-123')


class BaseInventario(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre='Farmacia Alfa')
        self.otra = Empresa.objects.create(nombre='Ferretería Beta')
        self.dueno = crear_usuario('dueno@alfa.com')
        self.almacen = crear_usuario('almacen@alfa.com')
        self.vendedor = crear_usuario('vende@alfa.com')
        for u, rol in ((self.dueno, Rol.DUENO), (self.almacen, Rol.ALMACEN), (self.vendedor, Rol.VENDEDOR)):
            Membresia.objects.create(usuario=u, empresa=self.empresa, rol=rol)
        with usando_empresa(self.empresa):
            self.cat = Categoria.objects.create(nombre='Reactivos')
            self.un = Unidad.objects.get(abreviatura='UN')
            self.prov = Proveedor.objects.create(nombre='Distribuidora Lara')
            self.prod = Producto.objects.create(codigo='GLU-01', nombre='Glucosa kit', categoria=self.cat,
                                                unidad=self.un, maneja_lotes=True, maneja_vencimiento=True,
                                                precio_venta_usd=Decimal('25.00'), stock_minimo=5)

    def ingresar(self, cantidad, lote, dias, producto=None):
        with usando_empresa(self.empresa):
            return servicios.ingresar(producto or self.prod, cantidad, Decimal('10.00'), self.dueno,
                                      numero_lote=lote, fecha_vencimiento=HOY + timedelta(days=dias) if dias is not None else None,
                                      proveedor=self.prov)


class CatalogoTests(BaseInventario):
    def test_empresa_nueva_trae_unidades(self):
        with usando_empresa(self.otra):
            self.assertTrue(Unidad.objects.filter(abreviatura='KG').exists())

    def test_mismo_codigo_en_otra_empresa_es_valido(self):
        with usando_empresa(self.otra):
            cat = Categoria.objects.create(nombre='Herramientas')
            Producto.objects.create(codigo='GLU-01', nombre='Otro', categoria=cat,
                                    unidad=Unidad.objects.get(abreviatura='UN'))
        self.assertEqual(Producto.todos.filter(codigo='GLU-01').count(), 2)

    def test_codigo_repetido_en_la_misma_empresa_muestra_error(self):
        self.client.force_login(self.dueno)
        r = self.client.post(reverse('inventario:producto_crear'), {
            'codigo': 'glu-01', 'nombre': 'Duplicado', 'categoria': self.cat.pk, 'unidad': self.un.pk,
            'precio_costo_usd': '1', 'precio_venta_usd': '2', 'stock_minimo': '0', 'factor_venta_dias': '30',
            'activo': 'on'})
        self.assertContains(r, 'Ya existe un producto con ese código')

    def test_crear_producto_normaliza_codigo(self):
        self.client.force_login(self.dueno)
        r = self.client.post(reverse('inventario:producto_crear'), {
            'codigo': ' pcr-02 ', 'nombre': 'PCR', 'categoria': self.cat.pk, 'unidad': self.un.pk,
            'precio_costo_usd': '1', 'precio_venta_usd': '2', 'stock_minimo': '0', 'factor_venta_dias': '30',
            'activo': 'on'})
        p = Producto.todos.get(codigo='PCR-02')
        self.assertRedirects(r, reverse('inventario:detalle', args=[p.pk]))
        self.assertEqual(p.empresa, self.empresa)

    def test_catalogo_categorias(self):
        self.client.force_login(self.almacen)
        r = self.client.post(reverse('inventario:catalogo', args=['categorias']), {'nombre': 'Insumos'})
        self.assertRedirects(r, reverse('inventario:catalogo', args=['categorias']))
        r = self.client.post(reverse('inventario:catalogo', args=['categorias']), {'nombre': 'insumos'})
        self.assertContains(r, 'Ya existe una categoría')


class AislamientoTests(BaseInventario):
    def test_producto_de_otra_empresa_da_404(self):
        with usando_empresa(self.otra):
            cat = Categoria.objects.create(nombre='X')
            ajeno = Producto.objects.create(codigo='AJ-1', nombre='Ajeno', categoria=cat,
                                            unidad=Unidad.objects.get(abreviatura='UN'))
        self.client.force_login(self.dueno)
        self.assertEqual(self.client.get(reverse('inventario:detalle', args=[ajeno.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('inventario:lista')), 'Ajeno')
        r = self.client.get(reverse('inventario:buscar'), {'q': 'Aje'})
        self.assertNotContains(r, 'Ajeno')

    def test_ingreso_con_producto_ajeno_es_rechazado(self):
        with usando_empresa(self.otra):
            cat = Categoria.objects.create(nombre='X')
            ajeno = Producto.objects.create(codigo='AJ-1', nombre='Ajeno', categoria=cat,
                                            unidad=Unidad.objects.get(abreviatura='UN'))
        self.client.force_login(self.dueno)
        self.client.post(reverse('inventario:ingreso'), {'producto': ajeno.pk, 'cantidad': 5, 'costo_unitario': '1'})
        self.assertFalse(Lote.todos.filter(producto=ajeno).exists())


class PermisosInventarioTests(BaseInventario):
    def test_vendedor_ve_inventario_sin_costos(self):
        self.ingresar(10, 'L1', 100)
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('inventario:lista'))
        self.assertContains(r, 'Glucosa kit')
        self.assertNotContains(r, '>Costo<')
        self.assertEqual(self.client.get(reverse('inventario:ingreso')).status_code, 403)
        self.assertEqual(self.client.get(reverse('proveedores:lista')).status_code, 403)

    def test_almacen_ve_costos_y_registra_ingresos(self):
        self.client.force_login(self.almacen)
        self.assertContains(self.client.get(reverse('inventario:lista')), '>Costo<')
        self.assertEqual(self.client.get(reverse('inventario:ingreso')).status_code, 200)


class ServiciosTests(BaseInventario):
    def test_ingreso_crea_lote_y_kardex(self):
        lote = self.ingresar(10, 'L1', 100)
        self.assertEqual((lote.cantidad_actual, lote.cantidad_inicial), (10, 10))
        mov = MovimientoInventario.todos.get(lote=lote)
        self.assertEqual((mov.tipo, mov.cantidad, mov.saldo_actual), ('INGRESO', 10, 10))

    def test_lote_existente_pide_confirmacion_y_luego_suma(self):
        self.ingresar(10, 'L1', 100)
        with self.assertRaises(servicios.LoteExistente):
            self.ingresar(5, 'L1', 100)
        with usando_empresa(self.empresa):
            servicios.ingresar(self.prod, 5, Decimal('11'), self.dueno, numero_lote='L1',
                               fecha_vencimiento=HOY, sumar_a_existente=True)
        self.assertEqual(Lote.todos.get(numero_lote='L1').cantidad_actual, 15)

    def test_producto_con_lote_obligatorio(self):
        with self.assertRaises(servicios.ErrorInventario):
            with usando_empresa(self.empresa):
                servicios.ingresar(self.prod, 5, Decimal('1'), self.dueno)

    def test_fefo_aparta_primero_lo_que_vence_antes(self):
        self.ingresar(5, 'TARDE', 200)
        self.ingresar(5, 'PRONTO', 20)
        self.ingresar(5, 'MEDIO', 90)
        with usando_empresa(self.empresa):
            reservas = servicios.apartar_fefo(self.prod, 8, self.dueno)
        self.assertEqual([(r.lote.numero_lote, r.cantidad) for r in reservas], [('PRONTO', 5), ('MEDIO', 3)])
        self.assertEqual(Lote.todos.get(numero_lote='MEDIO').cantidad_apartada, 3)

    def test_apartar_mas_de_lo_disponible_no_aparta_nada(self):
        self.ingresar(5, 'L1', 50)
        with usando_empresa(self.empresa):
            servicios.apartar_fefo(self.prod, 4, self.dueno)
            with self.assertRaises(servicios.StockInsuficiente):
                servicios.apartar_fefo(self.prod, 2, self.dueno)
        self.assertEqual(Lote.todos.get(numero_lote='L1').cantidad_apartada, 4)

    def test_ajuste_negativo_respeta_apartado(self):
        lote = self.ingresar(10, 'L1', 50)
        with usando_empresa(self.empresa):
            servicios.apartar_fefo(self.prod, 7, self.dueno)
            with self.assertRaises(servicios.StockInsuficiente):
                servicios.ajustar(lote, 'AJUSTE_NEG', 4, self.dueno, 'Rotura')
            servicios.ajustar(lote, 'AJUSTE_NEG', 3, self.dueno, 'Rotura')
        self.assertEqual(Lote.todos.get(pk=lote.pk).cantidad_actual, 7)

    def test_liberar_y_descontar(self):
        lote = self.ingresar(10, 'L1', 50)
        with usando_empresa(self.empresa):
            servicios.apartar_fefo(self.prod, 6, self.dueno)
            servicios.liberar(lote, 2, self.dueno)
            servicios.descontar_apartado(lote, 4, self.dueno)
        lote.refresh_from_db()
        self.assertEqual((lote.cantidad_actual, lote.cantidad_apartada), (6, 0))

    def test_la_base_de_datos_impide_stock_negativo(self):
        lote = self.ingresar(3, 'L1', 50)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lote.todos.filter(pk=lote.pk).update(cantidad_actual=F('cantidad_actual') - 5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lote.todos.filter(pk=lote.pk).update(cantidad_apartada=4)


class VistasInventarioTests(BaseInventario):
    def test_lista_usa_pocas_consultas_con_muchos_productos(self):
        with usando_empresa(self.empresa):
            for i in range(60):
                p = Producto.objects.create(codigo=f'P{i:03d}', nombre=f'Producto {i}', categoria=self.cat,
                                            unidad=self.un)
                for j in range(3):
                    servicios.ingresar(p, 5, Decimal('1'), self.dueno, numero_lote=f'L{j}')
        self.client.force_login(self.dueno)
        self.client.get(reverse('inventario:lista'))  # calienta sesión
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(reverse('inventario:lista'))
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 15, [q['sql'][:80] for q in ctx.captured_queries])
        self.assertEqual(len(r.context['pagina'].object_list), 50)

    def test_filtros_de_alerta(self):
        self.ingresar(2, 'VENC', -5)        # vencido y bajo mínimo
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse('inventario:lista'), {'alerta': 'vencidos'}), 'Glucosa kit')
        self.assertContains(self.client.get(reverse('inventario:lista'), {'alerta': 'stock_minimo'}), 'Glucosa kit')
        # solo tiene un lote vencido: no hay nada vendible, cuenta como agotado
        self.assertContains(self.client.get(reverse('inventario:lista'), {'alerta': 'agotados'}), 'Glucosa kit')

    def test_desmarcar_solo_activos_muestra_inactivos(self):
        Producto.todos.filter(pk=self.prod.pk).update(activo=False)
        self.client.force_login(self.dueno)
        self.assertNotContains(self.client.get(reverse('inventario:lista')), 'Glucosa kit')
        self.assertContains(self.client.get(reverse('inventario:lista'), {'q': ''}), 'Glucosa kit')

    def test_flujo_ingreso_desde_la_vista(self):
        self.client.force_login(self.almacen)
        datos = {'producto': self.prod.pk, 'cantidad': 12, 'costo_unitario': '9.50', 'numero_lote': 'A1',
                 'fecha_vencimiento': (HOY + timedelta(days=60)).isoformat(), 'proveedor': self.prov.pk}
        r = self.client.post(reverse('inventario:ingreso'), datos)
        self.assertRedirects(r, reverse('inventario:detalle', args=[self.prod.pk]))
        r = self.client.post(reverse('inventario:ingreso'), datos)       # mismo lote → confirmación
        self.assertContains(r, 'ya existe')
        r = self.client.post(reverse('inventario:ingreso'), {**datos, 'confirmar_suma': '1'})
        self.assertEqual(Lote.todos.get(numero_lote='A1').cantidad_actual, 24)
        self.assertEqual(Producto.todos.get(pk=self.prod.pk).precio_costo_usd, Decimal('9.50'))

    def test_flujo_ajuste_desde_la_vista(self):
        lote = self.ingresar(10, 'L1', 50)
        self.client.force_login(self.almacen)
        r = self.client.post(reverse('inventario:ajuste'), {'producto': self.prod.pk, 'lote': lote.pk,
                                                            'tipo': 'AJUSTE_NEG', 'cantidad': 20, 'motivo': 'x'})
        self.assertContains(r, 'Solo hay 10 disponibles')
        self.client.post(reverse('inventario:ajuste'), {'producto': self.prod.pk, 'lote': lote.pk,
                                                        'tipo': 'BAJA_VENC', 'cantidad': 4, 'motivo': 'Vencido'})
        self.assertEqual(Lote.todos.get(pk=lote.pk).cantidad_actual, 6)

    def test_detalle_y_buscador(self):
        self.ingresar(10, 'L1', 50)
        self.client.force_login(self.dueno)
        r = self.client.get(reverse('inventario:detalle', args=[self.prod.pk]))
        self.assertContains(r, 'Kardex')
        self.assertContains(r, 'L1')
        r = self.client.get(reverse('inventario:buscar'), {'q': 'gluc', 'destino': 'ajuste'})
        self.assertContains(r, f"{reverse('inventario:ajuste')}?producto={self.prod.pk}")


class ProveedoresTests(BaseInventario):
    def test_crud_y_nombre_unico(self):
        self.client.force_login(self.dueno)
        r = self.client.post(reverse('proveedores:crear'), {'nombre': 'Nuevo Prov', 'activo': 'on'})
        p = Proveedor.todos.get(nombre='Nuevo Prov')
        self.assertRedirects(r, reverse('proveedores:detalle', args=[p.pk]))
        r = self.client.post(reverse('proveedores:crear'), {'nombre': 'nuevo prov', 'activo': 'on'})
        self.assertContains(r, 'Ya existe un proveedor')
        self.assertContains(self.client.get(reverse('proveedores:lista'), {'q': 'nuevo'}), 'Nuevo Prov')


@skipUnless(connection.vendor == 'postgresql', 'La concurrencia real solo se prueba en PostgreSQL')
class ConcurrenciaTests(TransactionTestCase):
    """Dos vendedores apartan el mismo lote al mismo tiempo: nunca se sobrevende."""

    def test_apartados_simultaneos_no_sobrevenden(self):
        empresa = Empresa.objects.create(nombre='Concurrente')
        usuario = crear_usuario('c@c.com')
        with usando_empresa(empresa):
            cat = Categoria.objects.create(nombre='C')
            prod = Producto.objects.create(codigo='C1', nombre='C1', categoria=cat,
                                           unidad=Unidad.objects.get(abreviatura='UN'))
            servicios.ingresar(prod, 10, Decimal('1'), usuario)

        resultados, barrera = [], threading.Barrier(4)

        def vender():
            try:
                barrera.wait()
                with usando_empresa(empresa):
                    servicios.apartar_fefo(prod, 4, usuario)
                resultados.append('ok')
            except servicios.StockInsuficiente:
                resultados.append('sin_stock')
            finally:
                close_old_connections()
                connection.close()

        hilos = [threading.Thread(target=vender) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(sorted(resultados), ['ok', 'ok', 'sin_stock', 'sin_stock'])
        self.assertEqual(Lote.todos.get(producto=prod).cantidad_apartada, 8)
