# Retail Tools

Una aplicación Frappe/ERPNext con herramientas especializadas para operaciones de retail.

## 📦 Características

### Item Inspector (Consulta de Producto)

Página de dashboard completa para consulta rápida de información de productos.

#### Búsqueda
- **Código de barras** - Escaneo con cámara o entrada manual
- **Item Code** - Campo Link con autocompletado
- **Multi-match** - Selector cuando hay múltiples items con mismo código

#### Información del Producto
- Nombre, código, grupo, marca, UoM
- Imagen del producto
- Descripción (texto plano sin HTML)
- Tags de estado: DESHABILITADO, No es stock item

#### KPIs Principales
| Indicador | Descripción |
|-----------|-------------|
| **Existencia total** | Suma de cantidades en todos los almacenes |
| **Costo estimado (stock)** | Valor total del inventario |
| **Precio actual** | Precio de la lista seleccionada (se actualiza dinámicamente) |
| **Ventas 30 días** | Monto vendido con detalle de unidades y facturas |
| **Margen de utilidad** | Porcentaje con código de color (verde ≥20%, amarillo ≥10%, rojo <10%) |
| **Días sin movimiento** | Días desde última venta (verde <30, amarillo 30-59, rojo 60+) |
| **Última venta** | Monto total con detalle de unidades y precio unitario |
| **Última compra** | Monto total con detalle de unidades y costo unitario |

#### Alertas Automáticas
- ⚠️ **Stock bajo** - Cuando existencia < nivel de reorden
- ⏰ **Sin ventas 60+ días** - Producto posiblemente obsoleto

#### Histórico de Precios
- Selector de lista de precios
- Gráfica interactiva de evolución de precios
- Tabla con últimos 10 cambios de precio
- Precio y margen se actualizan al cambiar lista

#### Stock por Almacén
- Cantidad actual, reservada, proyectada
- Costo de valuación por almacén
- Valor estimado por ubicación

#### Transacciones Recientes
- Últimas 10 ventas con enlace al documento
- Últimas 10 compras con enlace al documento

#### Acciones Rápidas
- **Abrir Item** - Ir al formulario del producto
- **Saldos** - Reporte Stock Balance filtrado
- **Movimientos** - Reporte Stock Ledger filtrado

---

### Item Inspector Light (Consulta Rápida)

Versión simplificada para consultas rápidas con acceso para invitados.

**Ruta:** `/app/item-inspector-light`

**Características:**
- Solo 3 KPIs: Existencia, Costo estimado, Precio actual
- Histórico de precios (gráfico y tabla)
- Sin botones de navegación
- Diseño minimalista

---

## 🚀 Instalación

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/ernestoruiz89/retail_tools
bench install-app retail_tools
bench build --app retail_tools
bench restart
```

## 📋 Requisitos

- Frappe Framework v15+
- ERPNext (opcional, pero recomendado para funcionalidad completa)
- Python 3.10+

## 💻 Uso

### Acceder a Item Inspector

1. Navega a: **Módulos > Retail Tools > Item Inspector**
2. O busca "Consulta de Producto" en la barra de búsqueda
3. O directamente: `/app/item-inspector`

### Acceder a Item Inspector Light

1. Navega a: `/app/item-inspector-light`
2. Disponible para usuarios con rol Guest

### Buscar un producto

- **Por código de barras**: Ingresa el código y presiona Enter
- **Por Item Code**: Usa el campo Link de "Producto"
- **Con cámara**: Click en "Escanear con cámara" (requiere HTTPS)

## 🛠️ Desarrollo

### Configuración del entorno

Esta app usa `pre-commit` para formateo y linting:

```bash
cd apps/retail_tools
pre-commit install
```

### Herramientas de código

- **ruff** - Linter y formatter de Python
- **eslint** - Linter de JavaScript
- **prettier** - Formatter de código

### Estructura del proyecto

```
retail_tools/
├── retail_tools/
│   ├── retail_tools/
│   │   └── page/
│   │       ├── item_inspector/          # Página completa
│   │       │   ├── item_inspector.py    # API backend
│   │       │   ├── item_inspector.js    # Frontend
│   │       │   └── item_inspector.css   # Estilos
│   │       └── item_inspector_light/    # Versión simplificada
│   │           ├── item_inspector_light.py
│   │           ├── item_inspector_light.js
│   │           └── item_inspector_light.css
│   ├── hooks.py
│   └── patches.txt
├── pyproject.toml
└── README.md
```

### API Endpoints

| Endpoint | Descripción |
|----------|-------------|
| `resolve_item_from_barcode(barcode)` | Resuelve código de barras a Item |
| `get_item_snapshot(item_code)` | Retorna snapshot completo del producto |

## 📄 Licencia

MIT
