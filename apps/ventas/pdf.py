from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, Spacer, Table, TableStyle

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd

from django.db.models.functions import Lower

from .models import ItemPresupuesto, desglose_bs, redondear


def bs(valor):
    entero, dec = f'{abs(Decimal(valor or 0)):,.2f}'.split('.')
    return f"Bs {entero.replace(',', '.')},{dec}"


def pct(valor):
    return f'{Decimal(valor).normalize():f}'.replace('.', ',')


def _firma(perfil):
    if not perfil.firma:
        return None
    try:
        perfil.firma.open('rb')
        datos = BytesIO(perfil.firma.read())
        perfil.firma.close()
        img = Image(datos)
        escala = min(45 * mm / img.drawWidth, 22 * mm / img.drawHeight)
        img.drawWidth, img.drawHeight = img.drawWidth * escala, img.drawHeight * escala
        return img
    except Exception:
        return None


def lotes_por_item(p, items):
    """
    {item_id: {'lotes': [(numero, vence, cantidad)], 'falta': n, 'referencial': bool}} para el PDF.
    Con stock apartado/vendido se usan sus lotes reales; si no, un reparto FEFO referencial del stock
    disponible (sin lotes vencidos). Productos sin lote ni vencimiento no muestran nada.
    """
    from django.db.models import F
    from django.utils import timezone

    from apps.inventario.models import Lote

    from .models import Reserva
    hoy = timezone.localdate()
    reales = {}
    for r in Reserva.todos.filter(item__presupuesto=p).select_related('lote').order_by('lote__fecha_vencimiento', 'pk'):
        reales.setdefault(r.item_id, []).append(r)
    resultado = {}
    usados = {}                           # lo ya asignado en este mismo documento (mismo producto en dos líneas)
    for i in items:
        prod = i.producto
        if not (prod.maneja_lotes or prod.maneja_vencimiento):
            continue
        if i.pk in reales:
            resultado[i.pk] = {'lotes': [(r.lote.numero_lote, r.lote.fecha_vencimiento, r.cantidad) for r in reales[i.pk]],
                               'falta': 0, 'referencial': False}
            continue
        lotes = (Lote.todos.filter(producto=prod, cantidad_actual__gt=F('cantidad_apartada'))
                 .exclude(fecha_vencimiento__lt=hoy)
                 .order_by(F('fecha_vencimiento').asc(nulls_last=True), 'fecha_ingreso', 'pk'))
        asignados, pendiente = [], i.cantidad
        for lote in lotes:
            libre = lote.cantidad_disponible - usados.get(lote.pk, 0)
            tomar = min(libre, pendiente)
            if tomar > 0:
                asignados.append((lote.numero_lote, lote.fecha_vencimiento, tomar))
                usados[lote.pk] = usados.get(lote.pk, 0) + tomar
                pendiente -= tomar
            if not pendiente:
                break
        resultado[i.pk] = {'lotes': asignados, 'falta': pendiente, 'referencial': True}
    return resultado


GRIS_CLARO = colors.HexColor('#F8F9FA')
GRIS_BORDE = colors.HexColor('#DEE2E6')
GRIS_TEXTO = colors.HexColor('#6C757D')


def _estilo(nombre, **kw):
    base = {'parent': ESTILOS['Normal'], 'fontSize': 9, 'leading': 11}
    base.update(kw)
    return ParagraphStyle(nombre, **base)


E_NORMAL = _estilo('p_normal')
E_BOLD = _estilo('p_bold', fontName='Helvetica-Bold')
E_CENTRO = _estilo('p_centro', alignment=TA_CENTER)
E_DER = _estilo('p_der', alignment=TA_RIGHT)
E_LOTE = _estilo('p_lote', fontSize=8, leading=10, textColor=GRIS_TEXTO)
E_PEQUENO = _estilo('p_pequeno', fontSize=8, leading=10, textColor=GRIS_TEXTO)


def _celda_descripcion(producto):
    """Nombre con la marca como sublínea."""
    texto = producto.nombre
    if producto.marca_id:
        texto += f'<br/><font size="7" color="#6C757D"><i>{producto.marca.nombre}</i></font>'
    return Paragraph(texto, E_NORMAL)


