# GEMINI.md - Retail Tools

## Project Overview

**Retail Tools** is a Frappe Framework application that provides specialized tools for retail operations within ERPNext. The primary feature is the Item Inspector page.

## Architecture

### Technology Stack

- **Backend**: Frappe Framework (Python)
- **Frontend**: Frappe UI (JavaScript + jQuery)
- **Database**: MariaDB (via Frappe ORM)
- **Styling**: Custom CSS with Frappe theme variables

### Project Structure

```
retail_tools/
├── retail_tools/                    # App package
│   ├── retail_tools/               # Module package
│   │   └── page/
│   │       └── item_inspector/     # Main page component
│   ├── hooks.py                    # Frappe hooks configuration
│   ├── config/                     # Desktop/module configuration
│   ├── templates/                  # Jinja templates
│   └── public/                     # Static assets
├── pyproject.toml                  # Python project config
└── .eslintrc                       # ESLint configuration
```

## Key Components

### Item Inspector (`retail_tools/retail_tools/page/item_inspector/`)

Dashboard page for quick product lookup.

#### Backend API (`item_inspector.py`)

| Function | Description |
|----------|-------------|
| `resolve_item_from_barcode(barcode)` | Resolves item code from barcode |
| `get_item_snapshot(item_code)` | Returns comprehensive item data |
| `_get_valuation_rates(item_code)` | Gets latest valuation by warehouse |

#### Frontend (`item_inspector.js`)

- Class: `retail_tools.ItemInspector`
- Features: Barcode scanning, responsive tables, price charts
- Chart library: `frappe.Chart`

## Development Guidelines

### Python Conventions

- Use type hints for all function parameters and returns
- Use docstrings for public functions
- Prefer `lru_cache` for expensive lookups that don't change often
- Use Frappe's ORM (`frappe.get_all`, `frappe.db.get_value`)

### JavaScript Conventions

- Use ES6 class syntax
- Always clean up event handlers in `destroy()` method
- Use `frappe.call()` with error callbacks
- Escape user input with `frappe.utils.escape_html()`

### CSS Conventions

- Use CSS custom properties for theme support
- Follow BEM-like naming with `ii-` prefix
- Mobile-first responsive design
- Support both light and dark modes

## Common Tasks

### Adding a new API endpoint

```python
@frappe.whitelist()
def my_new_function(param: str) -> dict:
    """Brief description.
    
    Args:
        param: Description of param
        
    Returns:
        dict with result data
    """
    # Implementation
    return {"ok": True, "data": result}
```

### Calling API from JavaScript

```javascript
frappe.call({
  method: "retail_tools.retail_tools.page.item_inspector.item_inspector.my_new_function",
  args: { param: value },
  callback: (r) => {
    if (r.message?.ok) {
      // Handle success
    }
  },
  error: (err) => {
    console.error("Error:", err);
    frappe.msgprint(__("Operation failed"));
  },
});
```

## Database Dependencies

The Item Inspector queries these DocTypes:
- `Item` - Master data
- `Item Barcode` - Barcode mappings
- `Bin` - Stock levels by warehouse
- `Stock Ledger Entry` - Valuation rates
- `Item Price` - Price history
- `Sales Invoice` / `Sales Invoice Item`
- `Purchase Invoice` / `Purchase Invoice Item`

## Testing

Currently no automated tests. Manual testing:

1. Open Item Inspector page
2. Search for item by barcode
3. Verify stock, prices, and transactions display correctly
4. Test on mobile viewport
5. Test dark mode toggle
