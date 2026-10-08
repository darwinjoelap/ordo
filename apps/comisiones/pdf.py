from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Spacer, Table, TableStyle

from apps.core.pdf import Paragraph  # noqa: E402  (escapa & y < de los datos)

from apps.core.pdf import ESTILO_CELDA, ESTILOS, documento, encabezado_empresa, pie_empresa
from apps.core.templatetags.ordo import usd

from .models import AjusteComision, Comision


def liquidacion_pdf(liq, empresa):
    color = colors.HexColor(empresa.perfil.color_principal or '#053D74')
    buffer = BytesIO()
    doc = documento(buffer, titulo_pdf=f'Liquidación {liq.numero}')
    sub = f'N° {liq.numero}<br/>Fecha: {liq.creada_en:%d/%m/%Y}<br/>Ventas hasta: {liq.hasta:%d/%m/%Y}'
    e = encabezado_empresa(empresa, titulo='LIQUIDACIÓN DE COMISIONES', subtitulo=sub)
    nombre = liq.vendedor.nombre_visible
    estado = liq.estado + (f' el {liq.fecha_pago:%d/%m/%Y}' if liq.pagada else '')
    if liq.pagada and liq.metodo_pago:
        estado += f' · {liq.metodo_pago}' + (f' · Ref. {liq.referencia}' if liq.referencia else '')
    e += [Paragraph(f'<b>Vendedor:</b> {nombre}<br/><b>Estado:</b> {estado}', ESTILOS['Normal']), Spacer(1, 5 * mm)]
    filas = [['Fecha', 'Venta', 'Cliente', 'Base sin IVA', '%', 'Comisión']]
    comisiones = Comision.todos.filter(liquidacion=liq).select_related('presupuesto__cliente').order_by('fecha', 'pk')
    for c in comisiones:
        filas.append([f'{c.fecha:%d/%m/%Y}', c.presupuesto.numero, Paragraph(c.presupuesto.cliente.nombre, ESTILO_CELDA),
                      usd(c.base_usd), f'{c.porcentaje_efectivo:.2f}'.replace('.', ','), usd(c.monto_usd)])
    for a in AjusteComision.todos.filter(liquidacion=liq).select_related('devolucion__presupuesto__cliente') \
            .order_by('fecha', 'pk'):
        filas.append([f'{a.fecha:%d/%m/%Y}', a.devolucion.numero,
                      Paragraph(f'Devolución de {a.devolucion.presupuesto.numero} · {a.devolucion.presupuesto.cliente.nombre}',
                                ESTILO_CELDA), '', '', usd(a.monto_usd)])
    filas.append(['', '', 'TOTAL', '', '', usd(liq.total_usd)])
    t = Table(filas, colWidths=[20 * mm, 32 * mm, 62 * mm, 28 * mm, 14 * mm, 30 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), color), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F3F4F6')]),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (0, -1), (-1, -1), 1, color),
    ]))
    e += [t, Spacer(1, 16 * mm)]
    firmas = Table([['_' * 32, '_' * 32], ['Entregado por', f'Recibido: {nombre}']], colWidths=[90 * mm, 90 * mm])
    firmas.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('FONTSIZE', (0, 0), (-1, -1), 9)]))
    e.append(firmas)
    pie = pie_empresa(empresa)
    doc.build(e, onFirstPage=pie, onLaterPages=pie)
    return buffer.getvalue()