def _celdas_lote(producto, info):
    """
    (celda Lote, celda F. Venc.) en la MISMA fila del producto: un renglón por lote dentro de la celda.
    Con más de un lote, la cantidad de cada uno va entre paréntesis.
    """
    if not info:
        return Paragraph('N/A', E_LOTE), Paragraph('N/A', E_LOTE)
    lotes, varios = info['lotes'], len(info['lotes']) > 1
    numeros = [(numero or '—') + (f' ({cant})' if varios else '') for numero, _, cant in lotes]
    fechas = [f'{vence:%d/%m/%Y}' if vence else '—' for _, vence, _ in lotes]
    if info['falta']:
        faltan = f' (faltan {info["falta"]})' if lotes else ''
        numeros.append(f'<font color="#DC3545"><b>SIN STOCK</b>{faltan}</font>')
        fechas.append('<font color="#DC3545">—</font>')
    return Paragraph('<br/>'.join(numeros), E_LOTE), Paragraph('<br/>'.join(fechas), E_LOTE)


def presupuesto_pdf(p, empresa, moneda='ambas', tasa_referencial=False):
    """
    Presupuesto / nota de venta (formato BioLifeVentas). moneda: 'usd' | 'bs' | 'ambas'. Sin tasa, siempre USD.
    Lote y F. Venc. muestran todos los lotes del producto en su misma fila.
    """
    perfil = empresa.perfil
    if not p.tasa_bs:
        moneda = 'usd'
    color = colors.HexColor(perfil.color_principal or '#053D74')
    titulo = 'NOTA DE VENTA' if p.es_venta else 'PRESUPUESTO'
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'{titulo.title()} {p.numero or "borrador"}')

    # ── Encabezado: logo | empresa | número, fechas, vendedor y tasa ──────────
    der = [f'<font size="12"><b>{("N° " + p.numero) if p.numero else "BORRADOR"}</b></font>', '', f'Fecha: {p.fecha:%d/%m/%Y}']
    if not p.es_venta:
        der.append(f'Válido hasta: {p.valido_hasta:%d/%m/%Y}')
    der.append(f'Vendedor: {p.vendedor.nombre_visible}')
    if moneda != 'usd':
        der.append(f'Tasa: Bs {p.tasa_bs:.4f}/USD'.replace('.', ',') + (' (referencial)' if tasa_referencial else ''))
    e = encabezado_empresa(empresa, titulo=titulo, subtitulo='<br/>'.join(der))

    # ── Cliente ───────────────────────────────────────────────────────────────
    c = p.cliente
    blanco = _estilo('p_cli', fontSize=8, textColor=colors.white, fontName='Helvetica-Bold')
    datos_cli = [
        [Paragraph('CLIENTE', blanco), ''],
        [Paragraph(f'<b>{c.nombre}</b>', E_NORMAL), Paragraph(f'RIF/Cédula: {c.rif or "—"}', E_NORMAL)],
        [Paragraph((c.direccion or '—').replace('\n', '<br/>'), E_NORMAL), Paragraph(f'Tel: {c.telefono or "—"}', E_NORMAL)],
        [Paragraph(f'Contacto: {c.contacto or "—"}', E_NORMAL), Paragraph(f'Email: {c.email or "—"}', E_NORMAL)],
    ]
    tc = Table(datos_cli, colWidths=[96 * mm, 90 * mm])
    tc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 1), (-1, -1), GRIS_CLARO), ('BOX', (0, 0), (-1, -1), 0.5, GRIS_BORDE),
        ('INNERGRID', (0, 1), (-1, -1), 0.25, GRIS_BORDE), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    e += [tc, Spacer(1, 4 * mm)]

    # ── Ítems ─────────────────────────────────────────────────────────────────
    blanco_c = _estilo('p_hc', textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_CENTER)
    blanco_d = _estilo('p_hd', textColor=colors.white, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    blanco_i = _estilo('p_hi', textColor=colors.white, fontName='Helvetica-Bold')
    cab = [Paragraph('Cód.', blanco_i), Paragraph('Descripción', blanco_i), Paragraph('Lote', blanco_i),
           Paragraph('F. Venc.', blanco_i), Paragraph('Cant.', blanco_c)]
    if moneda == 'ambas':
        cab += [Paragraph('P. Unit USD', blanco_d), Paragraph('Sub. USD', blanco_d), Paragraph('Sub. Bs', blanco_d)]
        anchos = [18, 44, 24, 19, 12, 21, 21, 27]
    elif moneda == 'bs':
        cab += [Paragraph('P. Unit Bs', blanco_d), Paragraph('Subtotal Bs', blanco_d)]
        anchos = [20, 52, 26, 20, 14, 26, 28]
    else:
        cab += [Paragraph('P. Unit USD', blanco_d), Paragraph('Subtotal USD', blanco_d)]
        anchos = [20, 56, 26, 20, 14, 24, 26]
    filas = [cab]
    items = list(ItemPresupuesto.todos.filter(presupuesto=p).select_related('producto__unidad', 'producto__marca')
                 .order_by(Lower('producto__nombre'), 'pk'))
    lotes = lotes_por_item(p, items)
    montos_bs = desglose_bs(p, items)
    for i in items:
        lote, venc = _celdas_lote(i.producto, lotes.get(i.pk))
        fila = [Paragraph(i.producto.codigo, E_NORMAL), _celda_descripcion(i.producto), lote, venc,
                Paragraph(f'{i.cantidad}', E_CENTRO)]
        precio_bs = redondear(i.precio_usd * p.tasa_bs) if p.tasa_bs else None
        if moneda == 'ambas':
            fila += [Paragraph(usd(i.precio_usd), E_DER), Paragraph(usd(i.subtotal_usd), E_DER),
                     Paragraph(bs(montos_bs['lineas'][i.pk]), E_DER)]
        elif moneda == 'bs':
            fila += [Paragraph(bs(precio_bs), E_DER), Paragraph(bs(montos_bs['lineas'][i.pk]), E_DER)]
        else:
            fila += [Paragraph(usd(i.precio_usd), E_DER), Paragraph(usd(i.subtotal_usd), E_DER)]
        filas.append(fila)
    t = Table(filas, colWidths=[a * mm for a in anchos], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, GRIS_CLARO]),
        ('BOX', (0, 0), (-1, -1), 0.5, GRIS_BORDE), ('INNERGRID', (0, 0), (-1, -1), 0.25, GRIS_BORDE),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    e += [t, Spacer(1, 3 * mm)]

    # ── Totales ───────────────────────────────────────────────────────────────
    def fila_total(etiqueta, valor_usd, clave_bs, negativo=False):
        signo = '-' if negativo else ''
        valor_bs = montos_bs[clave_bs] if montos_bs else None
        if moneda == 'usd':
            return [etiqueta, f'{signo}{usd(valor_usd)}']
        if moneda == 'bs':
            return [etiqueta, f'{signo}{bs(valor_bs)}']
        return [etiqueta, f'{signo}{usd(valor_usd)}', f'{signo}{bs(valor_bs)}']

    unidades = sum(i.cantidad for i in items)
    tot = [['Total unidades:', f'{unidades}'] + ([''] if moneda == 'ambas' else [])]
    tot.append(fila_total('Subtotal:', p.subtotal_usd, 'subtotal'))
    if p.descuento_usd:
        tot.append(fila_total(f'Descuento ({pct(p.descuento_pct)} %):', p.descuento_usd, 'descuento', negativo=True))
        tot.append(fila_total('Subtotal con descuento:', p.base_usd, 'base'))
    if p.iva_usd:
        tot.append(fila_total(f'IVA ({pct(p.iva_pct)} %):', p.iva_usd, 'iva'))
    if moneda == 'usd':
        tot.append(['TOTAL USD:', usd(p.total_usd)])
    elif moneda == 'bs':
        tot.append(['TOTAL USD (ref.):', usd(p.total_usd)])
        tot.append(['TOTAL Bs:', bs(montos_bs['total'])])
    else:
        tot.append(['TOTAL:', usd(p.total_usd), bs(montos_bs['total'])])
    anchos_t = [85 * mm, 35 * mm, 35 * mm] if moneda == 'ambas' else [100 * mm, 40 * mm]
    tt = Table(tot, colWidths=anchos_t, hAlign='RIGHT')
    tt.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 0), (-1, 0), GRIS_CLARO), ('TEXTCOLOR', (0, 0), (-1, 0), GRIS_TEXTO),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, GRIS_BORDE),
        ('LINEABOVE', (0, -1), (-1, -1), 1, color), ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10), ('TEXTCOLOR', (0, -1), (-1, -1), color),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    e.append(tt)

    # ── Avisos ────────────────────────────────────────────────────────────────
    if p.estado == p.E.APARTADO and p.apartado_hasta:
        from django.utils import timezone
        e += [Spacer(1, 3 * mm), Paragraph(
            f'<b>PRESUPUESTO APARTADO</b>: productos reservados en inventario hasta el '
            f'{timezone.localtime(p.apartado_hasta):%d/%m/%Y %H:%M}. Pasada esa fecha el apartado se libera.',
            _estilo('p_aviso', fontSize=8, textColor=colors.HexColor('#856404'), backColor=colors.HexColor('#FFF3CD'),
                    borderColor=colors.HexColor('#FFC107'), borderWidth=0.5, borderPadding=6))]
    if any(x['referencial'] and (x['lotes'] or x['falta']) for x in lotes.values()):
        e += [Spacer(1, 3 * mm), Paragraph('* Lote y fecha de vencimiento son referenciales (FEFO). '
                                           'Se confirman al apartar.', _estilo('p_nota', fontSize=7, textColor=GRIS_TEXTO))]

    # ── Condiciones, datos de pago y firma ────────────────────────────────────
    e += [Spacer(1, 4 * mm), HRFlowable(width='100%', thickness=0.5, color=GRIS_BORDE), Spacer(1, 2 * mm)]
    bloque = []
    if p.condiciones:
        bloque.append(Paragraph(f'<b>Condiciones:</b> {p.condiciones.replace(chr(10), "<br/>")}', E_PEQUENO))
    if perfil.datos_bancarios:
        bloque.append(Paragraph(f'<b>Datos para el pago:</b><br/>{perfil.datos_bancarios.replace(chr(10), "<br/>")}',
                                E_PEQUENO))
    firma = _firma(perfil)
    if firma:
        bloque += [Spacer(1, 4 * mm), firma]
    if bloque:
        e.append(KeepTogether(bloque))
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()


