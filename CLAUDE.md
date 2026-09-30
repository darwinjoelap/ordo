# Ordo — Contexto de sesión

## Qué es
SaaS multiempresa de gestión comercial (ventas, inventario, compras, proveedores,
clientes, comisiones). Construido desde cero reutilizando lógica de BioLifeVentas
(`C:\proyectos\biolifeventas`, NO se modifica desde este proyecto).

## Stack
- Python 3.14 · Django 5.2 LTS · PostgreSQL (psycopg 3)
- Bootstrap 5.3 + Bootstrap Icons + HTMX 2 servidos localmente (static/vendor, sin CDN)
- WhiteNoise (estáticos) · Cloudinary (media) · ReportLab (PDF) · Sentry
- Railway Pro: entornos `staging` (rama develop) y `production` (rama main)

## Arranque local (PowerShell)
```powershell
cd C:\proyectos\ordo
.\venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"   # debe ser ...\ordo\venv\...
pip install -r requirements-dev.txt
copy .env.example .env      # solo la primera vez
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Estructura
- `config/settings/{base,dev,prod}.py` — dev por defecto en manage.py; prod en wsgi/Railway
- `apps/core` — inicio, healthcheck `/salud/`, utilidades comunes
- `apps/usuarios` — Usuario con login por CORREO (sin username). El rol vive en la membresía
- `apps/empresas` — Empresa, Membresia (rol), PerfilEmpresa (marca y datos para documentos), panel Mi empresa
- `apps/empresas/equipo.py` — reglas del equipo (agregar, rol, desactivar, clave temporal); `apps/usuarios` → Mi perfil y middleware de cambio de clave obligatorio
- `apps/core/tenancy.py` — EmpresaModel, empresa activa (`usando_empresa()` en comandos/tests)
- `apps/core/permisos.py` — tabla rol → acciones; `@requiere('codigo')`
- `apps/core/pdf.py` — `encabezado_empresa()` y `pie_empresa()` para TODOS los PDF
- `apps/core/forms.py` — `FormBootstrap` (OBLIGATORIO en formularios: rehace querysets por empresa) y `validar_unico_en_empresa`
- `apps/inventario` — catálogo, productos (`con_stock()`), lotes, kardex; `servicios.py` es el ÚNICO que mueve stock
- `apps/inventario/importacion.py` — columnas de la plantilla Excel (COLUMNAS es la única fuente), validar/aplicar
- `apps/proveedores` — proveedores
- `apps/tasas` — TasaCambio (global, sin empresa), `tasa_vigente()` cacheada, `actualizar_tasa_bcv`
- `apps/clientes` — Cliente con vendedor; `clientes_visibles(request)` aplica la regla de cartera
- `apps/ventas` — Presupuesto (también es la venta), ítems, Reserva por lote; `servicios.py` tiene TODO el flujo
  de estados y emite `venta_validada`; `pdf.py` presupuesto en USD/Bs
- `apps/comisiones` — % por vendedor/categoría, Comision (1 por venta validada, vía señal), Liquidacion; `servicios.py`
- `apps/core/management/commands/tareas_programadas.py` — cron diario (vence apartados + tasa BCV)
- `apps/compras` — órdenes de compra, recepción (`servicios.py`), panel de pedido (`sugerencias.py`), PDF
- `apps/core/secuencias.py` — `siguiente_numero('OC')` correlativos por empresa
- `scripts/biolifeventas_a_ordo.py` — exporta BioLifeVentas a la plantilla (se ejecuta DESDE biolifeventas)
- `apps/core/pwa.py` — manifest, service worker (`/sw.js`), `/offline/`, `/instalar/`; `static/js/pwa.js` registra y muestra el aviso de instalación
- `templates/` — base.html (barra superior, menú lateral, barra inferior móvil)
- `static/img/marca/` — logo Ordo e iconos PWA
- `tests/` — `python manage.py test tests`
- `docs/ESTADO.md`, `docs/DECISIONES.md` — estado por fase y decisiones

## Reglas
- Todo modelo de negocio hereda de `EmpresaModel`: nunca consultas sin empresa; `todos` solo en comandos/admin.
- Permisos nuevos se agregan en `PERMISOS` (apps/core/permisos.py), nunca `if rol == ...` en vistas.
- Movimientos de stock solo vía `apps/inventario/servicios.py` (select_for_update + F()).
- Tests también en PostgreSQL: `$env:DATABASE_URL="postgres://..."; python manage.py test tests`
- Nada de escrituras en vistas GET.
- Cambios de estado de presupuestos/ventas solo vía `apps/ventas/servicios.py`.
- Fuera de un request (tests, comandos) `obj.relacion.all()` de modelos de empresa devuelve vacío: usa `usando_empresa(e)` o `Modelo.todos`.
- `cloudinary_storage` va DESPUÉS de `django.contrib.staticfiles` en INSTALLED_APPS.
- Los .js/.css de vendor no llevan `sourceMappingURL` (rompe collectstatic con manifest).
