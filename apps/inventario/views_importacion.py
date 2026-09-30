from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere

from . import importacion
from .models import ImportacionProductos, Producto, Unidad

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _descarga(contenido, nombre):
    r = HttpResponse(contenido, content_type=XLSX)
    r['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return r


@login_required
@requiere('inventario.gestionar')
def plantilla(request):
    unidades = [(u.abreviatura, u.nombre) for u in Unidad.objects.all()]
    return _descarga(importacion.generar_plantilla(unidades), 'plantilla-productos-ordo.xlsx')


@login_required
@requiere('inventario.gestionar')
def exportar(request):
    productos = Producto.objects.select_related('categoria', 'subcategoria', 'marca', 'unidad',
                                                'proveedor_habitual').order_by('codigo')
    fecha = timezone.localdate().strftime('%Y%m%d')
    return _descarga(importacion.exportar_productos(productos), f'productos-{request.empresa.slug}-{fecha}.xlsx')


@login_required
@requiere('inventario.gestionar')
def importar(request):
    if request.method == 'POST':
        archivo = request.FILES.get('archivo')
        if not archivo:
            messages.error(request, 'Elige un archivo .xlsx.')
            return redirect('inventario:importar')
        if not archivo.name.lower().endswith('.xlsx'):
            messages.error(request, 'El archivo debe ser Excel .xlsx (si lo tienes en .xls o .csv, ábrelo y guárdalo como .xlsx).')
            return redirect('inventario:importar')
        if archivo.size > importacion.MAX_BYTES:
            messages.error(request, 'El archivo supera 5 MB.')
            return redirect('inventario:importar')
        contenido = archivo.read()
        try:
            resultado = importacion.validar(contenido)
        except importacion.ErrorArchivo as e:
            messages.error(request, str(e))
            return redirect('inventario:importar')
        imp = ImportacionProductos.objects.create(
            nombre_archivo=archivo.name[:200], contenido=contenido, usuario=request.user,
            estado=ImportacionProductos.Estado.VALIDADA if resultado.valido else ImportacionProductos.Estado.CON_ERRORES,
            resumen=resultado.resumen(), errores=[list(e) for e in resultado.errores],
            avisos=[list(a) for a in resultado.avisos])
        return redirect('inventario:importar_revision', pk=imp.pk)
    return render(request, 'inventario/importar.html', {
        'titulo': 'Importar productos',
        'columnas': importacion.COLUMNAS, 'reglas': importacion.REGLAS,
        'historial': ImportacionProductos.objects.select_related('usuario').defer('contenido')[:10],
    })


@login_required
@requiere('inventario.gestionar')
def importar_revision(request, pk):
    imp = get_object_or_404(ImportacionProductos.objects.defer('contenido'), pk=pk)
    return render(request, 'inventario/importar_revision.html', {
        'titulo': 'Revisión de importación', 'imp': imp, 'r': imp.resumen,
        'errores': imp.errores[:500], 'avisos': imp.avisos[:200],
    })


@login_required
@requiere('inventario.gestionar')
@require_POST
def importar_confirmar(request, pk):
    imp = get_object_or_404(ImportacionProductos, pk=pk)
    if imp.estado != ImportacionProductos.Estado.VALIDADA:
        messages.error(request, 'Esta importación no se puede aplicar.')
        return redirect('inventario:importar_revision', pk=pk)
    # Se valida otra vez: los datos pudieron cambiar desde la revisión
    resultado = importacion.validar(bytes(imp.contenido))
    if not resultado.valido:
        imp.estado = ImportacionProductos.Estado.CON_ERRORES
        imp.errores = [list(e) for e in resultado.errores]
        imp.save(update_fields=['estado', 'errores'])
        messages.error(request, 'Aparecieron errores nuevos al revalidar. Revisa la lista.')
        return redirect('inventario:importar_revision', pk=pk)
    totales = importacion.aplicar(resultado, request.user)
    imp.estado = ImportacionProductos.Estado.APLICADA
    imp.aplicado_en = timezone.now()
    imp.resumen = {**imp.resumen, 'aplicado': totales}
    imp.contenido = b''
    imp.save(update_fields=['estado', 'aplicado_en', 'resumen', 'contenido'])
    messages.success(request, f'Importación lista: {totales["creados"]} productos nuevos, '
                              f'{totales["actualizados"]} actualizados, {totales["lotes"]} lotes iniciales.')
    return redirect('inventario:lista')
