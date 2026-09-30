# Estado de Ordo

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Preparación (Railway Pro, repo, venv) | En curso |
| 1 | Esqueleto Django y primer despliegue | Código listo, falta desplegar en staging |
| 2 | Empresas, usuarios, roles, panel Mi empresa | Pendiente |
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