def devolucion_pdf(dev, empresa):
    """Nota de devolución: lo que el cliente devuelve, con montos de la venta original (USD y Bs)."""
    from .models import ItemDevolucion
    p = dev.presupuesto
    perfil = empresa.perfil
    color = colors.HexColor(perfil.color_principal or '#053D74')
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'Devolución {dev.numero}')
    sub = f'N° {dev.numero}<br/>Fecha: {dev.fecha:%d/%m/%Y}<br/>Venta: {p.numero} ({p.fecha:%d/%m/%Y})'
    e = encabezado_empresa(empresa, titulo='NOTA DE DEVOLUCIÓN', subtitulo=sub)
    c = p.cliente
    datos = [f'<b>Cliente:</b> {c.nombre}' + (f' · RIF/CI: {c.rif}' if c.rif else ''),
             f'<b>Vendedor:</b> {p.vendedor.nombre_visible}', f'<b>Motivo:</b> {dev.motivo}']
    e += [Paragraph('<br/>'.join(datos), ESTILOS['Normal']), Spacer(1, 5 * mm)]

    filas = [['#', 'Código', 'Producto', 'Lote', 'Cant.', 'Precio USD', 'Subtotal USD']]
    lineas = ItemDevolucion.todos.filter(devolucion=dev).select_related('item__producto__unidad', 'lote')
    for n, li in enumerate(lineas, 1):
        prod = li.item.producto
        nombre = prod.nombre + ('' if li.reingresa else ' <i>(no vuelve al inventario)</i>')
        filas.append([n, prod.codigo, Paragraph(nombre, ESTILO_CELDA),
                      (li.lote.numero_lote or '-') if li.lote else '-', f'{li.cantidad} {prod.unidad.abreviatura}',
                      usd(li.item.precio_usd), usd(li.subtotal_usd)])
    t = Table(filas, colWidths=[8 * mm, 24 * mm, 66 * mm, 22 * mm, 18 * mm, 22 * mm, 26 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (4, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
    ]))
    e += [t, Spacer(1, 4 * mm)]

    con_bs = bool(p.tasa_bs)

    def fila(etiqueta, valor, valor_bs=None):
        f = [etiqueta, usd(valor)]
        if con_bs:
            f.append(bs(valor_bs if valor_bs is not None else redondear(valor * p.tasa_bs)))
        return f
    tot = [fila('Subtotal', dev.subtotal_usd)]
    if dev.descuento_usd:
        tot.append(fila(f'Descuento ({pct(p.descuento_pct)} %)', -dev.descuento_usd))
    if dev.iva_usd:
        tot.append(fila(f'IVA ({pct(p.iva_pct)} %)', dev.iva_usd))
    tot.append(fila('TOTAL DEVUELTO', dev.total_usd, dev.total_bs))
    tt = Table(tot, colWidths=[44 * mm, 30 * mm] + ([36 * mm] if con_bs else []), hAlign='RIGHT')
    tt.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (0, -1), (-1, -1), 1, color),
        ('TEXTCOLOR', (0, -1), (-1, -1), color),
    ]))
    e.append(tt)
    if con_bs:
        e.append(Paragraph(f'Tasa BCV de la venta: {bs(p.tasa_bs)} por USD', ESTILOS['Italic']))
    e.append(Spacer(1, 5 * mm))
    if dev.reembolsado:
        texto = (f'<b>Reembolso:</b> {usd(dev.reembolso_usd)}'
                 + (f' ({bs(dev.reembolso_bs)})' if dev.reembolso_bs else '')
                 + f' · {dev.get_reembolso_metodo_display()} · {dev.reembolso_fecha:%d/%m/%Y}'
                 + (f' · Ref. {dev.reembolso_referencia}' if dev.reembolso_referencia else ''))
    else:
        texto = '<b>Reembolso:</b> pendiente / no aplica'
    e += [Paragraph(texto, ESTILOS['Normal']), Spacer(1, 16 * mm)]
    firmas = Table([['_' * 32, '_' * 32], [f'Entregado: {c.nombre}', f'Recibido: {empresa.nombre}']],
                   colWidths=[90 * mm, 90 * mm])
    firmas.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('FONTSIZE', (0, 0), (-1, -1), 9)]))
    e.append(KeepTogether([firmas]))
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()


