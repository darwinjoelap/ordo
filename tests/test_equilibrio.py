"""Punto de equilibrio: cálculo mensual, costos fijos, deducciones y permisos."""
from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.finanzas import servicios as finanzas
from apps.finanzas.models import CostoFijo, Deduccion
from apps.ventas import servicios as ventas

from .test_fase5 import HOY, Base

MES = HOY.replace(day=1)


class CalculoTests(Base):
    """Glucosa: precio 20; Centrífuga: precio 200, costo 100. Comisión del vendedor 5 %."""

    def calc(self):
        with self.empresa_ctx():
            return finanzas.calcular(HOY.year, HOY.month)

    def test_margen_resta_costo_comision_y_deducciones(self):
        p = self.venta([(self.equipo, 1)])                       # 200 sin IVA, costo 100, comisión 10
        with self.empresa_ctx():
            costo = sum(i.cantidad * i.costo_usd for i in p.items.all())
            Deduccion.objects.create(nombre='Banco', porcentaje=Decimal('2'), base='VENTA')        # 4
            Deduccion.objects.create(nombre='ISLR', porcentaje=Decimal('10'), base='UTILIDAD')     # 10 % de (200 − costo)
        r = self.calc()
        t = r['totales']
        self.assertEqual(t['ingreso'], Decimal('200.00'))
        self.assertEqual(t['costo'], costo)
        self.assertEqual(t['comision'], Decimal('10.00'))
        self.assertEqual(t['deducciones'], Decimal('4.00') + ((200 - costo) * Decimal('0.1')).quantize(Decimal('0.01')))
        self.assertEqual(t['margen'], 200 - costo - 10 - t['deducciones'])
        self.assertEqual(r['serie'][-1]['dia'], HOY.day)
        self.assertTrue(r['en_curso'])

    def test_equilibrio_se_alcanza_el_dia_que_cubre_los_fijos(self):
        self.venta([(self.equipo, 1)])
        with self.empresa_ctx():
            margen = finanzas.calcular(HOY.year, HOY.month)['acumulado']
            finanzas.agregar_costo('Alquiler', margen - 1, MES, True)
        r = self.calc()
        self.assertEqual(r['equilibrio_dia'], HOY.day)
        self.assertEqual(r['utilidad'], Decimal('1.00'))
        self.assertEqual(r['falta'], 0)

    def test_sin_alcanzar_muestra_lo_que_falta(self):
        self.venta([(self.equipo, 1)])
        with self.empresa_ctx():
            margen = finanzas.calcular(HOY.year, HOY.month)['acumulado']
            finanzas.agregar_costo('Nómina', margen + 500, MES, True)
        r = self.calc()
        self.assertIsNone(r['equilibrio_dia'])
        self.assertEqual(r['falta'], Decimal('500.00'))
        self.assertLess(r['utilidad'], 0)
        self.assertIsNotNone(r['ventas_equilibrio'])
        self.assertIsNotNone(r['proyeccion'])

    def test_devolucion_resta_ingreso(self):
        p = self.venta([(self.prod, 4)])                         # 80
        with self.empresa_ctx():
            item = p.items.get()
            ventas.devolver(p, self.dueno, {item.pk: (2, True)}, 'Sobraron')
        self.assertEqual(self.calc()['totales']['ingreso'], Decimal('40.00'))

    def test_venta_sin_validar_no_cuenta(self):
        with self.empresa_ctx():
            p = ventas.crear(self.cliente, self.vendedor, self.empresa)
            ventas.agregar_item(p, self.prod, 1, None, self.perfil, True)
        self.assertEqual(self.calc()['totales']['ingreso'], 0)

    def test_mes_futuro_y_sin_fijos(self):
        with self.empresa_ctx():
            r = finanzas.calcular(HOY.year + 1, 1)
        self.assertTrue(r['futuro'])
        self.assertEqual(r['serie'], [])
        self.assertIsNone(self.calc()['equilibrio_dia'])          # sin costos fijos no hay punto de equilibrio


class CostosTests(Base):
    def test_vigencia_por_mes(self):
        with self.empresa_ctx():
            finanzas.agregar_costo('Alquiler', Decimal('300'), date(2026, 3, 1), True)
            finanzas.agregar_costo('Reparación', Decimal('50'), date(2026, 4, 1), False)
            def total(m):
                return sum(c.monto_usd for c in finanzas.costos_del_mes(date(2026, m, 1)))
            self.assertEqual((total(2), total(3), total(4), total(5)), (0, 300, 350, 300))

    def test_quitar_conserva_los_meses_anteriores(self):
        with self.empresa_ctx():
            c = finanzas.agregar_costo('Alquiler', Decimal('300'), date(2026, 3, 1), True)
            self.assertFalse(finanzas.quitar_costo(c, date(2026, 6, 1)))
            self.assertEqual(finanzas.costos_del_mes(date(2026, 5, 1)).count(), 1)
            self.assertEqual(finanzas.costos_del_mes(date(2026, 6, 1)).count(), 0)
            self.assertTrue(finanzas.quitar_costo(c, date(2026, 3, 1)))
            self.assertEqual(CostoFijo.objects.count(), 0)


class PantallaTests(Base):
    def test_dueno_ve_y_gestiona(self):
        self.venta([(self.equipo, 1)])
        self.client.force_login(self.dueno)
        url = reverse('finanzas:equilibrio')
        self.assertContains(self.client.get(url), 'Punto de equilibrio')
        self.client.post(reverse('finanzas:costo_agregar'), {'mes': f'{MES:%Y-%m}', 'nombre': 'Alquiler', 'monto': '10', 'recurrente': '1'})
        self.client.post(reverse('finanzas:deduccion_agregar'), {'mes': f'{MES:%Y-%m}', 'nombre': 'Banco', 'porcentaje': '2,5', 'base': 'VENTA'})
        with self.empresa_ctx():
            c, d = CostoFijo.objects.get(), Deduccion.objects.get()
            self.assertEqual((c.monto_usd, c.hasta, d.porcentaje), (Decimal('10'), None, Decimal('2.5')))
        r = self.client.get(url)
        self.assertContains(r, 'Punto de equilibrio alcanzado')
        self.assertContains(r, 'pe-datos')
        self.client.post(reverse('finanzas:deduccion_quitar', args=[d.pk]), {'mes': f'{MES:%Y-%m}'})
        self.client.post(reverse('finanzas:costo_quitar', args=[c.pk]), {'mes': f'{MES:%Y-%m}'})
        with self.empresa_ctx():
            self.assertFalse(Deduccion.objects.get().activa)
            self.assertEqual(CostoFijo.objects.count(), 0)
        self.assertEqual(self.client.get(url + '?mes=basura').status_code, 200)
        self.assertEqual(self.client.get(url + '?mes=2020-01').status_code, 200)

    def test_datos_invalidos_no_se_guardan(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse('finanzas:costo_agregar'), {'nombre': 'X', 'monto': 'abc'})
        self.client.post(reverse('finanzas:deduccion_agregar'), {'nombre': 'X', 'porcentaje': '150', 'base': 'VENTA'})
        with self.empresa_ctx():
            self.assertEqual((CostoFijo.objects.count(), Deduccion.objects.count()), (0, 0))

    def test_vendedor_no_entra(self):
        self.client.force_login(self.vendedor)
        self.assertIn(self.client.get(reverse('finanzas:equilibrio')).status_code, (302, 403))
        self.assertNotContains(self.client.get(reverse('core:inicio'), follow=True), 'Punto de equilibrio')
