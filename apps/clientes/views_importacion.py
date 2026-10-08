from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere

from . import importacion
from .models import Cliente, ImportacionClientes

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
E = ImportacionClientes.Estado


def _descarga(contenido, nombre):
    r = HttpResponse(contenido, content_type=XLSX)
    r['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return r


@login_required
@requiere('clientes.importar')
def plantilla(request):
    vendedores = [(u.username, u.nombre_visible) for u in get_user_model().objects.filter(
        membresias__empresa=request.empresa, membresias__activa=True).order_by('username')]
    return _descarga(importacion.generar_plantilla(vendedores), 'plantilla-clientes-ordo.xlsx')


@login_required
@requiere('clientes.importar')
def exportar(request):
    fecha = timezone.localdate().strftime('%Y%m%d')
    return _descarga(importacion.exportar_clientes(Cliente.objects.select_related('vendedor').order_by('nombre')),
                     f'clientes-{request.empresa.slug}-{fecha}.xlsx')


@login_required
@requiere('clientes.importar')
def importar(request):
    if request.method == 'POST':
        archivo = request.FILES.get('archivo')
        problema = None
        if not archivo:
            problema = 'Elige un archivo .xlsx.'
        elif not archivo.name.lower().endswith('.xlsx'):
            problema = 'El archivo debe ser Excel .xlsx (si lo tienes en .xls o .csv, ábrelo y guárdalo como .xlsx).'
        elif archivo.size > importacion.MAX_BYTES:
            problema = 'El archivo supera 5 MB.'
        if not problema:
            contenido = archivo.read()
            try:
                resultado = importacion.validar(contenido, request.empresa)
            except importacion.ErrorArchivo as e:
                problema = str(e)
        if problema:
            messages.error(request, problema)
            return redirect('clientes:importar')
        imp = ImportacionClientes.objects.create(
            nombre_archivo=archivo.name[:200], contenido=contenido, usuario=request.user,
            estado=E.VALIDADA if resultado.valido else E.CON_ERRORES, resumen=resultado.resumen(),
            errores=[list(e) for e in resultado.errores], avisos=[list(a) for a in resultado.avisos])
        return redirect('clientes:importar_revision', pk=imp.pk)
    return render(request, 'clientes/importar.html', {
        'titulo': 'Importar clientes', 'columnas': importacion.COLUMNAS, 'reglas': importacion.REGLAS,
        'historial': ImportacionClientes.objects.select_related('usuario').defer('contenido')[:10],
    })


@login_required
@requiere('clientes.importar')
def importar_revision(request, pk):
    imp = get_object_or_404(ImportacionClientes.objects.defer('contenido'), pk=pk)
    return render(request, 'clientes/importar_revision.html', {
        'titulo': 'Revisión de importación', 'imp': imp, 'r': imp.resumen,
        'errores': imp.errores[:500], 'avisos': imp.avisos[:300],
    })


@login_required
@requiere('clientes.importar')
@require_POST
def importar_confirmar(request, pk):
    imp = get_object_or_404(ImportacionClientes, pk=pk)
    if imp.estado != E.VALIDADA:
        messages.error(request, 'Esta importación no se puede aplicar.')
        return redirect('clientes:importar_revision', pk=pk)
    resultado = importacion.validar(bytes(imp.contenido), request.empresa)     # los datos pudieron cambiar
    if not resultado.valido:
        imp.estado = E.CON_ERRORES
        imp.errores = [list(e) for e in resultado.errores]
        imp.save(update_fields=['estado', 'errores'])
        messages.error(request, 'Aparecieron errores nuevos al revalidar. Revisa la lista.')
        return redirect('clientes:importar_revision', pk=pk)
    totales = importacion.aplicar(resultado)
    imp.estado, imp.aplicado_en, imp.contenido = E.APLICADA, timezone.now(), b''
    imp.resumen = {**imp.resumen, 'aplicado': totales}
    imp.save(update_fields=['estado', 'aplicado_en', 'resumen', 'contenido'])
    messages.success(request, f'Importación lista: {totales["creados"]} clientes nuevos y {totales["actualizados"]} actualizados.')
    return redirect('clientes:lista')
