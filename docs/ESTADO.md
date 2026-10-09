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
| 7 | Migración BioLife y producción | Herramienta lista (docs/MIGRACION_BIOLIFE.md); falta ensayo con datos reales y producción |

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
- [x] Devoluciones total o parcial de ventas validadas (DV-AAAA-00001): ver detalle abajo

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
- [x] Modo soporte: el superusuario entra a cualquier empresa (botón Entrar o su enlace) con permisos de Dueño,
      sin membresía, sin aparecer en Equipo ni contar en el límite; banner y botón "Salir al panel"

## Login por usuario
- [x] Usuario propio de cada empresa (`maria` puede existir en dos empresas); correo opcional
- [x] Enlace `/<empresa>/` → login con usuario de esa empresa; queda recordada en el equipo (cookie)
- [x] Dirección principal y `/admin/` → solo cuentas de plataforma (superusuario `darwinjoelap`)
- [x] Migración de datos: usuario = parte del correo antes de la @; superusuarios quedan como plataforma

## Devoluciones de ventas
- [x] Desde una venta validada → "Registrar devolución" (Dueño/Administrador, permiso `ventas.devolver`)
- [x] Total o parcial por producto; "Devolver todo"; total estimado en vivo con descuento, IVA y tasa de la venta
- [x] Por línea: vuelve al stock (al mismo lote de donde salió, kardex DEVOLUCIÓN) o no vuelve (dañado/vencido)
- [x] Si se devuelve todo, la venta queda DEVUELTA; los montos cierran al centavo con la venta original
- [x] Comisión: ajuste negativo con el % congelado; nunca modifica lo liquidado o pagado, se descuenta en la
      próxima liquidación (si el saldo queda negativo, espera nuevas comisiones)
- [x] Reembolso opcional (monto, método, fecha, referencia), también registrable después
- [x] PDF "Nota de devolución" con firmas; lista Comercial → Devoluciones
- [x] Tablero y panel de pedido usan ventas netas de devoluciones
- [x] 17 tests en SQLite y PostgreSQL

## Paridad con BioLifeVentas — bloque A (ver docs/PARIDAD_BIOLIFEVENTAS.md)
- [x] Facturación por venta: N° de factura (no se repite), N° de control, fecha; corregir o quitar (permiso `ventas.facturar`)
- [x] Reporte de facturación: por fecha de venta o de factura, facturadas/sin facturar, pagadas, vendedor; PDF y Excel
- [x] PDF del presupuesto con formato BioLifeVentas: columnas Lote y F. Venc. con todos los lotes en la misma fila,
      marca, "SIN STOCK: faltan N"; en presupuestos sin apartar el reparto es FEFO referencial
- [x] El apartado FEFO ya no toma lotes vencidos
- [x] Reportes de ventas: vendido sin IVA, n.º de ventas, ticket, utilidad y margen (solo gestión), por mes,
      productos, clientes, vendedores, categorías y presupuestos por estado; filtros; el vendedor ve solo lo suyo
- [x] Lista de ventas filtrada por fechas con total neto de devoluciones
- [x] 17 tests en SQLite y PostgreSQL (201 en total)

## Paridad con BioLifeVentas — bloque B
- [x] Venta sin IVA (exenta) por documento; en el PDF sale "IVA: Exento" (modo FIJO: solo gestión)
- [x] Plataforma → Tasa BCV: historial, carga manual (reemplaza la del día) y "Consultar BCV ahora"
- [x] Empresa → Tasa del día (Dueño/Administrador): tasa propia de hoy solo para su empresa, reintentar BCV,
      volver a la del BCV; la tasa de la barra superior abre esta pantalla
- [x] Tablero: por cobrar, por entregar, lotes vencidos con stock, próximos a vencer (30 días), bajo mínimo
- [x] Lista de ventas filtrable por "sin pago" / "sin entregar"
- [x] Reportes → Apartados: por presupuesto (lotes y fecha límite) y total por producto
- [x] El disponible de inventario ya no cuenta lotes vencidos (un producto con solo lotes vencidos figura como agotado)
- [ ] Respaldo diario de la BD: se decide al preparar producción

