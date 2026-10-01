from datetime import timedelta, date
from decimal import Decimal as D
from django.utils import timezone
from usuarios.models import Usuario
from configuracion.models import ConfiguracionSistema, TasaCambio
from inventario.models import *
from proveedores.models import *
from presupuestos.models import *
from presupuestos.utils import asignar_lotes_fefo, confirmar_venta, liberar_apartado
from ventas.models import Venta
from compras.models import *
now = timezone.now(); hoy = now.date()
admin = Usuario.objects.create_superuser('Admin', 'a@b.com', 'clave-admin-1', rol='ADMIN', first_name='Darwin', last_name='Arroyo')
ana = Usuario.objects.create_user('ana', '', 'clave-ana-1', rol='CONTROL_TOTAL', first_name='Ana', last_name='Pérez')
luis = Usuario.objects.create_user('luis', 'luis@x.com', 'clave-luis-1', rol='VENDEDOR', first_name='Luis', telefono='0414')
pedro = Usuario.objects.create_user('pedro', '', 'clave-pedro-1', rol='VENDEDOR', activo_sistema=False)
cfg = ConfiguracionSistema.get(); cfg.nombre_empresa='Biolife de Venezuela, CA'; cfg.rif='J-123'; cfg.save()
for i, t in enumerate(['35.10', '36.20', '36.50']):
    TasaCambio.objects.create(fecha=hoy - timedelta(days=3 - i), tasa_bs_por_usd=D(t), fuente='BCV_AUTO')
TasaCambio.objects.create(fecha=hoy - timedelta(days=10), tasa_bs_por_usd=D('30'), fuente='BCV_AUTO', scraping_exitoso=False)
reac = CategoriaProducto.objects.create(nombre='Reactivos'); equ = CategoriaProducto.objects.create(nombre='Equipos')
qui = SubCategoriaProducto.objects.create(categoria=reac, nombre='Química')
wl = Marca.objects.create(nombre='Wiener Lab'); Marca.objects.create(nombre='Mindray', activa=False)
dist = Proveedor.objects.create(nombre='Distribuidora Lara', rif='J-9', contacto_principal='Carlos', telefono='0251')
DireccionProveedor.objects.create(proveedor=dist, etiqueta='Almacén', direccion_completa='Zona Ind. II', ciudad='Barquisimeto', estado='Lara', es_principal=True)
DireccionProveedor.objects.create(proveedor=dist, etiqueta='Oficina', direccion_completa='Av. 20', ciudad='Caracas')
otro = Proveedor.objects.create(nombre='Importadora X', activo=False)
glu = Producto.objects.create(codigo='GLU-01', nombre='Glucosa 2x50 ml', categoria=reac, subcategoria=qui, marca=wl, proveedor_habitual=dist, unidad='VIAL', precio_costo_usd=D('10'), precio_venta_usd=D('20'), stock_minimo=5, factor_venta_dias=D('120'))
col = Producto.objects.create(codigo='COL-01', nombre='Colesterol', categoria=reac, proveedor_habitual=dist, unidad='FRASCO', precio_costo_usd=D('8'), precio_venta_usd=D('15'), factor_auto_ajuste=False, factor_venta_dias=D('7'))
cen = Producto.objects.create(codigo='CEN-01', nombre='Centrífuga', categoria=equ, proveedor_habitual=otro, unidad='UN', requiere_lote=False, requiere_vencimiento=False, precio_costo_usd=D('100'), precio_venta_usd=D('180'))
def ingreso(p, n, cant, venc, costo, hace):
    l = Lote.objects.create(producto=p, numero_lote=n, fecha_vencimiento=venc, cantidad_inicial=cant, cantidad_actual=cant, precio_costo_lote_usd=costo, proveedor=p.proveedor_habitual)
    m = MovimientoInventario.objects.create(lote=l, tipo='INGRESO', cantidad=cant, usuario=ana, referencia_tipo='Ingreso de Compra', referencia_id=l.pk)
    MovimientoInventario.objects.filter(pk=m.pk).update(fecha=now - timedelta(days=hace)); Lote.objects.filter(pk=l.pk).update(fecha_ingreso=hoy - timedelta(days=hace))
    return l
