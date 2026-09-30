"""
Procesamiento de imágenes del perfil (logo y firma).
"""
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 2 * 1024 * 1024        # 2 MB
FORMATOS = {'PNG', 'JPEG'}
ANCHO_PDF = 600                     # px de la copia para PDF


def validar_imagen(archivo, etiqueta='La imagen'):
    """PNG o JPG de hasta 2 MB. SVG/GIF/WebP no: ReportLab no los dibuja bien."""
    if archivo.size > MAX_BYTES:
        raise ValidationError(f'{etiqueta} pesa {archivo.size / 1024 / 1024:.1f} MB; el máximo es 2 MB.')
    try:
        archivo.seek(0)
        with Image.open(archivo) as img:
            formato = img.format
            img.verify()
    except (UnidentifiedImageError, OSError):
        raise ValidationError(f'{etiqueta} no es una imagen válida.')
    finally:
        archivo.seek(0)
    if formato not in FORMATOS:
        raise ValidationError(f'{etiqueta} debe ser PNG o JPG (recibido: {formato or "desconocido"}).')


def generar_logo_pdf(perfil):
    """
    Crea `logo_pdf`: PNG de máx. 600 px de ancho, con transparencia conservada.
    Llamar DESPUÉS de guardar el perfil (el logo ya debe estar en el almacenamiento).
    """
    if not perfil.logo:
        if perfil.logo_pdf:
            perfil.logo_pdf.delete(save=False)
        return
    perfil.logo.open('rb')
    try:
        contenido = perfil.logo.read()
    finally:
        perfil.logo.close()
    with Image.open(BytesIO(contenido)) as img:
        img.load()
        img = img.convert('RGBA')
        if img.width > ANCHO_PDF:
            alto = round(img.height * ANCHO_PDF / img.width)
            img = img.resize((ANCHO_PDF, alto), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
    nombre = f'{Path(perfil.logo.name).stem}-pdf.png'
    if perfil.logo_pdf:
        perfil.logo_pdf.delete(save=False)
    perfil.logo_pdf.save(nombre, ContentFile(buffer.getvalue()), save=False)
