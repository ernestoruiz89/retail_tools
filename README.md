# Retail Tools

A Frappe/ERPNext application with specialized tools for retail operations.

## 📦 Features

### Item Inspector

Complete dashboard page for quick product information lookup.

**Route:** `/app/item-inspector`

#### Search
- **Barcode** - Camera scanning or manual entry
- **Item Code** - Link field with autocomplete
- **Multi-match** - Selector when multiple items share the same barcode

#### Product Information
- Name, code, group, brand, UoM
- Product image
- Description (plain text, no HTML)
- Status tags: DISABLED, Not a stock item

#### Main KPIs
| Indicator | Description |
|-----------|-------------|
| **Total Stock** | Sum of quantities across all warehouses |
| **Estimated Cost (stock)** | Total inventory value |
| **Current Price** | Price from selected price list (updates dynamically) |
| **Sales 30 Days** | Sales amount with unit and invoice details |
| **Profit Margin** | Percentage with color coding (green ≥20%, yellow ≥10%, red <10%) |
| **Days Without Movement** | Days since last sale (green <30, yellow 30-59, red 60+) |
| **Last Sale** | Total amount with unit and unit price details |
| **Last Purchase** | Total amount with unit and unit cost details |

#### Automatic Alerts
- ⚠️ **Low Stock** - When stock < reorder level
- ⏰ **No Sales 60+ Days** - Possibly obsolete product

#### Price History
- Price list selector
- Interactive price evolution chart
- Table with last 10 price changes
- Price and margin update when changing price list

#### Stock by Warehouse
- Current, reserved, and projected quantities
- Valuation cost per warehouse
- Estimated value by location

#### Recent Transactions
- Last 10 sales with document link
- Last 10 purchases with document link

#### Quick Actions
- **Open Item** - Go to product form
- **Balances** - Filtered Stock Balance report
- **Movements** - Filtered Stock Ledger report

---

### Item Inspector Light

Simplified version for quick lookups with guest access.

**Route:** `/app/item-inspector-light`

**Features:**
- Only 3 KPIs: Stock, Estimated cost, Current price
- Price history (chart and table)
- No navigation buttons
- Minimalist design
- Guest role access enabled

---

### Customer Lookup

Dashboard page for quick customer information lookup.

**Route:** `/app/customer-lookup`

#### Search
- Search by customer code, name, phone, or email
- Quick selection from search results

#### Customer Information
- Name, customer group, territory
- Mobile phone and email (when available)
- Primary address

#### Main KPIs
| Indicator | Description |
|-----------|-------------|
| **Outstanding Balance** | Total unpaid amount from Sales Invoices |
| **Lifetime Value** | Total purchases with invoice count |
| **Last Purchase** | Date of most recent transaction |
| **Loyalty Points** | Current points balance (if Loyalty Program is enabled) |

#### Recent Invoices
- Last 10 sales invoices with document links
- Invoice status, date, and amounts

#### Allowed Roles
- Sales User, Sales Manager, System Manager, Administrator, Accounts User

---

### Catalog Generator

Generate product catalogs for printing or digital distribution.

**Route:** `/app/catalog-generator`

#### Filters
- **Item Group** - Filter by group (includes child groups)
- **Brand** - Filter by brand
- **Warehouse** - Filter by items with stock
- **Price List** - Price list for pricing
- **Include Disabled** - Option to include disabled items

#### Layout Options
- Column selection (2, 3, or 4 columns)
- Responsive grid layout

#### Display Options
| Option | Description |
|--------|-------------|
| **Show Barcode** | Display barcode text |
| **Show Barcode Image** | Display barcode image |
| **Show Price** | Display item price |
| **Show Description** | Display item description |
| **Group by Item Group** | Organize items by category |

#### Output
- HTML preview for printing
- PDF-ready layout

#### Allowed Roles
- System Manager, Sales Manager, Sales User, Stock Manager, Stock User

---

### Label Generator

Generate barcode labels for printing.

**Route:** `/app/label-generator`

#### Label Formats
| Format | Size | Columns |
|--------|------|---------|
| **Small** | 38×25mm | 4 columns |
| **Medium** | 50×30mm | 3 columns |
| **Large** | 70×40mm | 2 columns |

#### Features
- Add items by barcode or item code
- Specify quantity per item
- Dynamic font sizing based on format
- Dynamic barcode height per format
- Price display toggle
- Load items with stock (with warehouse filter)
- Print-ready HTML output

#### Allowed Roles
- System Manager, Stock Manager, Stock User, Sales User

