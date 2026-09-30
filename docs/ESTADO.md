# Estado de Ordo

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Preparación (Railway Pro, repo, venv) | Listo (falta Railway Pro) |
| 1 | Esqueleto Django y primer despliegue | Código listo, falta desplegar en staging |
| 2 | Empresas, usuarios, roles, panel Mi empresa | Código listo, 29 tests en verde |
| 3 | Catálogo, inventario, proveedores, compras | Pendiente |
| 4 | Clientes, presupuestos, ventas, precios, validación | Pendiente |
| 5 | Comisiones | Pendiente |
| 6 | PWA iPhone, Android y web | Pendiente |
| 7 | Migración BioLife y producción | Pendiente |

## Fase 1 — detalle
- [x] Proyecto Django 5.2 con settings base/dev/prod
- [x] Usuario con login por correo
- [x] Base visual con marca Ordo (escritorio y móvil)
- [x] Healthcheck `/salud/`, Dockerfile, railway.json
- [x] 8 tests en verde; `check --deploy` sin errores
- [ ] Primer despliegue en Railway staging
- [ ] Sentry recibiendo errores

## Fase 2 — detalle
- [x] Empresa, Membresia (Dueño, Administrador, Almacén, Vendedor), PerfilEmpresa
- [x] EmpresaModel + manager que filtra por empresa activa (falla cerrado sin empresa)
- [x] Middleware de empresa activa + selector de empresa + pantalla "sin empresa"
- [x] Permisos por rol en `apps/core/permisos.py` (`@requiere(...)`, `permisos` en plantillas)
- [x] Panel Mi empresa (Identidad, Contacto, Documentos, Comercial) con vista previa en vivo
- [x] Logo PNG/JPG ≤ 2 MB, copia de 600 px para PDF, opción de quitar
- [x] `encabezado_empresa()` y `pie_empresa()` para todos los PDF + PDF de prueba
- [x] Comando `crear_empresa "Nombre" dueno@correo --password ...`
- [ ] Gestión de usuarios del equipo desde la app (invitar, cambiar rol) — pendiente, hoy desde el admin
