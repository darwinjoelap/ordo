# Paridad Ordo ↔ BioLifeVentas

Revisión del código de `C:\proyectos\biolifeventas` (01/10/2026, solo lectura).
Objetivo: que BioLife no pierda funciones al pasar a Ordo.

## A. Antes de migrar — HECHO (01/10/2026)
- [x] **Facturación fiscal por venta**: facturado, N° de factura, N° de control, fecha de facturación
      (BioLifeVentas: `Venta.facturado / numero_factura / numero_control / fecha_facturacion`)
- [x] **Reporte de facturación**: rango de fechas, solo facturadas / solo pagadas, totales, PDF
- [x] **Lote y vencimiento en el PDF del presupuesto** (lote apartado o el FEFO referencial; "SIN STOCK" si no hay)
      y marca bajo el nombre del producto
- [x] **Reportes y analítica**: KPIs (vendido, n.º de ventas, ticket promedio, utilidad solo gestión),
      ventas por mes, top productos, top clientes, por vendedor, presupuestos por estado;
      filtros fecha/vendedor/cliente/categoría/producto; el vendedor solo ve lo suyo
- [x] **Lista de ventas por rango de fechas** con total del período

## B. Importante — HECHO salvo respaldo (01/10/2026)
- [x] IVA por documento (venta sin IVA / exenta); hoy siempre toma el IVA de la empresa
- [x] Tasa manual sin entrar a `/admin/`: pantalla en Plataforma con historial y fuente (BCV / manual)
- [x] Tablero: lotes vencidos con stock, lista de stock crítico, filtros "pendiente de cobro" / "pendiente de entrega"
- [x] Reporte de inventario apartado (qué está apartado, cliente, vendedor, hasta cuándo)
- [ ] Respaldo diario de la BD (BioLifeVentas: `respaldar_bd` → Google Drive, 30 copias) — decidir en producción

## C. Menor / a decidir
- [ ] Días de apartado por presupuesto (hoy: los de la empresa)
- [ ] Eliminar presupuestos en borrador/cancelados (Ordo solo cancela: se conserva el número)
- [ ] Selector global USD/Bs en pantallas (Ordo muestra ambos)
- [ ] Proveedores: direcciones, empresas de encomienda y despachos (decidido no migrar aún)
- [x] Factor de venta automático: no hace falta, Ordo usa el consumo real de 90 días

## D. Ya cubierto en Ordo
Presupuestos con FEFO y apartado con vencimiento, pago y entrega, PDF USD/Bs/ambos, clientes, catálogo
(categoría, subcategoría, marca), ingreso y ajuste por lote, panel de pedido, órdenes de compra con recepción
parcial y cierre, lista de precios PDF, usuarios y roles, tasa BCV automática, PWA.

## E. Ordo agrega (BioLifeVentas no lo tiene)
Multiempresa, validación de ventas, comisiones y liquidaciones, devoluciones, kardex, importar/exportar Excel,
modos de precio, cartera por vendedor, rol Almacén, Mi empresa (marca en PDFs), panel de plataforma.

## Notas para la migración
- BioLifeVentas no tiene comisiones: NO ejecutar `generar_comisiones_faltantes` sobre ventas históricas
  (crearía comisiones de ventas viejas). Solo para ventas nuevas.
- Estados: CONFIRMADO → VALIDADA (BioLifeVentas no tiene paso de validación). VENCIDO/CANCELADO iguales.
- Números: BioLifeVentas usa `AAAANNNNN` (202600001); conservarlos al migrar y que la secuencia de Ordo siga después.
- En BioLifeVentas el lote está en el ítem (un ítem por lote); en Ordo es `Reserva` por ítem.
- Roles: CONTROL_TOTAL → Administrador; ADMIN → Dueño; VENDEDOR → Vendedor.
- Tasa: `TasaCambio.scraping_exitoso=False` marca días en que falló el BCV.
