from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer, Table, TableStyle

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd

from .models import ItemPresupuesto, redondear


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


def presupuesto_pdf(p, empresa, moneda='ambas'):
    """moneda: 'usd' | 'bs' | 'ambas'. Sin tasa, siempre USD."""
    perfil = empresa.perfil
    if not p.tasa_bs:
        moneda = 'usd'
    color = colors.HexColor(perfil.color_principal or '#053D74')
    titulo = 'NOTA DE VENTA' if p.es_venta else 'PRESUPUESTO'
    sub = f'N° {p.numero}<br/>Fecha: {p.fecha:%d/%m/%Y}'
    if not p.es_venta:
        sub += f'<br/>Válido hasta: {p.valido_hasta:%d/%m/%Y}'
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'{titulo.title()} {p.numero}')
    e = encabezado_empresa(empresa, titulo=titulo, subtitulo=sub)

    c = p.cliente
    datos_cliente = [f'<b>Cliente:</b> {c.nombre}' + (f' · RIF/CI: {c.rif}' if c.rif else '')]
    contacto = ' · '.join(x for x in [c.contacto, c.telefono, c.email] if x)
    if contacto:
        datos_cliente.append(contacto)
    if c.direccion:
        datos_cliente.append(c.direccion.replace('\n', ' '))
    datos_cliente.append(f'<b>Vendedor:</b> {p.vendedor.nombre_visible}')
    e += [Paragraph('<br/>'.join(datos_cliente), ESTILOS['Normal']), Spacer(1, 5 * mm)]

    en_usd, en_bs = moneda in ('usd', 'ambas'), moneda in ('bs', 'ambas')
    cab = ['#', 'Código', 'Producto', 'Cant.']
    if en_usd:
        cab += ['Precio USD', 'Subtotal USD']
    if en_bs:
        cab += ['Precio Bs', 'Subtotal Bs']
    filas = [cab]
    items = list(ItemPresupuesto.todos.filter(presupuesto=p).select_related('producto__unidad'))
    for n, i in enumerate(items, 1):
        fila = [n, i.producto.codigo, Paragraph(i.producto.nombre, ESTILO_CELDA),
                f'{i.cantidad} {i.producto.unidad.abreviatura}']
        if en_usd:
            fila += [usd(i.precio_usd), usd(i.subtotal_usd)]
        if en_bs:
            fila += [bs(redondear(i.precio_usd * p.tasa_bs)), bs(redondear(i.subtotal_usd * p.tasa_bs))]
        filas.append(fila)
    libre = 186 - 8 - 24 - 20 - (46 if en_usd else 0) - (54 if en_bs else 0)
    anchos = [8 * mm, 24 * mm, libre * mm, 20 * mm] + ([22 * mm, 24 * mm] if en_usd else []) + \
             ([26 * mm, 28 * mm] if en_bs else [])
    t = Table(filas, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
    ]))
    e += [t, Spacer(1, 4 * mm)]

    # Totales
    def fila_total(etiqueta, valor, negrita=False):
        f = [etiqueta]
        if en_usd:
            f.append(usd(valor))
        if en_bs:
            f.append(bs(redondear(valor * p.tasa_bs)))
        return f
    tot = []
    tot.append(fila_total('Subtotal', p.subtotal_usd))
    if p.descuento_usd:
        tot.append(fila_total(f'Descuento ({pct(p.descuento_pct)} %)', -p.descuento_usd))
    if p.descuento_usd and p.iva_usd:
        tot.append(fila_total('Base imponible', p.base_usd))
    if p.iva_usd:
        tot.append(fila_total(f'IVA ({pct(p.iva_pct)} %)', p.iva_usd))
    tot.append(fila_total('TOTAL', p.total_usd))
    anchos_t = [40 * mm] + ([30 * mm] if en_usd else []) + ([36 * mm] if en_bs else [])
    tt = Table(tot, colWidths=anchos_t, hAlign='RIGHT')
    tt.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (0, -1), (-1, -1), 1, color),
        ('TEXTCOLOR', (0, -1), (-1, -1), color),
    ]))
    e += [tt]
    if p.tasa_bs and en_bs:
        e.append(Paragraph(f'Tasa BCV aplicada: {bs(p.tasa_bs)} por USD',
                           ESTILOS['Italic']))
    e.append(Spacer(1, 6 * mm))

    bloque = []
    if p.condiciones:
        bloque += [Paragraph('<b>Condiciones</b>', ESTILOS['Normal']),
                   Paragraph(p.condiciones.replace('\n', '<br/>'), ESTILOS['Normal']), Spacer(1, 3 * mm)]
    if perfil.datos_bancarios:
        bloque += [Paragraph('<b>Datos para el pago</b>', ESTILOS['Normal']),
                   Paragraph(perfil.datos_bancarios.replace('\n', '<br/>'), ESTILOS['Normal']), Spacer(1, 3 * mm)]
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
