from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd


def orden_compra_pdf(orden, empresa, mostrar_costos=True):
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'Orden de compra {orden.numero}')
    color = colors.HexColor(empresa.perfil.color_principal or '#053D74')
    e = encabezado_empresa(empresa, titulo='ORDEN DE COMPRA',
                           subtitulo=f'N° {orden.numero}<br/>Fecha: {orden.fecha:%d/%m/%Y}')
    prov = orden.proveedor
    datos_prov = [f'<b>Proveedor:</b> {prov.nombre}']
    if prov.rif:
        datos_prov.append(f'RIF: {prov.rif}')
    contacto = ' · '.join(x for x in [prov.contacto, prov.telefono, prov.email] if x)
    if contacto:
        datos_prov.append(contacto)
    e += [Paragraph('<br/>'.join(datos_prov), ESTILOS['Normal']), Spacer(1, 5 * mm)]

    encabezados = ['#', 'Código', 'Producto', 'Unidad', 'Cantidad'] + (['Costo unit.', 'Subtotal'] if mostrar_costos else [])
    filas = [encabezados]
    items = list(orden.items.select_related('producto__unidad'))
    for n, i in enumerate(items, 1):
        fila = [n, i.producto.codigo, Paragraph(i.producto.nombre, ESTILO_CELDA), i.producto.unidad.abreviatura,
                i.cantidad_pedida]
        if mostrar_costos:
            fila += [usd(i.costo_unitario_usd), usd(i.subtotal_usd)]
        filas.append(fila)
    if mostrar_costos:
        filas.append([''] * 5 + ['TOTAL', usd(orden.total_usd())])
    anchos = [8 * mm, 24 * mm, 70 * mm, 16 * mm, 18 * mm] + ([24 * mm, 26 * mm] if mostrar_costos else [])
    if not mostrar_costos:
        anchos[2] = 120 * mm
    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, len(items)), [colors.white, colors.HexColor('#F3F4F6')]),
        ('LINEBELOW', (0, 0), (-1, len(items)), 0.25, colors.HexColor('#D1D5DB')),
    ]
    if mostrar_costos:
        estilo += [('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (-2, -1), (-1, -1), 1, color)]
    tabla.setStyle(TableStyle(estilo))
    e += [tabla, Spacer(1, 6 * mm)]
    if orden.notas:
        e += [Paragraph('<b>Notas</b>', ESTILOS['Normal']), Paragraph(orden.notas.replace('\n', '<br/>'), ESTILOS['Normal'])]
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