---

### POS Closing Report (Print Format)

Custom print format for POS Closing Entry documents, optimized for thermal receipt printers.

**DocType:** `POS Closing Entry`

#### Layout
- Optimized for thermal printers
- Monospace font (Courier New) for alignment
- Compact design with dashed section dividers

#### Sections
| Section | Content |
|---------|---------|
| **Header** | Company name, document ID, POS profile, user, period dates |
| **Sales Summary** | Transaction count, item quantity, net total, grand total |
| **Payment Methods** | Opening amount, expected amount, closing amount, difference (color-coded) |
| **Transactions** | List of all POS invoices with customer, date, amount, and return badge |
| **Footer** | Cashier signature line, print timestamp |

#### Features
- Color-coded payment differences (green for positive, red for negative)
- Return transactions marked with "RET" badge
- Automatic currency symbol from company settings
- Print-ready CSS with proper margins

---

## 🚀 Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/ernestoruiz89/retail_tools
bench install-app retail_tools
bench build --app retail_tools
bench restart
```

## 📋 Requirements

- Frappe Framework v15+
- ERPNext v15+
- Python 3.10+

## 💻 Usage

### Accessing Pages

| Page | Navigation | Direct URL |
|------|------------|------------|
| Item Inspector | Modules > Retail Tools > Item Inspector | `/app/item-inspector` |
| Item Inspector Light | - | `/app/item-inspector-light` |
| Customer Lookup | Modules > Retail Tools > Customer Lookup | `/app/customer-lookup` |
| Catalog Generator | Modules > Retail Tools > Catalog Generator | `/app/catalog-generator` |
| Label Generator | Modules > Retail Tools > Label Generator | `/app/label-generator` |

### Searching for a Product

- **By barcode**: Enter the code and press Enter
- **By Item Code**: Use the "Product" Link field
- **With camera**: Click "Scan with camera" (requires HTTPS)

### Searching for a Customer

- Enter customer name, code, phone, or email
- Select from search results

## 🛠️ Development

### Environment Setup

This app uses `pre-commit` for formatting and linting:

```bash
cd apps/retail_tools
pre-commit install
```

### Code Tools

- **ruff** - Python linter and formatter
- **eslint** - JavaScript linter
- **prettier** - Code formatter

### Project Structure

```
retail_tools/
├── retail_tools/
│   ├── retail_tools/
│   │   └── page/
│   │       ├── item_inspector/           # Full product lookup
│   │       │   ├── item_inspector.py     # Backend API
│   │       │   ├── item_inspector.js     # Frontend
│   │       │   └── item_inspector.css    # Styles
│   │       ├── item_inspector_light/     # Simplified version
│   │       │   ├── item_inspector_light.py
│   │       │   ├── item_inspector_light.js
│   │       │   └── item_inspector_light.css
│   │       ├── customer_lookup/          # Customer lookup
│   │       │   ├── customer_lookup.py
│   │       │   ├── customer_lookup.js
│   │       │   └── customer_lookup.css
│   │       ├── catalog_generator/        # Product catalog
│   │       │   ├── catalog_generator.py
│   │       │   ├── catalog_generator.js
│   │       │   └── catalog_generator.css
│   │       └── label_generator/          # Barcode labels
│   │           ├── label_generator.py
│   │           ├── label_generator.js
│   │           └── label_generator.css
│   ├── hooks.py
│   └── patches.txt
├── pyproject.toml
└── README.md
```

### API Endpoints

#### Item Inspector
| Endpoint | Description |
|----------|-------------|
| `resolve_item_from_barcode(barcode)` | Resolves barcode to Item |
| `get_item_snapshot(item_code)` | Returns complete product snapshot |

#### Customer Lookup
| Endpoint | Description |
|----------|-------------|
| `search_customer(query)` | Search customers by code, name, phone, email |
| `get_customer_snapshot(customer)` | Returns complete customer snapshot |

#### Catalog Generator
| Endpoint | Description |
|----------|-------------|
| `get_items_for_catalog(...)` | Get filtered items for catalog |
| `generate_catalog_html(...)` | Generate catalog HTML for preview/print |

#### Label Generator
| Endpoint | Description |
|----------|-------------|
| `get_label_formats()` | Get available label formats |
| `get_item_for_label(item_code)` | Get item data for label |
| `get_items_with_stock(warehouse)` | Get items with stock |
| `generate_labels_html(items, format)` | Generate labels HTML for printing |

## 📄 License

MIT
