"""
Importa el JSON de `scripts/biolifeventas_exportar.py` en una empresa de Ordo (Fase 7).

Reglas:
- Todo en UNA transacción: o entra todo o nada. Con `simular=True` se hace todo y se revierte al final.
- La empresa debe estar vacía de datos de negocio (productos, clientes, documentos); `vaciar=True` los borra antes
  (no toca usuarios, membresías ni Mi empresa).
- Usuarios: mismo nombre de usuario y la MISMA contraseña cifrada (ambos son Django). Si el usuario ya existe en la
  empresa, se reutiliza sin tocar su contraseña. Roles: ADMIN → Dueño, CONTROL_TOTAL → Administrador, VENDEDOR → Vendedor.
- Kardex completo con sus fechas; los saldos de cada movimiento se calculan hacia atrás desde la existencia actual
  del lote, así el último saldo coincide siempre con el lote.
- Presupuestos con su número original; CONFIRMADO → venta VALIDADA (sin comisiones: BioLifeVentas no las tenía).
  Los ítems partidos por lote en BioLifeVentas se agrupan en una línea con sus reservas por lote.
- Órdenes de compra con lo recibido. Tasas: solo las fechas que no tenga la tasa global, como tasa propia.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.compras.models import ItemOrdenCompra, OrdenCompra
from apps.core.tenancy import usando_empresa
from apps.empresas.models import Membresia, Rol
from apps.inventario.models import Categoria, Lote, Marca, MovimientoInventario, Producto, Subcategoria, Unidad
from apps.proveedores.models import Proveedor
from apps.tasas.models import TasaCambio, TasaEmpresa
from apps.ventas.models import Abono, ItemPresupuesto, Presupuesto, Reserva

UNIDADES = {'VIAL': 'VIAL', 'UN': 'UN', 'CAJA': 'CAJA', 'KIT': 'KIT', 'FRASCO': 'FCO', 'ML': 'ML', 'TEST': 'TEST',
            'TUBO': 'TUBO', 'ROLLO': 'ROLLO'}
ROLES = {'ADMIN': Rol.DUENO, 'CONTROL_TOTAL': Rol.ADMIN, 'VENDEDOR': Rol.VENDEDOR}
ESTADOS = {'BORRADOR': 'BORRADOR', 'EMITIDO': 'EMITIDO', 'APARTADO': 'APARTADO', 'CONFIRMADO': 'VALIDADA',
           'VENCIDO': 'VENCIDO', 'CANCELADO': 'CANCELADO'}
DIAS, MINIMO = 90, 30


class ErrorMigracion(Exception):
    pass


class _Simulacion(Exception):
    pass


def _d(texto):
    return Decimal(texto) if texto not in (None, '') else None


def _fecha(texto):
    return date.fromisoformat(texto[:10]) if texto else None


def _momento(texto):
    if not texto:
        return None
    m = datetime.fromisoformat(texto)
    return m if timezone.is_aware(m) else timezone.make_aware(m)


@contextmanager
def _sin_fechas_automaticas(*campos):
    """Permite guardar fechas históricas en campos auto_now / auto_now_add."""
    previos = [(c, c.auto_now, c.auto_now_add) for c in campos]
    for c in campos:
        c.auto_now = c.auto_now_add = False
    try:
        yield
    finally:
        for c, ahora, al_crear in previos:
            c.auto_now, c.auto_now_add = ahora, al_crear


def _campo(modelo, nombre):
    return modelo._meta.get_field(nombre)


def datos_de_negocio(empresa):
    return {
        'productos': Producto.todos.filter(empresa=empresa).count(),
        'clientes': Cliente.todos.filter(empresa=empresa).count(),
        'presupuestos': Presupuesto.todos.filter(empresa=empresa).count(),
        'proveedores': Proveedor.todos.filter(empresa=empresa).count(),
    }


def vaciar_empresa(empresa):
    """Borra los datos de negocio de la empresa (no usuarios, membresías ni Mi empresa)."""
    from apps.comisiones.models import AjusteComision, Comision, LineaComision, Liquidacion
    from apps.core.models import Secuencia
    from apps.inventario.models import ImportacionProductos
    from apps.ventas.models import Devolucion, ItemDevolucion
    for modelo in (AjusteComision, LineaComision, Comision, Liquidacion, ItemDevolucion, Devolucion, Reserva,
                   ItemPresupuesto, Presupuesto, Cliente, ItemOrdenCompra, OrdenCompra, MovimientoInventario, Lote,
                   Producto, Subcategoria, Categoria, Marca, Proveedor, ImportacionProductos, Secuencia, TasaEmpresa):
        modelo.todos.filter(empresa=empresa).delete()


class Importador:
    def __init__(self, datos, empresa):
        if datos.get('origen') != 'BioLifeVentas' or datos.get('version') != 1:
            raise ErrorMigracion('El archivo no es una exportación de BioLifeVentas (versión 1).')
        self.d, self.e = datos, empresa
        self.m = defaultdict(dict)                 # mapas id BioLifeVentas → objeto Ordo
        self.avisos = []
        self.conteo = Counter()

    # ── Orquestación ─────────────────────────────────────────────────────────
    def ejecutar(self, simular=False, vaciar=False):
        try:
            with transaction.atomic(), usando_empresa(self.e):
                if vaciar:
                    vaciar_empresa(self.e)
                ocupada = {k: n for k, n in datos_de_negocio(self.e).items() if n}
                if ocupada:
                    raise ErrorMigracion(f'La empresa ya tiene datos ({ocupada}). Usa --vaciar para reemplazarlos.')
                self.validar()
                self.usuarios()
                self.catalogo()
                self.proveedores()
                self.productos()
                self.lotes()
                self.clientes()
                self.presupuestos()
                self.kardex()
                self.ordenes()
                self.tasas()
                self.configuracion()
                self.verificacion = self.verificar()
                if simular:
                    raise _Simulacion
        except _Simulacion:
            self.avisos.insert(0, 'SIMULACIÓN: no se guardó nada.')
        return self

    # ── Validación previa ────────────────────────────────────────────────────
    def validar(self):
        errores = []
        for l in self.d['lotes']:
            if l['cantidad_actual'] < 0 or l['cantidad_apartada'] < 0 or l['cantidad_apartada'] > l['cantidad_actual']:
                errores.append(f'Lote {l["id"]} ({l["numero_lote"] or "s/n"}): existencia {l["cantidad_actual"]}, '
                               f'apartado {l["cantidad_apartada"]}')
        codigos = Counter(p['codigo'] for p in self.d['productos'])
        errores += [f'Código de producto repetido: {c}' for c, n in codigos.items() if n > 1]
        if errores:
            raise ErrorMigracion('Datos inconsistentes en BioLifeVentas (corrígelos allá y vuelve a exportar):\n  '
                                 + '\n  '.join(errores))

    # ── Usuarios ─────────────────────────────────────────────────────────────
    def usuarios(self):
        U = get_user_model()
        for u in self.d['usuarios']:
            nombre = u['username'].strip().lower()
            existente = U.objects.filter(empresa_cuenta=self.e, username=nombre).first()
            activo = bool(u['is_active'] and u['activo_sistema'])
            if existente:
                usuario = existente
                self.avisos.append(f'Usuario "{nombre}" ya existía en Ordo: se mantiene su contraseña de Ordo.')
            else:
                usuario = U(username=nombre, empresa_cuenta=self.e, first_name=u['first_name'][:150],
                            last_name=u['last_name'][:150], email=u['email'] or '', telefono=(u['telefono'] or '')[:30],
                            password=u['password'], is_active=activo, date_joined=_momento(u['date_joined']),
                            last_login=_momento(u['last_login']))
                usuario.save()
                self.conteo['usuarios'] += 1
            rol = ROLES.get(u['rol'], Rol.VENDEDOR)
            m, creada = Membresia.objects.get_or_create(usuario=usuario, empresa=self.e,
                                                        defaults={'rol': rol, 'activa': activo})
            if not creada and m.rol != rol:
                self.avisos.append(f'"{nombre}" ya era {m.get_rol_display()} en Ordo: se conserva ese rol.')
            self.m['usuario'][u['id']] = usuario
        limite = self.e.limite_usuarios
        activos = Membresia.objects.filter(empresa=self.e, activa=True, usuario__is_superuser=False).count()
        if limite and activos > limite:
            self.avisos.append(f'La empresa queda con {activos} usuarios activos y su límite es {limite}: '
                               'súbelo en Plataforma o desactiva usuarios.')

    def _usuario(self, bio_id):
        u = self.m['usuario'].get(bio_id)
        if u is None:
            raise ErrorMigracion(f'Usuario {bio_id} de BioLifeVentas no está en el archivo.')
        return u

    # ── Catálogo ─────────────────────────────────────────────────────────────
    def catalogo(self):
        for c in self.d['categorias']:
            self.m['categoria'][c['id']] = Categoria.objects.create(empresa=self.e, nombre=c['nombre'][:100],
                                                                    descripcion=c['descripcion'] or '')
        for s in self.d['subcategorias']:
            self.m['subcategoria'][s['id']] = Subcategoria.objects.create(
                empresa=self.e, categoria=self.m['categoria'][s['categoria_id']], nombre=s['nombre'][:100])
        for mca in self.d['marcas']:
            self.m['marca'][mca['id']] = Marca.objects.create(empresa=self.e, nombre=mca['nombre'][:100],
                                                              activa=mca['activa'])
        self.conteo.update(categorias=len(self.d['categorias']), subcategorias=len(self.d['subcategorias']),
                           marcas=len(self.d['marcas']))

    def proveedores(self):
        direcciones = defaultdict(list)
        for dp in self.d.get('direcciones_proveedor', []):
            if dp['activa']:
                direcciones[dp['proveedor_id']].append(dp)
        for p in self.d['proveedores']:
            dirs = sorted(direcciones[p['id']], key=lambda x: not x['es_principal'])
            texto = lambda x: f'{x["direccion_completa"]}, {x["ciudad"]}{", " + x["estado"] if x["estado"] else ""}'  # noqa: E731
            notas = p['notas'] or ''
            if len(dirs) > 1:
                notas = (notas + '\n\nOtras direcciones (BioLifeVentas):\n' + '\n'.join(
                    f'- {x["etiqueta"]}: {texto(x)}' for x in dirs[1:])).strip()
            self.m['proveedor'][p['id']] = Proveedor.objects.create(
                empresa=self.e, nombre=p['nombre'][:200], rif=p['rif'] or '', contacto=(p['contacto_principal'] or '')[:100],
                telefono=p['telefono'] or '', email=p['email'] or '', direccion=texto(dirs[0]) if dirs else '',
                notas=notas, activo=p['activo'])
        self.conteo['proveedores'] = len(self.d['proveedores'])

    # ── Productos y lotes ────────────────────────────────────────────────────
    def _dias_por_unidad(self):
        """Días por unidad con las ventas reales de los últimos 90 días (respaldo del panel de pedido)."""
        lote_producto = {l['id']: l['producto_id'] for l in self.d['lotes']}
        ahora = timezone.now()
        vendidas, primera = Counter(), {}
        for mv in self.d['movimientos']:
            if mv['tipo'] != 'VENTA':
                continue
            pid, fecha = lote_producto.get(mv['lote_id']), _momento(mv['fecha'])
            primera[pid] = min(primera.get(pid, fecha), fecha)
            if fecha >= ahora - timedelta(days=DIAS):
                vendidas[pid] += abs(mv['cantidad'])
        resultado = {}
        for p in self.d['productos']:
            if vendidas[p['id']]:
                base = min(DIAS, max(MINIMO, (ahora - primera[p['id']]).days))
                resultado[p['id']] = max(Decimal('0.01'), round(Decimal(base) / vendidas[p['id']], 2))
            elif not p['factor_auto_ajuste'] and _d(p['factor_venta_dias']):
                resultado[p['id']] = _d(p['factor_venta_dias'])
            else:
                resultado[p['id']] = Decimal(DIAS)
        return resultado

    def productos(self):
        unidades = {u.abreviatura: u for u in Unidad.objects.all()}
        dias = self._dias_por_unidad()
        for p in self.d['productos']:
            abrev = UNIDADES.get(p['unidad'], p['unidad'][:10].upper())
            if abrev not in unidades:
                unidades[abrev] = Unidad.objects.create(empresa=self.e, nombre=abrev.title(), abreviatura=abrev)
                self.avisos.append(f'Se creó la unidad "{abrev}".')
            self.m['producto'][p['id']] = Producto.objects.create(
                empresa=self.e, codigo=p['codigo'][:50], nombre=p['nombre'][:200], descripcion=p['descripcion'] or '',
                categoria=self.m['categoria'][p['categoria_id']],
                subcategoria=self.m['subcategoria'].get(p['subcategoria_id']),
                marca=self.m['marca'].get(p['marca_id']), unidad=unidades[abrev],
                proveedor_habitual=self.m['proveedor'].get(p['proveedor_habitual_id']),
                maneja_lotes=p['requiere_lote'], maneja_vencimiento=p['requiere_vencimiento'],
                precio_costo_usd=_d(p['precio_costo_usd']), precio_venta_usd=_d(p['precio_venta_usd']),
                stock_minimo=max(0, p['stock_minimo']), factor_venta_dias=dias[p['id']], activo=p['activo'])
        self.conteo['productos'] = len(self.d['productos'])

    def lotes(self):
        for l in self.d['lotes']:
            self.m['lote'][l['id']] = Lote.objects.create(
                empresa=self.e, producto=self.m['producto'][l['producto_id']], numero_lote=l['numero_lote'] or '',
                fecha_vencimiento=_fecha(l['fecha_vencimiento']), cantidad_inicial=max(0, l['cantidad_inicial']),
                cantidad_actual=l['cantidad_actual'], cantidad_apartada=l['cantidad_apartada'],
                costo_unitario_usd=_d(l['precio_costo_lote_usd']), proveedor=self.m['proveedor'].get(l['proveedor_id']),
                fecha_ingreso=_fecha(l['fecha_ingreso']) or timezone.localdate(), notas=l['notas'] or '')
        self.conteo['lotes'] = len(self.d['lotes'])

    # ── Clientes ─────────────────────────────────────────────────────────────
    def clientes(self):
        # Vendedor del cliente = el que más presupuestos le hizo (BioLifeVentas no asignaba cartera)
        por_cliente = defaultdict(Counter)
        for p in self.d['presupuestos']:
            por_cliente[p['cliente_id']][p['vendedor_id']] += 1
        campo = _campo(Cliente, 'creado_en')
        with _sin_fechas_automaticas(campo):
            for c in self.d['clientes']:
                vend = por_cliente[c['id']].most_common(1)
                self.m['cliente'][c['id']] = Cliente.objects.create(
                    empresa=self.e, nombre=c['nombre'][:200], rif=c['rif'] or '', contacto=c['contacto'] or '',
                    telefono=c['telefono'] or '', email=c['email'] or '', direccion=c['direccion'] or '',
                    activo=c['activo'], vendedor=self.m['usuario'].get(vend[0][0]) if vend else None,
                    creado_en=_momento(c['creado_en']) or timezone.now())
        self.conteo['clientes'] = len(self.d['clientes'])

    # ── Presupuestos y ventas ────────────────────────────────────────────────
    def presupuestos(self):
        from apps.ventas.servicios import recalcular_totales
        items_por = defaultdict(list)
        for it in self.d['items_presupuesto']:
            items_por[it['presupuesto_id']].append(it)
        ventas = {v['presupuesto_id']: v for v in self.d['ventas']}
        costo_lote = {l['id']: _d(l['precio_costo_lote_usd']) for l in self.d['lotes']}
        costo_prod = {p['id']: _d(p['precio_costo_usd']) for p in self.d['productos']}
        campos = [_campo(Presupuesto, 'creado_en'), _campo(Presupuesto, 'actualizado_en')]
        with _sin_fechas_automaticas(*campos):
            for b in self.d['presupuestos']:
                estado = ESTADOS.get(b['estado'])
                if estado is None:
                    raise ErrorMigracion(f'Presupuesto {b["numero"]}: estado desconocido {b["estado"]}.')
                v = ventas.get(b['id'])
                emitido = _momento(b['fecha_emision'])
                p = Presupuesto.objects.create(
                    empresa=self.e, numero=b['numero'] or f'BL-{b["id"]}', cliente=self.m['cliente'][b['cliente_id']],
                    vendedor=self._usuario(b['vendedor_id']), estado=estado, fecha=timezone.localtime(emitido).date(),
                    valido_hasta=_fecha(b['fecha_validez']), tasa_bs=_d(b['tasa_cambio_usada']),
                    iva_pct=_d(b['iva_porcentaje']) if b['incluye_iva'] else Decimal('0'),
                    descuento_pct=_d(b['descuento_global_porcentaje']),
                    apartado_hasta=_momento(b['fecha_vencimiento_apartado']) if estado == 'APARTADO' else None,
                    confirmado_en=_momento(v['fecha_venta']) if v else None,
                    validado_en=_momento(v['fecha_venta']) if v else None,
                    validado_por=self._usuario(v['confirmada_por_id']) if v else None,
                    pagado=bool(v and v['pagado']), fecha_pago=_fecha(v['fecha_pago']) if v else None,
                    metodo_pago=(v['metodo_pago'] or '') if v and v['pagado'] else '',
                    facturado=bool(v and v['facturado']), numero_factura=(v['numero_factura'] or '') if v else '',
                    numero_control=(v['numero_control'] or '') if v else '',
                    fecha_facturacion=_fecha(v['fecha_facturacion']) if v else None,
                    entregado=b['entregado'], fecha_entrega=_fecha(b['fecha_entrega']),
                    notas='\n'.join(x for x in [b['notas'], v and v['notas']] if x),
                    condiciones=b['condiciones'] or '',
                    creado_en=_momento(b['creado_en']) or emitido, actualizado_en=_momento(b['actualizado_en']) or emitido)
                if estado == 'VALIDADA' and not v:
                    self.avisos.append(f'{p.numero}: estaba CONFIRMADO sin registro de venta; se usó la fecha de emisión.')
                    p.validado_en = p.confirmado_en = emitido
                    p.save(update_fields=['validado_en', 'confirmado_en'])
                self.m['presupuesto'][b['id']] = p
                self._items(p, items_por[b['id']], estado, costo_lote, costo_prod)
                recalcular_totales(p)
                if p.pagado:                     # el pago de BioLifeVentas pasa a ser un abono por el total
                    Abono.objects.create(empresa=self.e, presupuesto=p, fecha=p.fecha_pago or p.fecha,
                                         metodo=p.metodo_pago or 'TRANSFERENCIA', monto=p.total_usd,
                                         monto_usd=p.total_usd)
                    Presupuesto.todos.filter(pk=p.pk).update(abonado_usd=p.total_usd)
                Presupuesto.todos.filter(pk=p.pk).update(actualizado_en=_momento(b['actualizado_en']) or emitido)
        self.conteo['presupuestos'] = len(self.d['presupuestos'])
        self.conteo['ventas'] = sum(1 for b in self.d['presupuestos'] if b['estado'] == 'CONFIRMADO')

    def _items(self, p, items, estado, costo_lote, costo_prod):
        """Agrupa los ítems partidos por lote en una línea por producto y precio, con sus reservas."""
        grupos = {}
        for it in items:
            grupos.setdefault((it['producto_id'], it['precio_unitario_usd']), []).append(it)
        for orden, ((prod_id, precio), partes) in enumerate(grupos.items()):
            cantidad = sum(x['cantidad'] for x in partes)
            con_lote = [x for x in partes if x['lote_id']]
            if con_lote:
                costo = sum(costo_lote[x['lote_id']] * x['cantidad'] for x in con_lote) / sum(x['cantidad'] for x in con_lote)
            else:
                costo = costo_prod[prod_id]
            item = ItemPresupuesto.objects.create(
                empresa=self.e, presupuesto=p, producto=self.m['producto'][prod_id], cantidad=cantidad,
                precio_base_usd=_d(precio), precio_usd=_d(precio), costo_usd=Decimal(costo).quantize(Decimal('0.01')),
                orden=orden)
            if estado in ('APARTADO', 'VALIDADA'):
                for x in con_lote:
                    Reserva.objects.create(empresa=self.e, item=item, lote=self.m['lote'][x['lote_id']],
                                           cantidad=x['cantidad'])

    # ── Kardex ───────────────────────────────────────────────────────────────
    def kardex(self):
        """Movimientos con su fecha original; saldos calculados hacia atrás desde la existencia actual del lote."""
        por_lote = defaultdict(list)
        for mv in self.d['movimientos']:
            por_lote[mv['lote_id']].append(mv)
        lotes = {l['id']: l for l in self.d['lotes']}
        nuevos = []
        for lote_id, movs in por_lote.items():
            actual, apartada = lotes[lote_id]['cantidad_actual'], lotes[lote_id]['cantidad_apartada']
            del_lote = []
            for mv in sorted(movs, key=lambda x: (x['fecha'], x['id']), reverse=True):
                del_lote.append(self._movimiento(mv, actual, apartada))
                c = mv['cantidad']
                if mv['tipo'] in ('INGRESO', 'AJUSTE_POS', 'AJUSTE_NEG', 'BAJA_VENC'):
                    actual -= c
                elif mv['tipo'] == 'VENTA':
                    actual -= c
                    apartada = max(0, apartada - c)
                elif mv['tipo'] in ('APARTADO', 'LIBERACION'):
                    apartada += c
            nuevos.extend(reversed(del_lote))            # se guardan en orden cronológico
            if actual != 0 or apartada != 0:
                self.avisos.append(f'Lote {lotes[lote_id]["numero_lote"] or lote_id}: el kardex no parte de cero '
                                   f'(existencia previa {actual}, apartado {apartada}); los saldos se calcularon '
                                   'desde la existencia actual.')
        with _sin_fechas_automaticas(_campo(MovimientoInventario, 'fecha')):
            MovimientoInventario.objects.bulk_create(nuevos, batch_size=500)
        self.conteo['movimientos'] = len(nuevos)

    def _movimiento(self, mv, saldo_actual, saldo_apartado):
        ref_tipo, ref_id = mv['referencia_tipo'] or '', None
        if ref_tipo == 'Presupuesto' and mv['referencia_id'] in self.m['presupuesto']:
            ref_id = self.m['presupuesto'][mv['referencia_id']].pk
            ref_tipo = 'Venta' if mv['tipo'] == 'VENTA' else 'Presupuesto'
        elif mv['tipo'] == 'INGRESO':
            ref_tipo, ref_id = 'Ingreso', self.m['lote'][mv['lote_id']].pk
        return MovimientoInventario(
            empresa=self.e, lote=self.m['lote'][mv['lote_id']], tipo=mv['tipo'], cantidad=mv['cantidad'],
            saldo_actual=saldo_actual, saldo_apartado=saldo_apartado, usuario=self._usuario(mv['usuario_id']),
            referencia_tipo=ref_tipo[:40], referencia_id=ref_id, motivo=(mv['motivo'] or '')[:250],
            fecha=_momento(mv['fecha']))

    # ── Compras, tasas y configuración ───────────────────────────────────────
    def ordenes(self):
        items_por = defaultdict(list)
        for it in self.d.get('items_orden_compra', []):
            items_por[it['orden_id']].append(it)
        campos = [_campo(OrdenCompra, 'fecha'), _campo(OrdenCompra, 'creado_en')]
        with _sin_fechas_automaticas(*campos):
            for o in self.d.get('ordenes_compra', []):
                items = items_por[o['id']]
                pedido = sum(i['cantidad_pedida'] for i in items)
                recibido = sum(i['cantidad_recibida'] for i in items)
                if o['estado'] == 'BORRADOR':
                    estado = OrdenCompra.Estado.BORRADOR
                elif recibido == 0:
                    estado = OrdenCompra.Estado.ENVIADA
                elif recibido < pedido:
                    estado = OrdenCompra.Estado.PARCIAL
                else:
                    estado = OrdenCompra.Estado.RECIBIDA
                creada = _momento(o['fecha_creacion']) or timezone.now()
                orden = OrdenCompra.objects.create(
                    empresa=self.e, numero=o['numero'][:30], proveedor=self.m['proveedor'][o['proveedor_id']],
                    estado=estado, fecha=timezone.localtime(creada).date(), fecha_envio=_momento(o['fecha_cierre']),
                    notas=o['notas'] or '', creado_por=self._usuario(o['creado_por_id']), creado_en=creada)
                ItemOrdenCompra.objects.bulk_create([ItemOrdenCompra(
                    empresa=self.e, orden=orden, producto=self.m['producto'][i['producto_id']],
                    cantidad_pedida=i['cantidad_pedida'], cantidad_recibida=min(i['cantidad_recibida'], i['cantidad_pedida']),
                    costo_unitario_usd=_d(i['precio_costo_usd'])) for i in items])
        self.conteo['ordenes_compra'] = len(self.d.get('ordenes_compra', []))

    def tasas(self):
        globales = set(TasaCambio.objects.values_list('fecha', flat=True))
        nuevas = [TasaEmpresa(empresa=self.e, fecha=_fecha(t['fecha']), bs_por_usd=_d(t['tasa_bs_por_usd']))
                  for t in self.d.get('tasas', [])
                  if t['scraping_exitoso'] and _fecha(t['fecha']) not in globales]
        TasaEmpresa.objects.bulk_create(nuevas)
        from django.core.cache import cache

        from apps.tasas.servicios import _clave_empresa
        cache.delete(_clave_empresa(self.e.pk))
        self.conteo['tasas'] = len(nuevas)

    def configuracion(self):
        perfil = self.e.perfil
        if perfil.formato_numero_presupuesto != 'CORRIDO':
            perfil.formato_numero_presupuesto = 'CORRIDO'
            perfil.save(update_fields=['formato_numero_presupuesto'])
        ultimo = max((b['numero'] for b in self.d['presupuestos'] if b['numero']), default='')
        self.avisos.append(f'Los presupuestos nuevos siguen el correlativo de BioLifeVentas (último migrado: {ultimo or "—"}).')
        if not perfil.vendedores_ven_todos_los_clientes:
            perfil.vendedores_ven_todos_los_clientes = True
            perfil.save(update_fields=['vendedores_ven_todos_los_clientes'])
            self.avisos.append('Mi empresa → Comercial: los vendedores ven TODOS los clientes (como en BioLifeVentas).')
        cfg = self.d.get('configuracion', {})
        if cfg and _d(cfg.get('iva_porcentaje')) != perfil.iva_porcentaje:
            self.avisos.append(f'IVA en BioLifeVentas {cfg["iva_porcentaje"]} % y en Ordo {perfil.iva_porcentaje} %: revisa Mi empresa.')
        if cfg and cfg.get('dias_vencimiento_apartado') != perfil.dias_apartado:
            self.avisos.append(f'Días de apartado: BioLifeVentas {cfg["dias_vencimiento_apartado"]}, Ordo {perfil.dias_apartado}.')

    # ── Verificación contra el resumen del archivo ───────────────────────────
    def verificar(self):
        from django.db.models import Sum
        r = self.d.get('resumen', {})
        lotes = Lote.todos.filter(empresa=self.e)
        filas = [
            ('Productos', r.get('productos'), Producto.todos.filter(empresa=self.e).count()),
            ('Lotes', r.get('lotes'), lotes.count()),
            ('Movimientos de kardex', r.get('movimientos'), MovimientoInventario.todos.filter(empresa=self.e).count()),
            ('Unidades en existencia', r.get('unidades_en_existencia'), lotes.aggregate(t=Sum('cantidad_actual'))['t'] or 0),
            ('Unidades apartadas', r.get('unidades_apartadas'), lotes.aggregate(t=Sum('cantidad_apartada'))['t'] or 0),
            ('Clientes', r.get('clientes'), Cliente.todos.filter(empresa=self.e).count()),
            ('Presupuestos', r.get('presupuestos'), Presupuesto.todos.filter(empresa=self.e).count()),
            ('Ventas', r.get('ventas'), Presupuesto.todos.filter(empresa=self.e, estado='VALIDADA').count()),
            ('Total vendido USD', _d(r.get('total_ventas_usd')),
             Presupuesto.todos.filter(empresa=self.e, estado='VALIDADA').aggregate(t=Sum('total_usd'))['t'] or Decimal('0')),
            ('Órdenes de compra', r.get('ordenes_compra'), OrdenCompra.todos.filter(empresa=self.e).count()),
        ]
        # Reservas = apartado de los lotes (lo apartado por documentos apartados o validados con stock aún reservado)
        reservado = Reserva.todos.filter(empresa=self.e, item__presupuesto__estado='APARTADO').aggregate(t=Sum('cantidad'))['t'] or 0
        filas.append(('Apartado según presupuestos', r.get('unidades_apartadas'), reservado))
        return [(n, a, b, a is None or a == b) for n, a, b in filas]

    @property
    def ok(self):
        return all(x[3] for x in getattr(self, 'verificacion', []))