## Panel de pedido (mejoras)
- [x] Columna "Con pedido": días que alcanza disponible + en camino + lo que se pide; se recalcula al editar la cantidad
- [x] Consumo con los días reales de historial (30 a 90) y aviso "Con vencidos" por producto
- [x] Filtros: proveedor, categoría, subcategoría (según la categoría) y marca
- [x] Script `biolifeventas_a_ordo.py`: «dias_por_unidad» calculado con ventas reales de 90 días

## Fase 7 — migración BioLifeVentas
- [x] `scripts/biolifeventas_exportar.py`: exporta TODO a JSON (solo lectura), con resumen para cuadrar
- [x] Importador (`apps/core/migracion_biolife.py`): usuarios con su clave, catálogo, proveedores, productos, lotes,
      kardex completo, clientes, presupuestos/ventas (facturación, pago, entrega, apartados), órdenes de compra, tasas
- [x] Una transacción; simulación; `--vaciar`; verificación de existencias, apartados, ventas y total vendido
- [x] Plataforma → empresa → "Migrar desde BioLifeVentas" (subir JSON, simular, guardar) y comando `importar_biolifeventas`
- [x] Probado con una copia de los modelos de BioLifeVentas y datos de prueba (13 tests)
- [ ] Ensayo con datos reales en staging
- [ ] Entorno de producción, respaldo diario y corte

## Panel de pedido por clasificación y visor de PDF (01/10/2026)
- [x] Panel de pedido: filas agrupadas por categoría › subcategoría (alfabético) con total de unidades por grupo,
      total por proveedor y tarjeta "Total por clasificación" (se recalcula al escribir cantidades)
- [x] PDF del pedido (`compras:panel_pedido_pdf`): clasificado igual, total de unidades por clasificación y general;
      usa las cantidades escritas en el panel (`?c=producto:cantidad,...`)
- [x] Visor de PDF dentro de la app (`/visor/?u=`, pdf.js en static/vendor/pdfjs): en la PWA instalada los enlaces
      `data-pdf` abren ahí, y "atrás" vuelve a la pantalla anterior en vez de cerrar la app. Compartir / Descargar
- [x] Recepción de órdenes con productos que no llegaron: verificado con pruebas (tests/test_panel_pdf.py)

## Consulta sin conexión (03/10/2026)
- [x] «Consulta rápida» (`/consulta/`): productos (precio USD/Bs, existencia, SIN STOCK) y clientes de la cartera, con buscador
- [x] Sin conexión muestra lo último guardado en el dispositivo, con fecha y aviso; se refresca sola cada 10 min al usar Ordo con internet
- [x] Se borra al cerrar sesión o si la sesión venció. La pantalla «Sin conexión» lleva a la consulta
- [ ] NO incluido (decidido): crear presupuestos sin conexión (correlativo, lotes y apartados se deciden en el servidor)
- [x] Presupuesto: muestra productos y total de unidades

## Número al guardar y venta por cobrar (04/10/2026)
- [x] El presupuesto nace SIN número; se asigna al Guardar, Emitir, Apartar o Confirmar (`servicios.asignar_numero`), y solo con productos
- [x] `servicios.eliminar`: borra un BORRADOR por completo; si tenía el último número de la serie, se libera (`liberar_numero_presupuesto`)
- [x] «Nuevo presupuesto» reutiliza el borrador vacío del mismo cliente; el cron borra borradores vacíos sin número de más de 24 h
- [x] Migración `ventas 0004_numero_al_guardar` (número opcional; único solo cuando no está vacío)
- [x] Venta confirmada/validada = «Por cobrar» hasta registrar el pago (ya era así; ahora se ve en lista y detalle, con pruebas)
- [x] Pago con banco emisor, referencia y monto recibido (USD o Bs) opcionales; muestra «Faltan/Sobran» si difiere (migración `ventas 0005_datos_del_pago`)

