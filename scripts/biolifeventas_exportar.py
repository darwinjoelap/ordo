"""
Exporta TODO BioLifeVentas a un JSON para importarlo en Ordo (Fase 7). SOLO LEE: no modifica nada.

Uso (PowerShell, desde la carpeta de BioLifeVentas y con SU venv):
    cd C:\\proyectos\\biolifeventas
    .\\.venv\\Scripts\\Activate.ps1
    # Para leer PRODUCCIÓN apunta a su base (URL pública de Postgres de BioLifeVentas; no la pegues en chats):
    $env:DATABASE_URL = "postgresql://..."
    python manage.py shell -c "exec(open(r'C:\\proyectos\\ordo\\scripts\\biolifeventas_exportar.py', encoding='utf-8').read())"

Genera: biolifeventas_export.json en la carpeta actual (ORDO_SALIDA para cambiar el nombre).
Luego en Ordo:  python manage.py importar_biolifeventas biolifeventas_export.json --empresa biolife --simular
"""
import json
import os
from datetime import date, datetime
from decimal import Decimal

from compras.models import ItemOrdenCompra, OrdenCompra
from configuracion.models import ConfiguracionSistema, TasaCambio
from inventario.models import CategoriaProducto, Lote, Marca, MovimientoInventario, Producto, SubCategoriaProducto
from presupuestos.models import Cliente, ItemPresupuesto, Presupuesto
from proveedores.models import DireccionProveedor, Proveedor
from usuarios.models import Usuario
from ventas.models import Venta

VERSION = 1


def v(valor):
    """Valor serializable: Decimal y fechas como texto."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


def filas(qs, campos):
    return [{c: v(getattr(o, c)) for c in campos} for o in qs]


datos = {'version': VERSION, 'origen': 'BioLifeVentas', 'exportado_en': datetime.now().isoformat()}

datos['usuarios'] = filas(Usuario.objects.order_by('pk'), [
    'id', 'username', 'first_name', 'last_name', 'email', 'telefono', 'rol', 'activo_sistema', 'is_active',
    'is_superuser', 'password', 'date_joined', 'last_login'])

cfg = ConfiguracionSistema.get()
datos['configuracion'] = {c: v(getattr(cfg, c)) for c in [
    'nombre_empresa', 'rif', 'iva_porcentaje', 'dias_vencimiento_apartado', 'condiciones_presupuesto']}

datos['categorias'] = filas(CategoriaProducto.objects.order_by('pk'), ['id', 'nombre', 'descripcion'])
datos['subcategorias'] = filas(SubCategoriaProducto.objects.order_by('pk'), ['id', 'categoria_id', 'nombre'])
datos['marcas'] = filas(Marca.objects.order_by('pk'), ['id', 'nombre', 'activa'])

datos['proveedores'] = filas(Proveedor.objects.order_by('pk'), [
    'id', 'nombre', 'rif', 'contacto_principal', 'telefono', 'email', 'notas', 'activo'])
datos['direcciones_proveedor'] = filas(DireccionProveedor.objects.order_by('pk'), [
    'id', 'proveedor_id', 'etiqueta', 'direccion_completa', 'ciudad', 'estado', 'pais', 'es_principal', 'activa'])

datos['productos'] = filas(Producto.objects.order_by('pk'), [
    'id', 'codigo', 'nombre', 'descripcion', 'categoria_id', 'subcategoria_id', 'marca_id', 'proveedor_habitual_id',
    'unidad', 'requiere_lote', 'requiere_vencimiento', 'precio_costo_usd', 'precio_venta_usd', 'stock_minimo',
    'factor_venta_dias', 'factor_auto_ajuste', 'activo'])
datos['lotes'] = filas(Lote.objects.order_by('pk'), [
    'id', 'producto_id', 'numero_lote', 'fecha_vencimiento', 'cantidad_inicial', 'cantidad_actual',
    'cantidad_apartada', 'precio_costo_lote_usd', 'proveedor_id', 'fecha_ingreso', 'notas'])
datos['movimientos'] = filas(MovimientoInventario.objects.order_by('fecha', 'pk'), [
    'id', 'lote_id', 'tipo', 'cantidad', 'fecha', 'usuario_id', 'referencia_tipo', 'referencia_id', 'motivo'])

datos['clientes'] = filas(Cliente.objects.order_by('pk'), [
    'id', 'nombre', 'rif', 'direccion', 'telefono', 'email', 'contacto', 'activo', 'creado_en'])
datos['presupuestos'] = filas(Presupuesto.objects.order_by('pk'), [
    'id', 'numero', 'cliente_id', 'vendedor_id', 'fecha_emision', 'fecha_validez', 'incluye_iva', 'iva_porcentaje',
    'descuento_global_porcentaje', 'tasa_cambio_usada', 'estado', 'dias_validez_apartado', 'fecha_apartado',
    'fecha_vencimiento_apartado', 'notas', 'condiciones', 'entregado', 'fecha_entrega', 'creado_en',
    'actualizado_en'])
datos['items_presupuesto'] = filas(ItemPresupuesto.objects.order_by('pk'), [
    'id', 'presupuesto_id', 'producto_id', 'lote_id', 'cantidad', 'precio_unitario_usd'])
datos['ventas'] = filas(Venta.objects.order_by('pk'), [
    'id', 'presupuesto_id', 'fecha_venta', 'confirmada_por_id', 'metodo_pago', 'notas', 'pagado', 'fecha_pago',
    'facturado', 'numero_factura', 'numero_control', 'fecha_facturacion'])

datos['ordenes_compra'] = filas(OrdenCompra.objects.order_by('pk'), [
    'id', 'numero', 'proveedor_id', 'estado', 'creado_por_id', 'fecha_creacion', 'fecha_cierre', 'notas'])
datos['items_orden_compra'] = filas(ItemOrdenCompra.objects.order_by('pk'), [
    'id', 'orden_id', 'producto_id', 'cantidad_pedida', 'cantidad_recibida', 'precio_costo_usd'])

datos['tasas'] = filas(TasaCambio.objects.order_by('fecha'), ['fecha', 'tasa_bs_por_usd', 'fuente', 'scraping_exitoso'])

# Resumen para comparar después de importar
datos['resumen'] = {
    'productos': len(datos['productos']), 'lotes': len(datos['lotes']), 'movimientos': len(datos['movimientos']),
    'unidades_en_existencia': sum(l['cantidad_actual'] for l in datos['lotes']),
    'unidades_apartadas': sum(l['cantidad_apartada'] for l in datos['lotes']),
    'clientes': len(datos['clientes']), 'presupuestos': len(datos['presupuestos']), 'ventas': len(datos['ventas']),
    'ordenes_compra': len(datos['ordenes_compra']), 'usuarios': len(datos['usuarios']),
    'total_ventas_usd': str(sum((p.total_usd for p in Presupuesto.objects.filter(estado='CONFIRMADO')
                                 .prefetch_related('items')), Decimal('0'))),
}

salida = os.environ.get('ORDO_SALIDA', 'biolifeventas_export.json')
with open(salida, 'w', encoding='utf-8') as f:
    json.dump(datos, f, ensure_ascii=False, indent=1)
print(f'Listo: {os.path.abspath(salida)}')
for k, n in datos['resumen'].items():
    print(f'  {k}: {n}')
print('El archivo contiene las contraseñas CIFRADAS de los usuarios: guárdalo en un lugar privado y bórralo al terminar.')
