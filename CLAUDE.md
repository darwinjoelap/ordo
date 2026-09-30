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
- `apps/usuarios` — Usuario con login por CORREO (sin username). El rol vive en la membresía (Fase 2)
- `templates/` — base.html (barra superior, menú lateral, barra inferior móvil)
- `static/img/marca/` — logo Ordo e iconos PWA
- `tests/` — `python manage.py test tests`
- `docs/ESTADO.md`, `docs/DECISIONES.md` — estado por fase y decisiones

## Reglas
- Todo modelo de negocio heredará de `EmpresaModel` (Fase 2): nunca consultas sin empresa.
- Movimientos de stock solo vía servicios con `select_for_update()` (Fase 3).
- Nada de escrituras en vistas GET.
- `cloudinary_storage` va DESPUÉS de `django.contrib.staticfiles` en INSTALLED_APPS.
- Los .js/.css de vendor no llevan `sourceMappingURL` (rompe collectstatic con manifest).
