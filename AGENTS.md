# AGENTS.md — Ordo

## Alcance

- Ordo es un SaaS multiempresa de gestión comercial para ventas, inventario, compras, proveedores, clientes, comisiones y finanzas.
- Trabaja en `C:\proyectos\ordo` o en un checkout autorizado de Ordo. Ordo, Ordo Salud y Ordo Lab son repositorios independientes. Confirma en Ordo toda suposición sobre arquitectura, datos, funcionalidades y operación. El acceso o los cambios en otros repositorios, incluido BioLifeVentas, requieren autorización específica.
- Haz cambios incrementales y conserva el trabajo preexistente. Revisa `git status --short --branch` al iniciar. Si hace falta `safe.directory`, acota la excepción al comando y a la ruta del checkout.
- Consulta el código y las pruebas del módulo. Usa [CLAUDE.md](CLAUDE.md), [ESTADO.md](docs/ESTADO.md) y [DECISIONES.md](docs/DECISIONES.md) como contexto. Si difieren del código, identifica el comportamiento efectivo y señala la discrepancia.

## Arquitectura y módulos

Ordo es una aplicación modular Django con plantillas, Bootstrap, Bootstrap Icons, HTMX y PWA. Los ajustes viven en `config/settings/{base,dev,prod}.py` y las rutas raíz en `config/urls.py`.

- `apps/core/` contiene contexto de empresa, permisos, subdominios, secuencias, PDF, PWA, consulta sin conexión, cliente Gemini y tareas programadas.
- `apps/usuarios/` y `apps/empresas/` gestionan autenticación, membresías, equipo, perfiles, plataforma y soporte.
- `apps/inventario/`, `apps/compras/` y `apps/proveedores/` gestionan catálogo, lotes, almacenes, kardex, traslados, abastecimiento y recepción.
- `apps/clientes/`, `apps/ventas/` y `apps/comisiones/` gestionan cartera, presupuestos, ventas, devoluciones, abonos, cobranza, despachos, entregas, agenda de servicios y liquidaciones.
- `apps/tasas/` gestiona tasas globales y de empresa. `apps/finanzas/` contiene el punto de equilibrio.
- `templates/` y `static/` contienen la interfaz. `tests/` contiene la suite Django. `scripts/` contiene herramientas de exportación histórica desde BioLifeVentas.

## Reglas permanentes de aislamiento y permisos

- Usa `EmpresaModel` para los modelos de negocio que pertenecen a una empresa. Limita consultas, formularios, acciones, documentos, reportes y cachés a la empresa activa. Respeta el alcance de los modelos globales y de plataforma.
- Fuera de una solicitud, establece el contexto con `usando_empresa(empresa)`. Reserva `Modelo.todos` para comandos y administración con alcance explícito. Las relaciones de modelos de empresa consultadas sin contexto pueden devolver un conjunto vacío.
- Usa `FormBootstrap` en formularios de negocio y `validar_unico_en_empresa` cuando corresponda. Conserva el filtrado de opciones por empresa y reutiliza selectores como `clientes_visibles(request)`.
- Define permisos de negocio en `PERMISOS` en `apps/core/permisos.py`. Aplica `@requiere` o `tiene_permiso` y resuelve el acceso mediante permisos y membresías.
- Conserva el inicio de sesión por nombre de usuario dentro de cada empresa, las cuentas separadas de plataforma y el modo soporte explícito. Mantén `/<slug>/` al final de las rutas raíz y revisa los slugs reservados al añadir una ruta de primer nivel. Consulta [DOMINIO.md](docs/DOMINIO.md) para cambios en subdominios o acceso por ruta.
- Cuando un cambio afecte al aislamiento, verifica con al menos dos empresas que un usuario de una no pueda consultar ni alterar recursos de la otra. Cubre las superficies afectadas mediante identificadores ajenos, URLs directas, documentos (incluidos PDF y descargas), reportes y exportaciones, peticiones HTMX y cachés. Comprueba que tampoco se filtren datos en respuestas parciales ni al cambiar de empresa o cerrar sesión.

## Reglas permanentes de integridad comercial e interfaz

