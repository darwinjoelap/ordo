# Decisiones de Ordo

| Fecha | Decisión | Motivo |
| --- | --- | --- |
| 2026-09-30 | Ordo desde cero en repo propio; BioLifeVentas solo como referencia | No poner en riesgo el sistema en producción |
| 2026-09-30 | Multiempresa con esquema compartido (campo `empresa`) | Simple, una sola BD en Railway |
| 2026-09-30 | Python 3.14 local y en Docker | Es la versión instalada en el equipo de desarrollo; Django 5.2 la soporta |
| 2026-09-30 | ~~Login por correo~~ → reemplazado (ver abajo); rol en la membresía usuario↔empresa | — |
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
| 2026-09-30 | Comisión sobre base sin IVA y después del descuento | El IVA no es ingreso de la empresa |
| 2026-09-30 | % por vendedor con excepción por categoría; se congela en cada línea | Cambiar % no altera comisiones pasadas |
| 2026-09-30 | Liquidación por período; anular solo si no está pagada y se conserva el número | Trazabilidad de pagos a vendedores |
| 2026-09-30 | PWA "online-first": sin caché de páginas ni modo offline de datos | Stock y precios deben ser actuales; evita mostrar datos de otra empresa/usuario |
| 2026-09-30 | Alta de personas con contraseña temporal visible una sola vez y cambio obligatorio al entrar | No depende de correo saliente; la clave no queda guardada en ningún lado |
| 2026-09-30 | Restablecer contraseña de otro solo si pertenece únicamente a esa empresa | Un admin de una empresa no puede tomar cuentas que también usan otras empresas |
| 2026-09-30 | Enlace por empresa como ruta `/<enlace>/` (subdominios más adelante, con dominio propio) | Funciona hoy en Railway sin DNS comodín |
| 2026-09-30 | Razón social y RIF controlados por la plataforma | Datos fiscales verificados por Ordo; el cliente no los altera |
| 2026-09-30 | Superusuario = soporte de Ordo: entra a cualquier empresa con membresía virtual (no guardada) | Control total sin mezclarse con los usuarios del cliente; queda en el log `apps.plataforma` |
| 2026-09-30 | Login por nombre de usuario, único por empresa; correo opcional | Como BioLifeVentas; cada empresa administra sus usuarios. Se entra por el enlace de la empresa; la dirección principal es solo para cuentas de plataforma |
| 2026-10-01 | Devolución como documento propio (DV), total o parcial; la venta queda DEVUELTA solo si se devuelve todo | Trazabilidad: la venta original no se edita; caso real de devoluciones parciales |
| 2026-10-01 | Lo devuelto vuelve al mismo lote de donde salió; el usuario marca por línea si no vuelve (dañado/vencido) | Kardex y vencimientos correctos sin pasos extra |
| 2026-10-01 | Devolución de comisión como ajuste negativo, nunca editando liquidaciones | Lo pagado no cambia; se descuenta en la próxima liquidación |
| 2026-10-01 | Montos de la devolución con precio, descuento, IVA y tasa de la venta; la última cierra al centavo | La suma de devoluciones nunca difiere del total de la venta |
| 2026-10-01 | La factura fiscal se emite fuera de Ordo; Ordo guarda N° factura/control/fecha y no permite repetir el número | Igual que BioLifeVentas; base para el libro de ventas |
| 2026-10-01 | Lotes en el PDF dentro de la misma fila del producto, una línea por lote | Pedido de BioLife: un renglón por producto aunque salga de varios lotes |
| 2026-10-01 | Un lote vencido nunca se aparta ni se ofrece en el PDF | FEFO tomaba primero el vencido (vence antes) |
| 2026-10-01 | Analítica en montos sin IVA, después del descuento y neta de devoluciones; por fecha de validación | Lo que realmente ingresa; coherente con comisiones |
| 2026-10-01 | PDF del presupuesto con el formato de BioLifeVentas (caja de cliente, columnas Lote y F. Venc., total de unidades); varios lotes en la misma celda con su cantidad entre paréntesis | Preferencia de BioLife; un renglón por producto |
| 2026-10-01 | Montos en Bs: precio unitario en Bs redondeado primero y totales desde esos precios (`desglose_bs`) | Igual que BioLifeVentas: la tabla y los totales en Bs cuadran al céntimo |
| 2026-10-01 | Venta exenta = IVA 0 % en el documento; el vendedor la marca salvo en modo de precio FIJO | Como BioLifeVentas (`incluye_iva`), respetando el control de precios |
| 2026-10-01 | Tasa manual solo desde Plataforma (superusuario) | La tasa es global; una empresa no debe cambiarla para todas |
| 2026-10-01 | Disponible = existencia − apartado − libre en lotes vencidos | Lo vencido no se puede vender; alertas y panel de pedido quedan correctos |
| 2026-10-01 | Cada empresa puede cargar su propia tasa del día (TasaEmpresa); se usa la más reciente entre la global y la propia, y la propia gana el mismo día | El tenant no depende de la plataforma si el BCV falla, y un error suyo no afecta a otras empresas |
