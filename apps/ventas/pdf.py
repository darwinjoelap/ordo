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
