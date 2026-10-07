"""Consulta rápida (sin conexión): pantalla sin datos del usuario, datos por empresa y permisos; unidades del presupuesto."""
from decimal import Decimal

from django.urls import reverse

from apps.clientes.models import Cliente
from apps.core.tenancy import usando_empresa
from apps.inventario.models import Categoria, Producto, Unidad
from apps.ventas import servicios as ventas

from .test_fase5 import Base


class ConsultaTests(Base):
    def test_pantalla_no_lleva_datos_del_usuario(self):
        self.client.force_login(self.vendedor)
        html = self.client.get(reverse('core:consulta')).content.decode()
        self.assertIn('js/consulta', html)
        self.assertIn(reverse('core:consulta_datos'), html)
        for dato in (self.vendedor.username, self.cliente.nombre, self.prod.nombre, 'name="csrfmiddlewaretoken"'):
            self.assertNotIn(dato, html)

    def test_datos_productos_clientes_y_tasa(self):
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('core:consulta_datos'))
        self.assertIn('no-cache', r['Cache-Control'])
        d = r.json()
        glu = next(p for p in d['productos'] if p['c'] == self.prod.codigo)
        self.assertEqual((glu['n'], Decimal(glu['p'])), (self.prod.nombre, self.prod.precio_venta_usd))
        self.assertIn('d', glu)
        self.assertEqual([c['n'] for c in d['clientes']], [self.cliente.nombre])
        self.assertIn('generado', d)

    def test_solo_datos_de_la_empresa_y_de_la_cartera(self):
        from apps.empresas.models import Empresa
        otra = Empresa.objects.create(nombre='Otra')
        with usando_empresa(otra):
            cat = Categoria.objects.create(nombre='X')
            Producto.objects.create(codigo='AJENO', nombre='Producto ajeno', categoria=cat,
                                    unidad=Unidad.objects.get(abreviatura='UN'))
        with self.empresa_ctx():
            Cliente.objects.create(nombre='Cliente de otro vendedor', vendedor=self.dueno)
            self.perfil.vendedores_ven_todos_los_clientes = False
            self.perfil.save()
        self.client.force_login(self.vendedor)
        d = self.client.get(reverse('core:consulta_datos')).json()
        self.assertNotIn('AJENO', [p['c'] for p in d['productos']])
        self.assertNotIn('Cliente de otro vendedor', [c['n'] for c in d['clientes']])

    def test_sin_sesion_redirige_al_login(self):
        for nombre in ('core:consulta', 'core:consulta_datos'):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 302)

    def test_service_worker_y_pantalla_offline(self):
        sw = self.client.get('/sw.js').content.decode()
        self.assertIn("'/consulta/datos.json'", sw)
        self.assertIn("consulta-ordo", sw)
        self.assertIn("searchParams.has('red')", sw)           # primero lo guardado; ?red=1 fuerza la red
        self.assertIn('Promise.race', sw)                      # límite de espera con señal débil
        self.assertContains(self.client.get('/offline/'), 'Señal débil')
        self.assertEqual(self.client.get('/sw.js').status_code, 200)
        self.assertIn('js/consulta', sw)                       # precargado
        self.assertContains(self.client.get('/offline/'), 'href="/consulta/"')
        self.client.force_login(self.vendedor)
        html = self.client.get(reverse('core:inicio')).content.decode()
        self.assertIn('data-ordo-consulta="1"', html)
        self.assertIn(f'href="{reverse("core:consulta")}"', html)


class UnidadesPresupuestoTests(Base):
    def test_muestra_productos_y_total_de_unidades(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 4, None, self.perfil, True)
            ventas.agregar_item(p, self.equipo, 3, None, self.perfil, True)
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse('ventas:detalle', args=[p.pk]))
        self.assertContains(r, 'Productos (2)')
        self.assertContains(r, '7 unidades')
        self.assertContains(r, '2 / 7')
