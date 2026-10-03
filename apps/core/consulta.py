"""
Consulta rápida (funciona sin conexión): catálogo con precio y existencia, y clientes, SOLO LECTURA.

- /consulta/            pantalla sin datos del usuario en el HTML (el service worker la guarda).
- /consulta/datos.json  los datos de la empresa activa; el service worker guarda la última respuesta.
Sin conexión se muestra lo último guardado en ese dispositivo, con su fecha. Nada se edita aquí:
presupuestos, apartados y stock se siguen decidiendo en el servidor.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.core.permisos import requiere, tiene_permiso


@login_required
@requiere('inventario.ver')
def consulta(request):
    return render(request, 'core/consulta.html', {'titulo': 'Consulta rápida'})


@never_cache
@login_required
@requiere('inventario.ver')
def consulta_datos(request):
    from apps.clientes.permisos import clientes_visibles
    from apps.inventario.models import Producto
    from apps.tasas.servicios import tasa_vigente

    empresa = request.empresa
    productos = [{
        'c': p.codigo, 'n': p.nombre, 'p': str(p.precio_venta_usd), 'd': p.stock_disponible,
        'u': p.unidad.abreviatura, 'g': p.categoria.nombre, 'm': p.marca.nombre if p.marca_id else '',
    } for p in Producto.objects.filter(activo=True).con_stock().select_related('unidad', 'categoria', 'marca')
        .order_by('nombre')]
    clientes = []
    if tiene_permiso(request, 'clientes.gestionar'):
        clientes = [{'n': c.nombre, 'r': c.rif, 't': c.telefono, 'k': c.contacto, 'd': c.direccion}
                    for c in clientes_visibles(request).filter(activo=True).order_by('nombre')]
    tasa = tasa_vigente(empresa)
    return JsonResponse({
        'empresa': empresa.perfil.nombre_comercial or empresa.nombre,
        'generado': timezone.now().isoformat(),
        'tasa': {'bs': str(tasa.bs_por_usd), 'fecha': tasa.fecha.isoformat()} if tasa else None,
        'productos': productos, 'clientes': clientes,
    })
