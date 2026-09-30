from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


@login_required
def inicio(request):
    """Tablero inicial. Se llena en las fases 3 a 5."""
    return render(request, 'core/inicio.html', {'titulo': 'Inicio'})


@never_cache
def salud(request):
    """Healthcheck para Railway: responde 200 si la app y la BD están vivas."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'estado': 'ok'})
    except Exception:  # pragma: no cover - solo falla con la BD caída
        return JsonResponse({'estado': 'error'}, status=503)
