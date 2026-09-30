# Estado de Ordo

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Preparación (Railway Pro, repo, venv) | Listo (falta Railway Pro) |
| 1 | Esqueleto Django y primer despliegue | Código listo, falta desplegar en staging |
| 2 | Empresas, usuarios, roles, panel Mi empresa | Código listo, 29 tests en verde |
| 3 | Catálogo, inventario, proveedores, compras | Código listo (3A + 3B), 79 tests en verde |
| 4 | Clientes, presupuestos, ventas, precios, validación | Código listo y en develop |
| 5 | Comisiones | Código listo y en develop |
| 6 | PWA iPhone, Android y web | Código listo y en develop |
| 7 | Migración BioLife y producción | En curso: staging (guía en docs/DESPLIEGUE_RAILWAY.md) |

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
- [x] Gestión del equipo desde la app (Empresa → Equipo): agregar, rol, desactivar, contraseña temporal
- [x] Mi perfil: nombre, apellido, teléfono y cambio de contraseña (obligatorio si es temporal)

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

## Fase 5 — detalle
- [x] % por vendedor + excepción por categoría (la categoría manda); pantalla Porcentajes
- [x] Base: venta sin IVA, después del descuento; % congelado por línea al validar
- [x] Comisión automática al validar la venta (señal `venta_validada`)
- [x] Opción de empresa "la comisión exige venta cobrada" (Mi empresa → Comercial)
- [x] Liquidación por vendedor hasta una fecha, número LQ-AAAA-00001, PDF con firmas, pago con método/referencia, anulación (si no está pagada)
- [x] Vendedor: "Mis comisiones" por mes y sus liquidaciones; tarjeta "Mi comisión del mes" en Inicio
- [x] Comando `generar_comisiones_faltantes` (para ventas migradas de BioLifeVentas)
- [ ] Devoluciones / anulación de ventas validadas (no existe aún: hoy una venta validada no se revierte)

## Fase 6 — detalle
- [x] `/manifest.webmanifest` (standalone, iconos 192/512/maskable, accesos directos Presupuesto e Inventario)
- [x] `/sw.js` en la raíz: precarga estáticos; estáticos desde caché; páginas SIEMPRE desde la red
      (no se guarda HTML: datos por empresa/usuario); sin conexión → `/offline/`. Caché versionada por commit
- [x] Aviso "Instala Ordo": botón nativo en Android/Chrome/Edge; instrucciones en iPhone (Safari); se descarta 30 días
- [x] Indicador "Sin conexión"; guía `/instalar/` (menú de cuenta, se oculta en la app instalada)
- [x] Probado en Chromium: service worker activo y página sin conexión al caer el servidor
- [ ] Probar instalación real en iPhone y Android (requiere HTTPS: staging en Railway)

## Panel de plataforma (superusuario)
- [x] `/plataforma/`: lista de empresas con enlace, plan, vencimiento, usuarios activos/límite y estado
- [x] Alta de empresa: nombre comercial, razón social, RIF, enlace, plan, vencimiento, límite de usuarios
      y Dueño (con contraseña temporal si es nuevo)
- [x] Edición y suspensión (bloquea el acceso de todo el equipo sin borrar datos)
- [x] Enlace propio `/<enlace>/`: login con la marca de la empresa y la deja elegida
- [x] Razón social y RIF solo se editan desde la plataforma (en Mi empresa quedan de solo lectura)
- [x] Aviso al Dueño/Administrador 7 días antes del vencimiento; límite de usuarios aplicado en Equipo
