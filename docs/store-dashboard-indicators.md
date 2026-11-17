# Indicadores comerciales y de inventario

El Panel de Tienda incluye siete indicadores adicionales y su detalle en el PDF.

## Activación

Después de actualizar el código, ejecutar desde el bench:

```sh
bench --site nombre-del-sitio migrate
bench build --app retail_tools
bench --site nombre-del-sitio clear-cache
bench restart
```

Repetir `migrate` y `clear-cache` en cada sitio actualizado. La migración crea los nuevos DocTypes; no basta con `git pull`. No se agrega ninguna regla Custom DocPerm ni se modifica la asignación de roles de usuarios.

## Configuración por empresa

En la sección de indicadores, **Configurar gastos y metas** abre **Retail Indicator Settings**. Crear un registro por empresa. Pueden administrarlo System Manager, Accounts Manager, RT Contador y RT Administrador de Sistema, sujetos a sus permisos por empresa.

1. **Cargar cuentas de gastos** incorpora las cuentas de detalle de la empresa y conserva las clasificaciones existentes.
2. Clasificar alquiler, salarios y otros gastos según su comportamiento real: **Fijo**, **Variable**, **Costo de ventas** o **Excluido**. Costo de ventas se resta una sola vez. La clasificación automática solo reconoce cuentas de tipo Cost of Goods Sold. Las cuentas con movimiento sin clasificar dejan pendiente el punto de equilibrio.
3. Ajustar los días de inactividad (60 por defecto) y de demanda reciente (30 por defecto).
4. Registrar metas saludables y límites moderados para cualquiera de los 20 indicadores. La columna **Criterio** indica si la meta es un mínimo, un máximo o un intervalo. Sin una meta personalizada, los 13 indicadores anteriores conservan sus reglas y referencias actuales; los nuevos quedan neutrales. El punto de equilibrio conserva su comparación contra ventas si no se configura una meta de cobertura.

Las metas de **ROA, ROE, rotación de inventario y GMROI** se introducen en base anual. Para conservar los umbrales originales: ROA 36.5% (moderado 0%), ROE 60.833333% (moderado 0%) y rotación 6.083333 veces (moderado 1.825 veces). La tabla y DuPont convierten meta y resultado a la misma base al cambiar el selector.

**Ticket promedio y UPT** tienen metas separadas; el semáforo de su fila conjunta muestra el peor estado entre las metas configuradas. **DIO** acepta un mínimo saludable además de la meta máxima y del máximo moderado. La **cobertura del punto de equilibrio** usa ventas / punto de equilibrio × 100; 100% representa cubrir los gastos y puede configurarse un margen de seguridad mayor. Si el punto de equilibrio es cero, se mantiene el estado cubierto sin dividir por cero.

## Bases de cálculo

| Indicador | Base |
| --- | --- |
| GMROI | Utilidad bruta comercial de artículos de stock / media de los saldos diarios de inventario al costo. Usa el costo comercial del dashboard (tasa de entrada o valoración de respaldo). Excluye servicios. Sin historial, inventario promedio positivo o costo disponible, muestra N/A. |
| Capital estancado | Valor positivo del stock sin ventas durante los días configurados / valor positivo total del stock. Un artículo nunca vendido espera ese plazo desde su primera entrada. Se evalúa al corte y usa todos los artículos, no solo las primeras 15 alertas. |
| Agotados con demanda | Artículos con stock total ≤ 0 y ventas positivas recientes / artículos con ventas positivas recientes. A nivel empresa cuenta cada artículo una vez; el detalle por almacén evalúa cada almacén por separado. |
| Punto de equilibrio | Gastos fijos del período / [1 − (costo comercial de ventas + otros gastos variables) / ventas netas]. Requiere clasificación completa, costo disponible, ventas y contribución positivas. |
| Descuentos | Descuentos comerciales de líneas y descuento adicional distribuido / importe antes de descuentos. Se convierte a moneda de empresa y se elimina el impuesto incluido usando la base neta de cada línea. Excluye devoluciones y descuentos financieros. Si una línea gratuita impide reconstruir su base sin impuestos, muestra N/A. |
| Devoluciones | Importe absoluto de devoluciones / ventas antes de devoluciones, sin impuestos. Puede superar 100% si se devuelven ventas de períodos anteriores. Sin ventas positivas muestra N/A. |
| Ciclo de efectivo | DIO + DSO − DPO. DIO = inventario contable promedio / costo de ventas contable diario. DSO = CxC promedio / ventas a crédito contabilizadas diarias. DPO = CxP promedio / compras a crédito contabilizadas diarias. CxC/CxP y flujos correspondientes incluyen impuestos. CxC o CxP cero sin movimiento equivalen a cero días; saldos sin flujos o denominadores negativos dan N/A. |

Las medias históricas ponderan cada movimiento por los días restantes hasta el corte, incluidos los saldos de apertura. Se excluyen documentos cancelados y se evita duplicar facturas POS con sus facturas consolidadas.

**Alcance contable:** punto de equilibrio y ciclo de efectivo requieren **Todos los almacenes**, pues los gastos y las cuentas por cobrar/pagar se contabilizan por empresa. El ciclo usa únicamente contabilidad registrada; no incluye POS pendientes de cierre. El inventario proviene de Stock Ledger Entry: los POS sin consolidar pueden estar pendientes de afectar sus existencias.

**Anualización:** GMROI y su meta se convierten juntos (365 / días). Los porcentajes, los días del ciclo y el punto de equilibrio no se anualizan. El análisis DuPont conserva su comportamiento y las metas existentes. El PDF usa la misma base seleccionada, separa los siete indicadores en una página y pagina el detalle de categorías/almacenes.

## Verificación local

```sh
python -m unittest discover -s tests -p 'test_dashboard_*.py'
node --test tests/store_dashboard_dates.test.js tests/store_dashboard_page_loader.test.js
```

Las pruebas ejecutan consultas de ventas y movimientos en una base SQLite de prueba y verifican cancelaciones, consolidación POS, filtros, promedios, descuentos, devoluciones, gastos, anualización y datos del PDF. La instalación real de DocTypes requiere un sitio Frappe con `migrate`.
