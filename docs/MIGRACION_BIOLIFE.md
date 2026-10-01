# Migración BioLifeVentas → Ordo (Fase 7)

Dos piezas:
1. `scripts/biolifeventas_exportar.py` — se ejecuta DESDE BioLifeVentas. Solo lee. Genera `biolifeventas_export.json`.
2. Ordo → Plataforma → (empresa) → **Migrar desde BioLifeVentas** — sube el JSON, **Simular**, revisa, **Migrar y guardar**.
   (Alternativa por consola: `python manage.py importar_biolifeventas archivo.json --empresa biolife [--simular] [--vaciar]`.)

Todo entra en UNA transacción: si algo falla no queda nada a medias.

## Qué se migra
| BioLifeVentas | Ordo |
|---|---|
| Usuarios (ADMIN / CONTROL_TOTAL / VENDEDOR) | Dueño / Administrador / Vendedor, **misma contraseña**; inactivos quedan inactivos |
| Categorías, subcategorías, marcas | Igual |
| Proveedores + direcciones | Proveedor con la dirección principal; las demás en Notas |
| Productos (unidad VIAL, FRASCO→FCO…) | Igual; «días por unidad» calculado con ventas reales de 90 días |
| Lotes | Igual (existencia, apartado, costo, vencimiento, fecha de ingreso) |
| Kardex completo | Igual, con sus fechas; saldos recalculados desde la existencia actual |
| Clientes | Igual; vendedor = el que más le vendió; "vendedores ven todos los clientes" activado |
| Presupuestos (todos los estados) | Mismo número (202600001…). CONFIRMADO → venta VALIDADA. Los nuevos siguen ese correlativo |
| Venta: pago, método, factura, N° control | En la misma venta |
| Ítems partidos por lote | Una línea por producto + reservas por lote |
| Órdenes de compra | BORRADOR → Borrador; CERRADA → Enviada / Parcial / Recibida según lo recibido |
| Tasas BCV | Solo las fechas que falten en Ordo, como tasa propia de la empresa |
| — | **No** se generan comisiones de ventas antiguas |

No se migran: empresas de encomienda y despachos de proveedores.

## Ensayo en STAGING (hacerlo antes de producción)
1. **Exportar** (BioLifeVentas sigue funcionando normal):
   - Railway → proyecto BioLifeVentas → Postgres → Settings → Networking → **TCP Proxy: activar** (temporal).
   - Variables del Postgres → copia `DATABASE_PUBLIC_URL` (no la pegues en chats).
   ```powershell
   cd C:\proyectos\biolifeventas
   .\.venv\Scripts\Activate.ps1
   $env:DATABASE_URL = "<DATABASE_PUBLIC_URL>"
   python manage.py shell -c "exec(open(r'C:\proyectos\ordo\scripts\biolifeventas_exportar.py', encoding='utf-8').read())"
   Remove-Item Env:DATABASE_URL
   ```
   - Railway → Postgres de BioLifeVentas → **TCP Proxy: eliminar**. (Buen momento para rotar su contraseña.)
2. **Importar en staging**: `https://ordo-staging.up.railway.app/cuenta/entrar/` (darwinjoelap) → Plataforma → BioLife →
   **Migrar desde BioLifeVentas** → subir el JSON → **Simular**.
   - Si la empresa ya tiene datos de prueba, marca "Borrar esos datos y reemplazarlos".
   - Todas las filas deben decir ✓. Lee los avisos.
3. **Migrar y guardar**. Luego revisar en `/biolife/` con un usuario real:
   - [ ] Entrar con usuario y clave de BioLifeVentas
   - [ ] Inventario: existencia por producto y lotes = BioLifeVentas
   - [ ] Una venta antigua: PDF, factura, pago
   - [ ] Un apartado vigente: lotes y fecha límite
   - [ ] Reportes del mes y Reporte de facturación vs. BioLifeVentas
   - [ ] Panel de pedido: consumo "según ventas"
4. Borra el `.json` de tu equipo.

## Corte a PRODUCCIÓN (cuando el ensayo esté bien)
1. Avisar al equipo una hora sin ventas. Dejar BioLifeVentas sin uso (no registrar nada más).
2. Exportar de nuevo (paso 1) — con los datos al minuto.
3. Importar en la empresa de **producción** (Simular → Migrar y guardar).
4. Verificar (paso 3). Entregar el enlace `/biolife/` al equipo.
5. BioLifeVentas queda de consulta unas semanas; luego se apaga.
