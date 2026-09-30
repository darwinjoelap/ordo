# Estado de Ordo

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Preparación (Railway Pro, repo, venv) | Listo (falta Railway Pro) |
| 1 | Esqueleto Django y primer despliegue | Código listo, falta desplegar en staging |
| 2 | Empresas, usuarios, roles, panel Mi empresa | Código listo, 29 tests en verde |
| 3 | Catálogo, inventario, proveedores, compras | Código listo (3A + 3B), 79 tests en verde |
| 4 | Clientes, presupuestos, ventas, precios, validación | Código listo, 111 tests en verde |
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

## Fase 3B — detalle
- [x] Importación de productos desde Excel: plantilla descargable (Productos + Instrucciones + Unidades),
      validación completa sin guardar, revisión con errores por fila, confirmación en una transacción, historial
- [x] Varios lotes por producto repitiendo el código; productos existentes se actualizan sin tocar stock
- [x] Exportar productos en el mismo formato (editar en Excel y reimportar)
- [x] `scripts/biolifeventas_a_ordo.py`: exporta productos y lotes de BioLifeVentas al formato de la plantilla (solo lectura)
- [x] Órdenes de compra: borrador → enviada → parcial/recibida · anulada; recepción parcial crea lotes y kardex
- [x] Numeración por empresa sin carreras (`core.Secuencia`): OC-2026-00001
- [x] Panel de pedido: consumo real (ventas 90 días) o estimado, descuenta lo que ya está en camino, crea la orden
- [x] PDF de orden de compra (con/sin costos) y PDF de lista de precios, ambos con encabezado_empresa
- [x] Lista de precios en Bs (Fase 4)

## Fase 4 — detalle
- [x] Tasa BCV única para todas las empresas: `actualizar_tasa_bcv` (lee bcv.org.ve), carga manual en el admin,
      caché de 5 min, indicador en la barra superior (amarillo si no es de hoy)
- [x] Clientes con vendedor asignado; el vendedor ve solo los suyos (opción en Mi empresa → Comercial para que vean todos)
- [x] Presupuestos: borrador → emitido → apartado → por validar → venta validada · rechazada · vencido · cancelado
- [x] Tasa congelada al emitir; totales guardados (subtotal, descuento, IVA, total USD y Bs)
- [x] Modos de precio: FIJO (vendedor no cambia), LIBRE, RANGO (costo + margen mín/máx; fuera de rango se marca para revisión)
- [x] Apartado FEFO todo-o-nada con días configurables; vencimiento automático (`tareas_programadas`)
- [x] Validación por el administrador: descuenta stock y emite la señal `venta_validada` (gancho para comisiones)
- [x] Si la empresa no exige validación, confirmar valida directo
- [x] Rechazo con motivo: vuelve a apartado o libera stock
- [x] Pago (método y fecha) y entrega
- [x] PDF de presupuesto / nota de venta en USD, Bs o ambos
- [x] Tablero de inicio: ventas validadas del mes, por validar, apartados, bajo mínimo, actividad, apartados por vencer
- [ ] Servicio Cron en Railway: `python manage.py tareas_programadas` (ej. `0 11 * * *` UTC = 7:00 Venezuela)