def facturacion_pdf(ventas, t, f, empresa):
    """Reporte de facturación (libro de ventas) del período."""
    from django.utils import timezone
    perfil = empresa.perfil
    color = colors.HexColor(perfil.color_principal or '#053D74')
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf='Reporte de facturación')
    filtros = []
    if f['factura'] == 'si':
        filtros.append('solo facturadas')
    elif f['factura'] == 'no':
        filtros.append('sin facturar')
    if f['pago'] == 'si':
        filtros.append('solo pagadas')
    elif f['pago'] == 'no':
        filtros.append('no pagadas')
    sub = (f'Del {f["desde"]:%d/%m/%Y} al {f["hasta"]:%d/%m/%Y}<br/>'
           f'Por fecha de {"factura" if f["por"] == "factura" else "venta"}'
           + (f'<br/>{", ".join(filtros).capitalize()}' if filtros else '')
           + f'<br/>Generado: {timezone.localtime():%d/%m/%Y %H:%M}')
    e = encabezado_empresa(empresa, titulo='REPORTE DE FACTURACIÓN', subtitulo=sub)
    filas = [['Fecha', 'Venta', 'Cliente', 'Factura', 'Control', 'F. factura', 'Neto USD', 'Pag.']]
    for p in ventas:
        fecha = timezone.localtime(p.validado_en).date() if p.validado_en else p.fecha
        cliente = p.cliente.nombre + (f'<br/><font size="7" color="#6B7280">{p.cliente.rif}</font>' if p.cliente.rif else '')
        filas.append([f'{fecha:%d/%m/%Y}', p.numero, Paragraph(cliente, ESTILO_CELDA), p.numero_factura or '—',
                      p.numero_control or '—', f'{p.fecha_facturacion:%d/%m/%Y}' if p.fecha_facturacion else '—',
                      usd(p.neto_usd), 'Sí' if p.pagado else 'No'])
    filas.append(['', '', f'{t["n"] or 0} ventas', '', '', 'TOTAL', usd(t['neto'] or 0), ''])
    tabla = Table(filas, colWidths=[18 * mm, 27 * mm, 51 * mm, 22 * mm, 22 * mm, 18 * mm, 20 * mm, 8 * mm],
                  repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (6, 0), (6, -1), 'RIGHT'), ('ALIGN', (7, 0), (7, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F3F4F6')]),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (0, -1), (-1, -1), 1, color),
    ]))
    e += [tabla, Spacer(1, 6 * mm)]
    resumen = [['Facturadas', f'{t["n_fact"] or 0}', usd(t['fact'] or 0)],
               ['Sin facturar', f'{t["n_sin"] or 0}', usd(t['sin'] or 0)],
               ['Pagadas', f'{t["n_pag"] or 0}', usd(t['pag'] or 0)]]
    if t.get('devuelto'):
        resumen.append(['Devoluciones descontadas', '', usd(t['devuelto'])])
    tr = Table(resumen, colWidths=[50 * mm, 15 * mm, 30 * mm], hAlign='RIGHT')
    tr.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 8.5), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                            ('LINEBELOW', (0, 0), (-1, -2), 0.25, colors.HexColor('#E5E7EB'))]))
    e += [tr, Spacer(1, 3 * mm),
          Paragraph('Montos en USD, netos de devoluciones e incluyen IVA.', ESTILOS['Italic'])]
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
