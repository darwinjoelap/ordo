# Decisiones de Ordo

| Fecha | Decisión | Motivo |
| --- | --- | --- |
| 2026-09-30 | Ordo desde cero en repo propio; BioLifeVentas solo como referencia | No poner en riesgo el sistema en producción |
| 2026-09-30 | Multiempresa con esquema compartido (campo `empresa`) | Simple, una sola BD en Railway |
| 2026-09-30 | Python 3.14 local y en Docker | Es la versión instalada en el equipo de desarrollo; Django 5.2 la soporta |
| 2026-09-30 | Login por correo; rol en la membresía usuario↔empresa | Un usuario puede tener roles distintos en varias empresas |
| 2026-09-30 | Bootstrap/HTMX servidos localmente | La PWA debe cargar sin depender de CDN |
| 2026-09-30 | Railway Pro con entornos staging y production | Logs de 30 días, soporte, respaldos |
| 2026-09-30 | `EmpresaModel.objects` devuelve vacío si no hay empresa activa; `todos` para uso interno | Evita fugas de datos por olvido de filtro |
| 2026-09-30 | Logo solo PNG/JPG ≤ 2 MB, con copia de 600 px para PDF | ReportLab no dibuja SVG; PDFs livianos |
| 2026-09-30 | Alta de empresas por admin o comando `crear_empresa` | El registro público queda para después de la v1.0 |
| 2026-09-30 | Formularios de Ordo heredan `FormBootstrap`, que rehace querysets FK por request | Django arma esos querysets al importar, sin empresa activa, y quedaban vacíos |
| 2026-09-30 | Unidades de medida por empresa en tabla propia | Ordo no es solo para laboratorios |
| 2026-09-30 | Proveedor habitual opcional; direcciones/encomiendas de BioLifeVentas no se migran aún | Simplificar; se evalúa en Fase 3B |
| 2026-09-30 | Stock nunca se toca fuera de `inventario/servicios.py`; admin de lotes en solo lectura | Kardex íntegro y sin carreras |
| 2026-09-30 | Importación solo .xlsx, validación total antes de guardar ("todo o nada") | Evita cargas a medias; el usuario corrige y reintenta |
| 2026-09-30 | La importación no modifica stock de productos existentes | Re-importar el mismo archivo no duplica existencias |
| 2026-09-30 | Los related managers de modelos de empresa también filtran por empresa activa | Consistencia; fuera de un request usar `usando_empresa()` o `Modelo.todos` |
| 2026-09-30 | El stock se descuenta al VALIDAR; al confirmar queda apartado | Solo las ventas validadas cuentan; el rechazo no deja kardex sucio |
| 2026-09-30 | Presupuesto y venta son el mismo documento (estados) | Sin duplicar ítems; trazabilidad completa |
| 2026-09-30 | Tasa BCV global (no por empresa), congelada en cada documento al emitir | Es un dato oficial único; el documento no cambia si cambia la tasa |
| 2026-09-30 | Modo RANGO no bloquea: marca `requiere_revision` y lo ve quien valida | El vendedor no se traba con el cliente enfrente; el control queda en la validación |
| 2026-09-30 | El vendedor puede crear clientes y ve solo los suyos (configurable) | Cartera propia por vendedor, como en BioLifeVentas |
| 2026-09-30 | Señal `venta_validada` como gancho para comisiones | La Fase 5 se engancha sin tocar el flujo de ventas |