l1 = ingreso(glu, 'G-A', 20, hoy + timedelta(days=40), D('9.50'), 200)
l2 = ingreso(glu, 'G-B', 30, hoy + timedelta(days=300), D('10'), 100)
l3 = ingreso(col, 'C-A', 10, hoy - timedelta(days=5), D('8'), 150)     # vencido
l4 = ingreso(cen, '', 3, None, D('100'), 150)
cli1 = Cliente.objects.create(nombre='Clínica Sol', rif='J-1', telefono='0251-1')
cli2 = Cliente.objects.create(nombre='Lab Luna', rif='J-2')
cli3 = Cliente.objects.create(nombre='Hospital Viejo', activo=False)
def presu(cli, vend, items, hace, desc='0', iva=True, tasa='36.20'):
    p = Presupuesto(cliente=cli, vendedor=vend, fecha_validez=hoy + timedelta(days=7), tasa_cambio_usada=D(tasa), descuento_global_porcentaje=D(desc), incluye_iva=iva, condiciones='Pago de contado')
    p.generar_numero(); p.save()
    for prod, cant, precio in items:
        ItemPresupuesto.objects.create(presupuesto=p, producto=prod, cantidad=cant, precio_unitario_usd=D(precio))
    Presupuesto.objects.filter(pk=p.pk).update(fecha_emision=now - timedelta(days=hace), creado_en=now - timedelta(days=hace))
    p.refresh_from_db(); return p
def mover_fechas(p, hace):
    MovimientoInventario.objects.filter(referencia_id=p.pk, referencia_tipo='Presupuesto').update(fecha=now - timedelta(days=hace))
# 1) venta antigua confirmada (30 GLU → toma 20 de G-A y 10 de G-B: ítem partido en dos)
p1 = presu(cli1, luis, [(glu, 30, '20'), (cen, 1, '180')], 80)
assert asignar_lotes_fefo(p1)[0]; confirmar_venta(p1, ana); mover_fechas(p1, 80)
v = Venta.objects.get(presupuesto=p1); v.pagado=True; v.fecha_pago=hoy - timedelta(days=75); v.metodo_pago='ZELLE'; v.facturado=True; v.numero_factura='000123'; v.numero_control='00-0456'; v.fecha_facturacion=hoy-timedelta(days=79); v.save()
Venta.objects.filter(pk=v.pk).update(fecha_venta=now - timedelta(days=80))
# 2) venta reciente con descuento y sin IVA, sin pagar
p2 = presu(cli2, ana, [(glu, 5, '19.99')], 10, desc='7', iva=False)
assert asignar_lotes_fefo(p2)[0]; confirmar_venta(p2, ana); mover_fechas(p2, 10)
Venta.objects.filter(presupuesto=p2).update(fecha_venta=now - timedelta(days=10))
# 3) apartado vigente
p3 = presu(cli1, luis, [(glu, 4, '20')], 2)
assert asignar_lotes_fefo(p3)[0]; mover_fechas(p3, 2)
# 4) cancelado tras apartar
p4 = presu(cli2, pedro, [(glu, 2, '20')], 30)
assert asignar_lotes_fefo(p4)[0]; liberar_apartado(p4, 'Cancelado'); p4.estado='CANCELADO'; p4.save(); mover_fechas(p4, 30)
# 5) borrador y 6) emitido
p5 = presu(cli1, luis, [(col, 1, '15')], 1); 
p6 = presu(cli2, luis, [(cen, 1, '175')], 3); p6.estado='EMITIDO'; p6.save()
# ajuste y baja por vencimiento
m = MovimientoInventario.objects.create(lote=l3, tipo='BAJA_VENC', cantidad=-2, usuario=ana, referencia_tipo='Ajuste Manual', motivo='Vencido')
Lote.objects.filter(pk=l3.pk).update(cantidad_actual=8)
# órdenes de compra
oc1 = OrdenCompra.objects.create(numero='OC-2026-001', proveedor=dist, creado_por=ana)
ItemOrdenCompra.objects.create(orden=oc1, producto=glu, cantidad_pedida=50, precio_costo_usd=D('10'))
oc2 = OrdenCompra.objects.create(numero='OC-2026-002', proveedor=dist, creado_por=ana, estado='CERRADA', fecha_cierre=now - timedelta(days=20))
ItemOrdenCompra.objects.create(orden=oc2, producto=col, cantidad_pedida=20, cantidad_recibida=10, precio_costo_usd=D('8'))
print('semilla ok', Presupuesto.objects.count(), MovimientoInventario.objects.count())
