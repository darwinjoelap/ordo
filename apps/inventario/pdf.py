from io import BytesIO
from itertools import groupby

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd


def lista_precios_pdf(productos, empresa, mostrar_existencia=False):
    """Lista de precios agrupada por categoría. `productos` debe venir con con_stock() y ordenado por categoría."""
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf='Lista de precios')
    color = colors.HexColor(empresa.perfil.color_principal or '#053D74')
    e = encabezado_empresa(empresa, titulo='LISTA DE PRECIOS', subtitulo=f'Vigente al {timezone.localdate():%d/%m/%Y}')
    for categoria, grupo in groupby(productos, key=lambda p: p.categoria.nombre):
        grupo = list(grupo)
        e.append(Paragraph(f'<b>{categoria}</b>', ESTILOS['Heading4']))
        filas = [['Código', 'Producto', 'Marca'] + (['Disponible'] if mostrar_existencia else []) + ['Precio USD']]
        for p in grupo:
            filas.append([p.codigo, Paragraph(p.nombre, ESTILO_CELDA), p.marca.nombre if p.marca else '']
                         + ([f'{p.stock_disponible} {p.unidad.abreviatura}'] if mostrar_existencia else [])
                         + [usd(p.precio_venta_usd)])
        anchos = [26 * mm, 92 * mm, 28 * mm] + ([22 * mm] if mostrar_existencia else []) + [24 * mm]
        if not mostrar_existencia:
            anchos[1] = 114 * mm
        t = Table(filas, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
        ]))
        e += [t, Spacer(1, 4 * mm)]
    if len(e) <= 4:
        e.append(Paragraph('No hay productos para mostrar con esos filtros.', ESTILOS['Normal']))
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
