"""
Servicios vendidos (Mi empresa → Servicios → «Maneja servicios»).

Un servicio es un Producto de tipo SERVICIO: no tiene lotes ni stock. Cada línea de servicio de una venta es UNA
ejecución con su fecha programada, responsable y constancia de realizado. El estado del servicio se deriva
(`ItemPresupuesto.estado_servicio`), nunca se guarda aparte.

- Programar: en cualquier presupuesto vivo (la fecha sale en el PDF como «Fecha prevista»).
- Marcar realizado: solo en ventas confirmadas (Por cobrar · Por validar · Validada).
- El cobro NO cambia: usa el saldo y los abonos de la venta. «Por cobrar» = realizado y la venta tiene saldo.
- Venta solo de servicios: queda «entregada» cuando todos sus servicios están realizados.
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import ItemPresupuesto, Presupuesto
from .servicios import ErrorVenta, _bloquear

E = Presupuesto.Estado
CONFIRMADAS = Presupuesto.CONFIRMADAS
PESTANAS = [
    ('hoy', 'Hoy', 'calendar-day'), ('atrasados', 'Atrasados', 'exclamation-triangle'),
    ('proximos', 'Próximos', 'calendar-week'), ('por_programar', 'Por programar', 'calendar-plus'),
    ('realizados', 'Realizados', 'check2-circle'), ('por_cobrar', 'Por cobrar', 'cash-coin'),
]
ETIQUETAS = {
    'PENDIENTE': ('Por programar', 'secondary'), 'PROGRAMADO': ('Programado', 'primary'),
    'ATRASADO': ('Atrasado', 'danger'), 'REALIZADO': ('Realizado', 'success'), 'ANULADO': ('Anulado', 'dark'),
}
COBRO_PENDIENTE = Q(presupuesto__estado=E.POR_PAGAR) | Q(presupuesto__estado=E.VALIDADA, presupuesto__pagado=False)


def activo(empresa):
    return bool(empresa and empresa.perfil.maneja_servicios)


def de_ventas(presupuestos):
    """Líneas de servicio de esos presupuestos (ya filtrados por empresa y visibilidad)."""
    return (ItemPresupuesto.objects.filter(presupuesto__in=presupuestos, producto__tipo='SERVICIO')
            .select_related('presupuesto__cliente', 'presupuesto__vendedor', 'producto__unidad', 'responsable'))


def pestana(qs, clave, hoy=None):
    """Filtra las líneas de servicio por pestaña de la agenda."""
    hoy = hoy or timezone.localdate()
    vivas = qs.filter(presupuesto__estado__in=CONFIRMADAS, realizado_en__isnull=True)
    if clave == 'hoy':
        return vivas.filter(fecha_servicio=hoy).order_by('hora_servicio', 'pk')
    if clave == 'atrasados':
        return vivas.filter(fecha_servicio__lt=hoy).order_by('fecha_servicio', 'hora_servicio', 'pk')
    if clave == 'proximos':
        return vivas.filter(fecha_servicio__gt=hoy).order_by('fecha_servicio', 'hora_servicio', 'pk')
    if clave == 'por_programar':
        return vivas.filter(fecha_servicio__isnull=True).order_by('presupuesto__confirmado_en', 'pk')
    realizados = qs.filter(realizado_en__isnull=False)
    if clave == 'por_cobrar':
        return realizados.filter(COBRO_PENDIENTE).order_by('realizado_en', 'pk')
    return realizados.order_by('-realizado_en', '-pk')          # realizados


def resumen(qs, hoy=None):
    """Conteos para el recordatorio: hoy, mañana, atrasados, por programar y realizados por cobrar."""
    hoy = hoy or timezone.localdate()
    vivas = Q(presupuesto__estado__in=CONFIRMADAS, realizado_en__isnull=True)
    return qs.aggregate(
        hoy=Count('pk', filter=vivas & Q(fecha_servicio=hoy)),
        manana=Count('pk', filter=vivas & Q(fecha_servicio=hoy + timedelta(days=1))),
        atrasados=Count('pk', filter=vivas & Q(fecha_servicio__lt=hoy)),
        por_programar=Count('pk', filter=vivas & Q(fecha_servicio__isnull=True)),
        por_cobrar=Count('pk', filter=Q(realizado_en__isnull=False) & COBRO_PENDIENTE),
    )


# ── Acciones ──────────────────────────────────────────────────────────────────

def _item_bloqueado(item):
    """Bloquea la venta (como todo cambio de estado) y relee la línea."""
    p = _bloquear(item.presupuesto)
    item = ItemPresupuesto.objects.select_related('producto').get(pk=item.pk)
    item.presupuesto = p
    if not item.producto.es_servicio:
        raise ErrorVenta('Esta línea no es un servicio.')
    return item


def _texto(valor, largo):
    return ' '.join((valor or '').split())[:largo]


@transaction.atomic
def programar(item, fecha, hora=None, responsable=None, responsable_nombre=''):
    item = _item_bloqueado(item)
    if item.presupuesto.estado in Presupuesto.CAIDAS:
        raise ErrorVenta('La venta está anulada: ya no se programa.')
    if item.realizado_en:
        raise ErrorVenta('El servicio ya está realizado. Deshaz «realizado» para cambiar la fecha.')
    item.fecha_servicio, item.hora_servicio = fecha, (hora if fecha else None)
    item.responsable = responsable
    item.responsable_nombre = '' if responsable else _texto(responsable_nombre, 120)
    item.save(update_fields=['fecha_servicio', 'hora_servicio', 'responsable', 'responsable_nombre'])
    return item


@transaction.atomic
def realizar(item, usuario, cuando=None, nota='', recibe_nombre='', recibe_cedula='', firma=''):
    """Constancia de ejecución. `cuando`: datetime (por defecto ahora). No puede ser futuro."""
    from .entregas import _firma
    item = _item_bloqueado(item)
    p = item.presupuesto
    if p.estado not in CONFIRMADAS:
        raise ErrorVenta('Solo se marca realizado un servicio de una venta confirmada.')
    if item.realizado_en:
        raise ErrorVenta('Este servicio ya está marcado como realizado.')
    ahora = timezone.now()
    cuando = cuando or ahora
    if cuando > ahora + timedelta(minutes=5):
        raise ErrorVenta('La fecha de realizado no puede ser futura.')
    item.realizado_en, item.realizado_por = cuando, usuario
    item.nota_servicio = _texto(nota, 500)
    item.recibe_nombre, item.recibe_cedula = _texto(recibe_nombre, 120), _texto(recibe_cedula, 20).upper()
    item.recibe_firma = _firma(firma)
    if not item.fecha_servicio:                  # se hizo sin programar: queda en la fecha real
        item.fecha_servicio = timezone.localtime(cuando).date()
    item.save(update_fields=['realizado_en', 'realizado_por', 'nota_servicio', 'recibe_nombre', 'recibe_cedula',
                             'recibe_firma', 'fecha_servicio'])
    _actualizar_entrega(p)
    return item


@transaction.atomic
def deshacer(item):
    """Corrige un «realizado» marcado por error: vuelve a programado (conserva la fecha)."""
    item = _item_bloqueado(item)
    if not item.realizado_en:
        raise ErrorVenta('Este servicio no está marcado como realizado.')
    item.realizado_en = item.realizado_por = None
    item.nota_servicio = item.recibe_nombre = item.recibe_cedula = item.recibe_firma = ''
    item.save(update_fields=['realizado_en', 'realizado_por', 'nota_servicio', 'recibe_nombre', 'recibe_cedula',
                             'recibe_firma'])
    _actualizar_entrega(item.presupuesto)
    return item


def _actualizar_entrega(p):
    """
    Venta SOLO de servicios: queda «entregada» cuando todos están realizados (fecha = el último).
    Si tiene mercancía, la entrega la sigue llevando la mercancía (despacho o el vendedor).
    """
    lineas = list(ItemPresupuesto.objects.filter(presupuesto=p).select_related('producto'))
    if not lineas or any(not i.producto.es_servicio for i in lineas):
        return p
    todos = all(i.realizado_en for i in lineas)
    fecha = timezone.localtime(max(i.realizado_en for i in lineas)).date() if todos else None
    if (p.entregado, p.fecha_entrega) != (todos, fecha):
        p.entregado, p.fecha_entrega = todos, fecha
        p.save(update_fields=['entregado', 'fecha_entrega'])
    return p


# ── WhatsApp ──────────────────────────────────────────────────────────────────

def telefono_whatsapp(telefono):
    """'0414-123.45.67' → '584141234567'. Números con código de país se respetan. '' si no parece un móvil."""
    digitos = re.sub(r'\D', '', telefono or '')
    if digitos.startswith('00'):
        digitos = digitos[2:]
    if digitos.startswith('0') and len(digitos) == 11:          # formato venezolano 04xx
        digitos = '58' + digitos[1:]
    elif len(digitos) == 10 and digitos.startswith('4'):       # 414xxxxxxx
        digitos = '58' + digitos
    return digitos if 10 <= len(digitos) <= 15 else ''


def mensaje_whatsapp(item, perfil):
    plantilla = perfil.mensaje_servicio or PLANTILLA
    datos = {
        'cliente': item.presupuesto.cliente.contacto or item.presupuesto.cliente.nombre,
        'servicio': item.producto.nombre,
        'fecha': f'{item.fecha_servicio:%d/%m/%Y}' if item.fecha_servicio else 'la fecha por confirmar',
        'hora': f'{item.hora_servicio:%I:%M %p}' if item.hora_servicio else '',
        'empresa': perfil.nombre_comercial,
    }
    try:
        texto = plantilla.format(**datos)
    except (KeyError, IndexError, ValueError):          # plantilla mal escrita: no rompe la agenda
        texto = PLANTILLA.format(**datos)
    return ' '.join(texto.split())


PLANTILLA = 'Hola {cliente}, le recordamos el servicio «{servicio}» programado para el {fecha}. {empresa}'


def enlace_whatsapp(item, perfil):
    """wa.me con el mensaje listo; sin teléfono válido, abre WhatsApp para elegir el contacto."""
    numero = telefono_whatsapp(item.presupuesto.cliente.telefono)
    return f'https://wa.me/{numero}?text={quote(mensaje_whatsapp(item, perfil))}'


# ── Reporte ───────────────────────────────────────────────────────────────────

def reporte(qs, desde, hasta):
    """
    Servicios REALIZADOS entre `desde` y `hasta` (fecha de ejecución), con su monto y si la venta está cobrada.
    Monto de la línea = cantidad × precio (antes de descuento e IVA, como en la analítica de ventas).
    """
    filas = list(qs.filter(realizado_en__date__gte=desde, realizado_en__date__lte=hasta)
                 .order_by('realizado_en', 'pk'))
    cero = Decimal('0')
    total = cobrado = cero
    por_servicio, por_responsable = {}, {}
    for i in filas:
        i.monto = i.subtotal_usd
        i.cobrada = not i.presupuesto.estado == E.POR_PAGAR and not (i.presupuesto.estado == E.VALIDADA
                                                                       and not i.presupuesto.pagado)
        total += i.monto
        cobrado += i.monto if i.cobrada else cero
        s = por_servicio.setdefault(i.producto_id, {'nombre': i.producto.nombre, 'n': 0, 'cantidad': 0, 'monto': cero})
        s['n'] += 1
        s['cantidad'] += i.cantidad
        s['monto'] += i.monto
        nombre = i.responsable_visible or 'Sin responsable'
        r = por_responsable.setdefault(nombre, {'nombre': nombre, 'n': 0, 'monto': cero})
        r['n'] += 1
        r['monto'] += i.monto
    pendientes = pestana(qs, 'hoy').count() + pestana(qs, 'atrasados').count()
    return {
        'filas': filas, 'total': total, 'cobrado': cobrado, 'por_cobrar': total - cobrado, 'n': len(filas),
        'por_servicio': sorted(por_servicio.values(), key=lambda x: -x['monto']),
        'por_responsable': sorted(por_responsable.values(), key=lambda x: -x['monto']),
        'pendientes_hoy': pendientes,
    }


def rango(desde, hasta):
    hoy = timezone.localdate()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


def combinar(fecha, hora):
    """Fecha + hora del formulario → datetime con zona horaria (hora vacía = ahora si es hoy, mediodía si no)."""
    if fecha is None:
        return None
    ahora = timezone.localtime()
    if hora is None:
        hora = ahora.time() if fecha == ahora.date() else datetime.min.time().replace(hour=12)
    return timezone.make_aware(datetime.combine(fecha, hora))
