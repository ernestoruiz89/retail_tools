# Retail Tools

Una aplicación Frappe/ERPNext con herramientas especializadas para operaciones de retail.

## 📦 Características

### Item Inspector (Consulta de Producto)

Página de dashboard para consulta rápida de información de productos:

- **Búsqueda por código de barras** - Escaneo con cámara o entrada manual
- **Información del producto** - Nombre, grupo, marca, UoM, imagen
- **Stock por almacén** - Cantidades actuales, reservadas, proyectadas
- **Valorización** - Costo de valuación y valor estimado del inventario
- **Historial de precios** - Gráfica interactiva por lista de precios
- **Transacciones recientes** - Últimas 10 ventas y compras

## 🚀 Instalación

Puedes instalar esta aplicación usando [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app retail_tools
```

## 📋 Requisitos

- Frappe Framework v15+
- ERPNext (opcional, pero recomendado para funcionalidad completa)
- Python 3.10+

## 💻 Uso

### Acceder a Item Inspector

1. Navega a: **Módulos > Retail Tools > Item Inspector**
2. O busca "Consulta de Producto" en la barra de búsqueda

### Buscar un producto

- **Por código de barras**: Ingresa el código en el campo "Código de barras" y presiona Enter
- **Por Item Code**: Usa el campo Link de "Producto"
- **Con cámara**: Click en "Escanear con cámara" (requiere HTTPS)

## 🛠️ Desarrollo

### Configuración del entorno

Esta app usa `pre-commit` para formateo y linting. Instala pre-commit:

```bash
cd apps/retail_tools
pre-commit install
```

### Herramientas de código

- **ruff** - Linter y formatter de Python
- **eslint** - Linter de JavaScript
- **prettier** - Formatter de código
- **pyupgrade** - Actualizador de sintaxis Python

### Estructura del proyecto

```
retail_tools/
├── retail_tools/
│   ├── retail_tools/
│   │   └── page/
│   │       └── item_inspector/     # Página principal
│   │           ├── item_inspector.py   # API backend
│   │           ├── item_inspector.js   # Frontend logic
│   │           └── item_inspector.css  # Estilos
│   ├── hooks.py                    # Hooks de Frappe
│   └── patches.txt                 # Migraciones de BD
├── pyproject.toml                  # Configuración del proyecto
└── README.md
```

## 📄 Licencia

MIT
