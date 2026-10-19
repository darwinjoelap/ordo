from io import BytesIO
from itertools import groupby

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Spacer, Table, TableStyle

from apps.core.pdf import Paragraph  # noqa: E402  (escapa & y < de los datos)

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd


def lista_precios_pdf(productos, empresa, mostrar_existencia=False, tasa=None):
    """Lista de precios agrupada por categoría. `productos` debe venir con con_stock() y ordenado por categoría."""
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf='Lista de precios')
    color = colors.HexColor(empresa.perfil.color_principal or '#053D74')
    from apps.ventas.models import redondear
    from apps.ventas.pdf import bs
    sub = f'Vigente al {timezone.localdate():%d/%m/%Y}'
    if tasa:
        sub += f'<br/>Tasa BCV: {bs(tasa.bs_por_usd)} ({tasa.fecha:%d/%m/%Y})'
    e = encabezado_empresa(empresa, titulo='LISTA DE PRECIOS', subtitulo=sub)
    for categoria, grupo in groupby(productos, key=lambda p: p.categoria.nombre):
        grupo = list(grupo)
        e.append(Paragraph(f'<b>{categoria}</b>', ESTILOS['Heading4']))
        filas = [['Código', 'Producto', 'Marca'] + (['Disponible'] if mostrar_existencia else []) + ['Precio USD'] + (['Precio Bs'] if tasa else [])]
        for p in grupo:
            filas.append([p.codigo, Paragraph(p.nombre, ESTILO_CELDA), p.marca.nombre if p.marca else '']
                         + ([('Servicio' if p.es_servicio else f'{p.stock_disponible} {p.unidad.abreviatura}')] if mostrar_existencia else [])
                         + [usd(p.precio_venta_usd)]
                         + ([bs(redondear(p.precio_venta_usd * tasa.bs_por_usd))] if tasa else []))
        anchos = [26 * mm, 92 * mm, 28 * mm] + ([22 * mm] if mostrar_existencia else []) + [24 * mm] \
            + ([28 * mm] if tasa else [])
        anchos[1] = (186 - 26 - 28 - 24 - (22 if mostrar_existencia else 0) - (28 if tasa else 0)) * mm
        t = Table(filas, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (-2 if tasa else -1, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
        ]))
        e += [t, Spacer(1, 4 * mm)]
    if len(e) <= 4:
        e.append(Paragraph('No hay productos para mostrar con esos filtros.', ESTILOS['Normal']))
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()


def traslado_pdf(t, items, empresa):
    """Comprobante de traslado entre almacenes, con firmas de quien entrega y quien recibe."""
    perfil = empresa.perfil
    color = colors.HexColor(perfil.color_principal or '#053D74')
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'Traslado {t.numero}')
    cuando = timezone.localtime(t.fecha)
    e = encabezado_empresa(empresa, titulo='TRASLADO ENTRE ALMACENES', subtitulo='<br/>'.join([
        f'<font size="12"><b>N° {t.numero}</b></font>', '', f'Fecha: {cuando:%d/%m/%Y %H:%M}',
        f'Registró: {t.usuario.nombre_visible}']))
    e += [Paragraph(f'<b>Desde:</b> {t.origen.nombre if t.origen_id else "Sin almacén"} &nbsp;&nbsp; '
                    f'<b>Hacia:</b> {t.destino.nombre}', ESTILO_CELDA)]
    if t.notas:
        e.append(Paragraph(f'<b>Notas:</b> {t.notas}', ESTILO_CELDA))
    e.append(Spacer(1, 4 * mm))
    filas = [['Código', 'Producto', 'Lote', 'Vence', 'Cantidad']]
    for i in items:
        lote = i.lote_origen
        filas.append([i.producto.codigo, Paragraph(i.producto.nombre, ESTILO_CELDA), lote.numero_lote or '—',
                      f'{lote.fecha_vencimiento:%d/%m/%Y}' if lote.fecha_vencimiento else '—',
                      f'{i.cantidad} {i.producto.unidad.abreviatura}'])
    filas.append(['', f'{len(items)} línea(s)', '', 'Total', str(sum(i.cantidad for i in items))])
    tabla = Table(filas, colWidths=[28 * mm, 82 * mm, 28 * mm, 22 * mm, 26 * mm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F3F4F6')]),
        ('LINEABOVE', (0, -1), (-1, -1), 1, color), ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    firma = lambda titulo: Paragraph(f'<br/><br/><br/>______________________________<br/><b>{titulo}</b><br/>'  # noqa: E731
                                     'Nombre: ____________________<br/>C.I.: ________________', ESTILO_CELDA)
    firmas = Table([[firma('Entrega'), firma('Recibe')]], colWidths=[93 * mm, 93 * mm])
    e += [tabla, Spacer(1, 8 * mm), firmas]
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