- En inventario, reservas, ventas, abonos, devoluciones, correlativos, tasas y comisiones, preserva la atomicidad de las transacciones, la idempotencia frente a reintentos y la trazabilidad de los cambios según corresponda. Verifica los efectos parciales, duplicados y concurrentes cuando el flujo pueda producirlos.
- Mueve stock mediante `apps/inventario/servicios.py`. Conserva bloqueos, actualizaciones atómicas, reservas, lotes, almacenes y kardex. Usa `Producto.objects.fisicos()` en operaciones sobre stock. Los servicios se gestionan mediante su agenda y carecen de stock.
- Cambia estados de presupuestos y ventas mediante `apps/ventas/servicios.py`. Respeta los flujos de cobro y entrega, abonos, devoluciones y sus efectos sobre comisiones. Usa los servicios de compras para recepciones, `apps/core/secuencias.py` para correlativos y `tasa_vigente(empresa)` para resolver la tasa vigente cuando corresponda.
- Mantén las vistas GET libres de escrituras de negocio. Aplica permisos y aislamiento en las peticiones HTMX, descargas y acciones sobre objetos.
- Reutiliza parciales y componentes. Conserva Bootstrap, Bootstrap Icons y HTMX locales en `static/vendor/`. Mantén los archivos vendor libres de referencias `sourceMappingURL` para que funcione `collectstatic` con manifest.
- Usa `encabezado_empresa()`, `pie_empresa()` y `Paragraph` de `apps/core/pdf.py` al generar documentos. Conserva `data-pdf` en enlaces y formularios GET que abran PDF en la PWA.
- Conserva la consulta sin conexión de solo lectura, el aislamiento de su caché y el borrado al cerrar sesión.
- En la carga con IA, limita la selección al catálogo de la empresa y conserva la revisión antes de agregar ítems. Usa `IA_MODO=prueba` y datos ficticios para las pruebas.

## Desarrollo y verificación local

- Verifica el entorno virtual de Ordo antes de ejecutar Python. En PowerShell, activa `.\venv\Scripts\Activate.ps1` y comprueba el ejecutable con `python -c "import sys; print(sys.executable)"`.
- Para un entorno local autorizado, instala `requirements-dev.txt` y usa `.env.example` como plantilla inicial. Verifica la configuración y el destino de la base antes de ejecutar `migrate`, `createsuperuser` o `runserver`. Los ajustes base usan SQLite local cuando falta `DATABASE_URL` o está vacío.
- Ejecuta `python manage.py test tests` o la parte pertinente de la suite cuando esté autorizado. Usa datos ficticios y configuración aislada. Para concurrencia, bloqueos y comportamiento específico del motor, verifica también con PostgreSQL de pruebas.
- En una auditoría de solo lectura, evita importar ajustes de Django y ejecutar comandos que escriban archivos o toquen bases. Los ajustes de desarrollo crean `STATIC_ROOT` al importarse.
- Informa qué verificaste, qué queda pendiente y los supuestos que afecten al resultado.

## Datos, integraciones y migraciones

- Protege `.env`, credenciales, claves, bases, respaldos, exportaciones y datos de clientes, incluidos pedidos, documentos y firmas. Usa datos ficticios en ejemplos, pruebas y diagnósticos. Mantén datos sensibles y credenciales fuera de los registros.
- Usa integraciones simuladas o aisladas para verificar Gemini, BCV, Cloudinary, SMTP y Sentry. El acceso a servicios, secretos, bases o datos reales requiere autorización específica. WhiteNoise sirve los estáticos. Conserva `cloudinary_storage` después de `django.contrib.staticfiles` en `INSTALLED_APPS`.
- Distingue migraciones de esquema y datos de Django de la importación histórica desde BioLifeVentas. Revisa el destino, el alcance por empresa y el impacto antes de aplicar cualquiera.
- Para una importación histórica, sigue [MIGRACION_BIOLIFE.md](docs/MIGRACION_BIOLIFE.md). Usa datos ficticios o una copia aislada autorizada. `--simular` ejecuta operaciones y las revierte en una transacción. `--vaciar` elimina datos de negocio de la empresa destino y requiere autorización explícita. Conserva los números históricos y evita generar comisiones sobre ventas importadas salvo instrucción expresa.

## Referencias operativas sujetas a verificación

- La referencia al redactar este archivo es Python 3.14, Django 5.2, SQLite local y PostgreSQL con psycopg 3 para producción. Verifica `Dockerfile`, `requirements.txt`, `requirements-dev.txt` y los ajustes vigentes antes de instalar, actualizar u operar.
- La documentación describe `develop` como rama de trabajo y `main` como origen del autodespliegue a `production` en Railway, con servicios `web`, `cron` y `Postgres`. Verifica el entorno, las ramas, el autodespliegue, las migraciones y los servicios activos antes de operar. Los pasos históricos de staging sirven como referencia para reconstruir un entorno.
- Consulta [DESPLIEGUE_RAILWAY.md](docs/DESPLIEGUE_RAILWAY.md) y [DOMINIO.md](docs/DOMINIO.md) para Railway, DNS de Cloudflare, subdominios y `/salud/`. El contenedor documentado corre `collectstatic` durante el build y aplica migraciones antes de arrancar Gunicorn. El cron ejecuta `tareas_programadas` para vencer apartados y actualizar el BCV.
- Antes de aplicar migraciones grandes en producción, confirma el destino y un respaldo reciente de PostgreSQL. Ejecuta cambios de producción, despliegues, pushes, cambios de DNS o variables y acciones destructivas únicamente cuando estén autorizados.