## Estado «Por pagar» (con validar ventas activo)
- [x] Confirmar sin pago → `POR_PAGAR`; a `POR_VALIDAR` entra SOLO con pago registrado (`registrar_pago` mueve entre ambos); entregar no cambia la bandeja
- [x] `validar` rechaza ventas sin pago; `desconfirmar` devuelve una «Por pagar» a Apartado
- [x] «Por cobrar» del inicio y filtro «Por pagar» = `POR_PAGAR` + validadas sin pago. Migración `ventas 0006_estado_por_pagar` (mueve las «Por validar» sin pago)
- [x] Se guarda quién registró el pago y cuándo (migración `ventas 0007_pago_registrado_por`)
- [x] «Nuevo presupuesto» siempre crea uno en blanco y lista los abiertos del cliente para elegir; botón «Actualizar a la tasa de hoy» en presupuestos emitidos (`servicios.actualizar_tasa`)

## Ciclo de venta unificado
- [x] Confirmar → dos flujos independientes: «Por cobrar» (`Presupuesto.por_cobrar`) y «Por entregar» (`por_entregar` = confirmada sin entregar, cualquier estado de `CONFIRMADAS`)
- [x] Una sola etiqueta financiera: «Por cobrar» en amarillo (el estado `POR_PAGAR` se muestra así); camión cuando está entregada, en cualquier estado confirmado
- [x] Un solo parcial para el estado: `templates/ventas/partials/estado.html` (lista, detalle, inicio)

- **Punto de equilibrio** (`apps/finanzas`, `/finanzas/equilibrio/`, permiso `finanzas.ver` = dueño/administrador): costos fijos por mes (`CostoFijo` con vigencia desde/hasta), deducciones % sobre venta o utilidad bruta (`Deduccion`), cálculo en `servicios.calcular` (ventas validadas sin IVA − devoluciones − costo − comisiones − deducciones, acumulado por día vs. fijos). Gráfica SVG propia.

- **Señal débil**: la Consulta rápida sirve primero lo guardado en el dispositivo y se pone al día por detrás (`datos.json?red=1`, se rinde a los 20 s) con aviso de antigüedad; las demás páginas esperan 6 s (`ESPERA` en `apps/core/pwa.py`) y muestran `/offline/` como «Señal débil» con «Seguir esperando».

- **«&» en los PDF**: `apps.core.pdf.Paragraph` escapa `&` y `<` de los datos; todos los PDF importan ese (no el de ReportLab).
- **Exento de IVA**: `Producto.exento_iva` → `ItemPresupuesto.exento_iva` (copia al agregar) y `Presupuesto.exento_usd`; `models.partir_iva()` calcula IVA solo sobre la base imponible (USD, Bs y devoluciones). PDF y pantalla marcan (E) y separan Exento / Base imponible.
- **Nota de despacho**: `ventas.Despacho` (1 por presupuesto, mismo número), `/ventas/<pk>/despacho/` y `/despacho/pdf/`, `servicios.guardar_despacho`; desde APARTADO en adelante. Documento no fiscal.

- **Importar clientes por Excel**: `apps/clientes/importacion.py` (plantilla, validar, aplicar, exportar), `views_importacion.py`, `/clientes/importar/`, permiso `clientes.importar` (dueño/administrador). Coincide por RIF y, sin RIF, por nombre normalizado; actualiza sin borrar datos.
- **Ocultar SIN STOCK en PDF**: `PerfilEmpresa.ocultar_sin_stock` (Mi empresa → Documentos).

- **Pagos parciales (abonos)**: `ventas.Abono` (moneda, tasa, monto_usd, quién); `Presupuesto.abonado_usd`, `saldo_usd`, `abono_parcial`. `servicios.registrar_abono` / `anular_abono` / `_actualizar_cobro` (pagado = abonos cubren el neto, ±0,01). `registrar_pago` queda como atajo (abona todo el saldo / anula todo). Migración 0010 convierte cada venta pagada en un abono por el total. La comisión con «requiere pago» espera al pago COMPLETO.
- **Estado de cuenta del cliente**: `apps/clientes/estado_cuenta.py` (FILTROS, PDF horizontal, Excel), ficha del cliente con filtros y rango de fechas.
