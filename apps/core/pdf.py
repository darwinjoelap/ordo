"""
Piezas comunes de los PDF de Ordo. TODOS los documentos usan encabezado_empresa()
para que el panel "Mi empresa" se refleje en presupuestos, órdenes y reportes.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ESTILOS = getSampleStyleSheet()
ESTILO_NOMBRE = ParagraphStyle('nombre', parent=ESTILOS['Heading2'], spaceAfter=2, leading=17)
ESTILO_DATO = ParagraphStyle('dato', parent=ESTILOS['Normal'], fontSize=8.5, leading=11, textColor=colors.HexColor('#4B5563'))
ESTILO_DATO_DER = ParagraphStyle('dato_der', parent=ESTILO_DATO, alignment=TA_RIGHT)


def _imagen_logo(perfil, alto_max=22 * mm, ancho_max=46 * mm):
    archivo = perfil.logo_para_pdf
    if not archivo:
        return None
    try:
        archivo.open('rb')
        datos = BytesIO(archivo.read())
        archivo.close()
        ancho, alto = ImageReader(datos).getSize()
        escala = min(ancho_max / ancho, alto_max / alto)
        datos.seek(0)
        return Image(datos, width=ancho * escala, height=alto * escala)
    except Exception:  # un logo dañado nunca debe impedir generar el documento
        return None


def encabezado_empresa(empresa, titulo='', subtitulo=''):
    """Flowables del encabezado: logo + datos de la empresa + título del documento."""
    perfil = empresa.perfil
    color = colors.HexColor(perfil.color_principal or '#053D74')
    estilo_nombre = ParagraphStyle('n', parent=ESTILO_NOMBRE, textColor=color)

    datos = [Paragraph(perfil.nombre_comercial or empresa.nombre, estilo_nombre)]
    if perfil.razon_social and perfil.razon_social != perfil.nombre_comercial:
        datos.append(Paragraph(perfil.razon_social, ESTILO_DATO))
    if perfil.rif:
        datos.append(Paragraph(f'RIF: {perfil.rif}', ESTILO_DATO))
    if perfil.direccion_fiscal:
        datos.append(Paragraph(perfil.direccion_fiscal.replace('\n', '<br/>'), ESTILO_DATO))
    contacto = ' · '.join(x for x in [perfil.telefono, perfil.telefono_2, perfil.email, perfil.sitio_web] if x)
    if contacto:
        datos.append(Paragraph(contacto, ESTILO_DATO))

    derecha = []
    if titulo:
        derecha.append(Paragraph(f'<b>{titulo}</b>', ParagraphStyle('t', parent=ESTILOS['Heading3'],
                                                                    alignment=TA_RIGHT, textColor=color)))
    if subtitulo:
        derecha.append(Paragraph(subtitulo, ESTILO_DATO_DER))

    logo = _imagen_logo(perfil)
    celdas = [logo, datos, derecha] if logo else [datos, derecha]
    anchos = [50 * mm, 80 * mm, 56 * mm] if logo else [120 * mm, 66 * mm]
    tabla = Table([celdas], colWidths=anchos)
    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    return [tabla, Spacer(1, 3 * mm), HRFlowable(width='100%', thickness=1.4, color=color), Spacer(1, 5 * mm)]


def pie_empresa(empresa):
    """Función para onPage: pie con texto de la empresa y marca Ordo discreta."""
    perfil = empresa.perfil

    def dibujar(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(colors.HexColor('#6B7280'))
        if perfil.pie_documentos:
            canvas.drawString(doc.leftMargin, 12 * mm, perfil.pie_documentos[:150])
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 12 * mm,
                               f'Página {doc.page} · Generado con Ordo')
        canvas.restoreState()
    return dibujar


def documento(buffer, titulo_pdf='Documento'):
    return SimpleDocTemplate(buffer, pagesize=letter, title=titulo_pdf,
                             leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=20 * mm)
