# Estado de Ordo

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Preparación (Railway Pro, repo, venv) | Listo (falta Railway Pro) |
| 1 | Esqueleto Django y primer despliegue | Código listo, falta desplegar en staging |
| 2 | Empresas, usuarios, roles, panel Mi empresa | Código listo, 29 tests en verde |
| 3 | Catálogo, inventario, proveedores, compras | 3A lista (inventario y proveedores); falta 3B compras |
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

## Fase 3A — detalle
- [x] Categoría, Subcategoría, Marca, Unidad (unidades iniciales por empresa), Proveedor
- [x] Producto con `con_stock()` (1 consulta) y código único por empresa
- [x] Lote con CHECK en BD: sin stock negativo ni apartado mayor que la existencia
- [x] Kardex con saldo del lote en cada movimiento
- [x] `inventario/servicios.py`: ingresar, ajustar, apartar_fefo, liberar, descontar_apartado (select_for_update + F())
- [x] Pantallas: lista paginada con filtros, detalle con lotes y kardex, ingreso y ajuste con buscador, catálogo, proveedores
- [x] Vendedor ve stock y precio, NO costos; Almacén gestiona inventario y proveedores
- [x] Búsqueda con índice pg_trgm (PostgreSQL)
- [x] 54 tests en verde en SQLite y PostgreSQL 16 (incluye prueba de concurrencia real)

## Fase 3B — pendiente
- [ ] Órdenes de compra (borrador → cerrada → recepción parcial/total que genera ingresos)
- [ ] Panel de pedido (sugerido por consumo) y PDF de orden de compra con encabezado_empresa
- [ ] PDF de lista de precios
- [ ] Importación de productos desde Excel/CSV (necesaria para migrar BioLife y para nuevos clientes)
