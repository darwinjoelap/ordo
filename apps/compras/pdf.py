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


def panel_pedido_pdf(empresa, clasificaciones, dias, filtros=''):
    """clasificaciones: salida de sugerencias.por_clasificacion()."""
    from django.utils import timezone

    from apps.core.pdf import ESTILO_DATO
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf='Panel de pedido')
    color = colors.HexColor(empresa.perfil.color_principal or '#053D74')
    gris = colors.HexColor('#E5E7EB')
    e = encabezado_empresa(empresa, titulo='PEDIDO SUGERIDO',
                           subtitulo=f'Fecha: {timezone.localdate():%d/%m/%Y}<br/>Cobertura: {dias} días')
    if filtros:
        e += [Paragraph(f'<b>Filtros:</b> {filtros}', ESTILO_DATO), Spacer(1, 3 * mm)]

    filas = [['Código', 'Producto', 'Proveedor', 'Disp.', 'En camino', 'Pedir', 'Und.']]
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (3, 0), (5, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#D1D5DB')),
    ]
    total = productos = 0
    for clas, lineas, unidades in clasificaciones:
        n = len(filas)
        filas.append([Paragraph(f'<b>{clas}</b>', ESTILO_CELDA), '', '', '', '',
                      Paragraph(f'<para align="right"><b>{unidades}</b></para>', ESTILO_CELDA), 'und.'])
        estilo += [('SPAN', (0, n), (4, n)), ('BACKGROUND', (0, n), (-1, n), gris)]
        for s, cantidad in lineas:
            p = s.producto
            filas.append([p.codigo, Paragraph(p.nombre, ESTILO_CELDA),
                          Paragraph(p.proveedor_habitual.nombre if p.proveedor_habitual else '—', ESTILO_CELDA),
                          s.disponible, s.en_camino or '—', cantidad, p.unidad.abreviatura])
        total += unidades
        productos += len(lineas)
    n = len(filas)
    filas.append([f'TOTAL GENERAL · {productos} productos · {len(clasificaciones)} clasificaciones', '', '', '', '',
                  total, 'und.'])
    estilo += [('SPAN', (0, n), (4, n)), ('FONTNAME', (0, n), (-1, n), 'Helvetica-Bold'),
               ('LINEABOVE', (0, n), (-1, n), 1, color)]
    tabla = Table(filas, colWidths=[24 * mm, 66 * mm, 38 * mm, 14 * mm, 18 * mm, 14 * mm, 12 * mm], repeatRows=1)
    tabla.setStyle(TableStyle(estilo))
    e.append(tabla)
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
