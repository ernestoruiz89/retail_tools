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

1. **Cargar cuentas de mayor** incorpora los grupos principales bajo la raíz de gastos y conserva las filas existentes. Puede elegir cualquier mayor o cuenta de detalle directamente en la tabla. **Cargar cuentas → Cargar cuentas de detalle** sigue disponible cuando se necesita clasificar individualmente.
2. Clasificar los mayores según su comportamiento real: **Fijo**, **Variable**, **Costo de ventas** o **Excluido**. Las subcuentas, incluidas las que se creen después, heredan la clasificación del mayor más cercano que tenga una regla. Una clasificación de detalle tiene prioridad; una fila vacía permite heredar. Se usa la jerarquía del catálogo, no el prefijo del número. Cada movimiento se cuenta una sola vez, aunque se configuren varios niveles. Las cuentas de tipo Cost of Goods Sold conservan siempre **Costo de ventas**, incluso bajo un mayor fijo o variable, para no duplicar el costo comercial. Las cuentas con movimiento sin clasificación propia ni heredada dejan pendiente el punto de equilibrio.
3. Ajustar los días de inactividad (60 por defecto) y de demanda reciente (30 por defecto).
4. Registrar metas saludables y límites moderados para cualquiera de los 20 indicadores. La columna **Criterio** indica si la meta es un mínimo, un máximo o un intervalo. Si no se configura una meta, se aplica el criterio predeterminado del indicador cuando existe. **GMROI, capital estancado, agotados con demanda, descuentos, devoluciones y ciclo de efectivo** necesitan una meta personalizada para evaluar su resultado; mientras tanto muestran **Sin meta**. El punto de equilibrio indica si las ventas cubren los gastos cuando no se configura una meta de cobertura.

Las metas de **ROA, ROE, rotación de inventario y GMROI** se introducen en base anual. Para conservar los umbrales originales: ROA 36.5% (moderado 0%), ROE 60.833333% (moderado 0%) y rotación 6.083333 veces (moderado 1.825 veces). La tabla y DuPont convierten meta y resultado a la misma base al cambiar el selector.

**Ticket promedio y UPT** tienen metas separadas; el semáforo de su fila conjunta muestra el peor estado entre las metas configuradas. **DIO** acepta un mínimo saludable además de la meta máxima y del máximo moderado. La **cobertura del punto de equilibrio** usa ventas proyectadas a 30 días / punto de equilibrio mensual × 100; ambos importes se convierten con el mismo factor, por lo que la cobertura y sus metas porcentuales conservan su equivalencia. Sin meta personalizada, el semáforo indica si el ritmo de ventas es suficiente. Si el punto de equilibrio es cero, no se divide por cero.

## Bases de cálculo

| Indicador | Base |
| --- | --- |
| GMROI | Utilidad bruta comercial de artículos de stock / media de los saldos diarios de inventario al costo. Usa el costo comercial del dashboard (tasa de entrada o valoración de respaldo). Excluye servicios. Sin historial, inventario promedio positivo o costo disponible, muestra N/A. Una valoración promedio negativa por artículo y almacén también lo invalida y se indica como causa en pantalla y PDF. |
| Capital estancado | Valor positivo del stock sin ventas durante los días configurados / valor positivo total del stock. Un artículo nunca vendido espera ese plazo desde su primera entrada. Se evalúa al corte y usa todos los artículos, no solo las primeras 15 alertas. |
| Agotados con demanda | Artículos con stock total ≤ 0 y ventas positivas recientes / artículos con ventas positivas recientes. A nivel empresa cuenta cada artículo una vez; el detalle por almacén evalúa cada almacén por separado. |
| Punto de equilibrio mensual | Ventas necesarias por mes, con base fija de 30 días: (gastos fijos del período × 30 / días analizados) / [1 − (costo comercial de ventas + otros gastos variables) / ventas netas]. El margen se calcula con los importes del período. Requiere clasificación completa, costo disponible en los artículos vendidos, ventas y contribución positivas. Los saldos históricos de inventario negativos no bloquean este cálculo: su validación es independiente de GMROI. |
| Descuentos | Descuentos comerciales de líneas y descuento adicional distribuido / importe antes de descuentos. Se convierte a moneda de empresa y se elimina el impuesto incluido usando la base neta de cada línea. Excluye devoluciones y descuentos financieros. Si una línea gratuita impide reconstruir su base sin impuestos, muestra N/A. |
| Devoluciones | Importe absoluto de devoluciones / ventas antes de devoluciones, sin impuestos. Puede superar 100% si se devuelven ventas de períodos anteriores. Sin ventas positivas muestra N/A. |
| Ciclo de efectivo | DIO + DSO − DPO. DIO = inventario contable promedio / costo de ventas contable diario. DSO = CxC promedio / ventas a crédito contabilizadas diarias. DPO = CxP promedio / compras a crédito contabilizadas diarias. CxC/CxP y flujos correspondientes incluyen impuestos. CxC o CxP cero sin movimiento equivalen a cero días; saldos sin flujos o denominadores negativos dan N/A. |

Las medias históricas ponderan cada movimiento por los días restantes hasta el corte, incluidos los saldos de apertura. Se excluyen documentos cancelados y se evita duplicar facturas POS con sus facturas consolidadas.

El punto de equilibrio mensual es una estimación lineal con los gastos registrados en el período seleccionado, no un presupuesto de gastos aún no contabilizados. Por ejemplo, un punto de equilibrio de C$50,000 en 15 días se muestra como **C$100,000 / mes**. Los meses de 28 o 31 días y los períodos anuales también se convierten a 30 días; cambiar entre **Del período** y **Anualizado** no cambia esta base mensual. Sin gastos fijos netos registrados, el resultado sigue siendo cero.

**Alcance contable:** punto de equilibrio y ciclo de efectivo requieren **Todos los almacenes**, pues los gastos y las cuentas por cobrar/pagar se contabilizan por empresa. El ciclo usa únicamente contabilidad registrada; no incluye POS pendientes de cierre. El inventario proviene de Stock Ledger Entry: los POS sin consolidar pueden estar pendientes de afectar sus existencias.

**Anualización:** GMROI y su meta se convierten juntos (365 / días). Los porcentajes y los días del ciclo no se anualizan; el punto de equilibrio siempre usa la base mensual de 30 días. El análisis DuPont conserva su comportamiento y las metas existentes. El PDF usa las mismas bases que el dashboard, separa los siete indicadores en una página y pagina el detalle de categorías/almacenes.

## Verificación local

```sh
python -m unittest discover -s tests -p 'test_dashboard_*.py'
node --test tests/store_dashboard_dates.test.js tests/store_dashboard_page_loader.test.js
```

Las pruebas ejecutan consultas de ventas y movimientos en una base SQLite de prueba y verifican cancelaciones, consolidación POS, filtros, promedios, descuentos, devoluciones, gastos, anualización y datos del PDF. La instalación real de DocTypes requiere un sitio Frappe con `migrate`.
