"""
Piezas comunes de los PDF de Ordo. TODOS los documentos usan encabezado_empresa()
para que el panel "Mi empresa" se refleje en presupuestos, órdenes y reportes.
"""
import re
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import HRFlowable, Image, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus import Paragraph as _Paragraph

# ReportLab lee el texto de un Paragraph como marcado: un «&» o un «<» sueltos en un dato escrito por el usuario
# («Agroservicios J&M», «Tubo < 5 ml») salían alterados («J&M;») o rompían el PDF. Se escapan aquí, una sola vez,
# respetando las entidades (&amp;) y las etiquetas que sí usamos (<b>, <br/>, <font …>).
_AMP_SUELTO = re.compile(r'&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)')
_MENOR_SUELTO = re.compile(r'<(?!/?(?:b|i|u|br|font|super|sub|strike|a|para|span|nobr)\b[^<>]*>)')


def texto_seguro(texto):
    return _MENOR_SUELTO.sub('&lt;', _AMP_SUELTO.sub('&amp;', str(texto)))


class Paragraph(_Paragraph):
    """Paragraph de ReportLab que tolera «&» y «<» en los datos. TODOS los PDF de Ordo importan este."""

    def __init__(self, text, *args, **kwargs):
        super().__init__(texto_seguro(text), *args, **kwargs)

ESTILOS = getSampleStyleSheet()
ESTILO_NOMBRE = ParagraphStyle('nombre', parent=ESTILOS['Heading2'], spaceAfter=2, leading=17)
ESTILO_DATO = ParagraphStyle('dato', parent=ESTILOS['Normal'], fontSize=8.5, leading=11, textColor=colors.HexColor('#4B5563'))
ESTILO_CELDA = ParagraphStyle('celda', parent=ESTILOS['Normal'], fontSize=8.5, leading=10.5)
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
    if logo:
        # La columna del logo mide lo que mide el logo (+ 5 mm de aire): los datos quedan pegados a él
        ancho_logo = logo.drawWidth + 5 * mm
        anchos = [ancho_logo, 130 * mm - ancho_logo, 56 * mm]
    else:
        anchos = [120 * mm, 66 * mm]
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


def documento(buffer, titulo_pdf='Documento', horizontal=False):
    from reportlab.lib.pagesizes import landscape
    return SimpleDocTemplate(buffer, pagesize=landscape(letter) if horizontal else letter, title=titulo_pdf,
                             leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=20 * mm)


# ── Nombre del archivo y respuesta HTTP ───────────────────────────────────────
_SOBRAN = {'ca', 'c.a', 'c.a.', 'sa', 's.a', 's.a.', 'srl', 's.r.l', 's.r.l.', 'rl', 'r.l', 'r.l.', 'fp', 'f.p', 'f.p.',
           'de', 'del', 'la', 'las', 'el', 'los', 'y', 'e'}


def nombre_corto(nombre, palabras=3, largo=30):
    """«Laboratorio Clínico La Esperanza, C.A.» → «Laboratorio-Clinico-Esperanza» (sin acentos ni símbolos)."""
    import unicodedata
    texto = unicodedata.normalize('NFKD', nombre or '').encode('ascii', 'ignore').decode()
    partes = [x for x in texto.replace(',', ' ').split() if x.lower() not in _SOBRAN]
    limpias = [''.join(c for c in x if c.isalnum()) for x in partes]
    salida = ''
    for x in [x for x in limpias if x][:palabras]:          # palabras completas mientras quepan
        if salida and len(salida) + 1 + len(x) > largo:
            break
        salida = f'{salida}-{x}' if salida else x[:largo]
    return salida


def nombre_archivo(*partes, extension='pdf'):
    """Une las partes con «_» (número, destino corto, fecha): 202600343_Clinica-Sol_2026-10-02.pdf"""
    from datetime import date, datetime
    limpias = []
    for x in partes:
        if isinstance(x, (date, datetime)):
            x = x.strftime('%Y-%m-%d')
        x = ''.join(c for c in str(x or '') if c.isalnum() or c in '-.').strip('-.')
        if x:
            limpias.append(x)
    return '_'.join(limpias) + f'.{extension}'


def respuesta_pdf(contenido, *partes):
    """
    PDF en línea con nombre «número_destino_fecha.pdf». El nombre es estable para un mismo documento y el
    contenido nunca se guarda en caché: cada vez que se abre, comparte o descarga sale la versión actual.
    """
    from django.http import HttpResponse
    r = HttpResponse(contenido, content_type='application/pdf')
    r['Content-Disposition'] = f'inline; filename="{nombre_archivo(*partes)}"'
    r['Cache-Control'] = 'no-store, max-age=0'
    return r
