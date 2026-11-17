const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
	path.join(__dirname, "../retail_tools/retail_tools/page/store_dashboard/store_dashboard.js"),
	"utf8"
);

function makeDashboard() {
	const context = {
		frappe: {
			pages: { "store-dashboard": {} },
			sys_defaults: { date_format: "dd-mm-yyyy" },
			datetime: {
				get_today: () => "2026-11-13",
				str_to_user: (date) => {
					const [year, month, day] = date.split("-");
					return `${day}-${month}-${year}`;
				},
			},
			utils: { escape_html: (value) => value },
		},
		__: (value, args = []) => value.replace(/\{(\d+)\}/g, (_match, index) => args[index]),
		console,
	};
	vm.runInNewContext(`${source}\nthis.Dashboard = RetailStoreDashboard;`, context);
	const dashboard = Object.create(context.Dashboard.prototype);
	const values = {
		"#rt-db-company": "Test Company",
		"#rt-db-warehouse": "",
		"#rt-db-include-pos": true,
	};
	const activeButtons = new Set();
	dashboard.$container = {
		find(selector) {
			if (selector === ".rt-db-quick-btn") {
				return { removeClass: () => activeButtons.clear() };
			}
			const button = selector.match(/^\.rt-db-quick-btn\[data-range="(.+)"\]$/);
			if (button) {
				return { addClass: () => activeButtons.add(button[1]) };
			}
			return {
				length: 1,
				val(value) {
					if (arguments.length === 0) return values[selector];
					values[selector] = value;
					return this;
				},
				is: () => Boolean(values[selector]),
				empty() {},
				append() {},
				html(value) { values[selector] = value; },
				text(value) { values[selector] = value; return this; },
				removeClass() { return this; },
				addClass() { return this; },
				attr() { return this; },
			};
		},
	};
	dashboard.fromDateControl = {
		set_input: (value) => { values["#rt-db-from-date"] = value; },
		get_value: () => values["#rt-db-from-date"],
	};
	dashboard.toDateControl = {
		set_input: (value) => { values["#rt-db-to-date"] = value; },
		get_value: () => values["#rt-db-to-date"],
	};
	dashboard.activeRangeKey = null;
	dashboard.refreshRequestId = 0;
	dashboard.currency = "USD";
	dashboard.currencySymbol = "$";
	return { dashboard, context, values, activeButtons };
}

test("quick ranges use calendar dates without month boundary drift", () => {
	const { dashboard, values, activeButtons } = makeDashboard();
	dashboard.refreshData = () => {};
	dashboard.applyQuickRange("last_month");
	assert.equal(values["#rt-db-from-date"], "2026-10-01");
	assert.equal(values["#rt-db-to-date"], "2026-10-31");
	assert.deepEqual([...activeButtons], ["last_month"]);

	dashboard.applyQuickRange("this_month");
	assert.equal(values["#rt-db-from-date"], "2026-11-01");
	assert.equal(values["#rt-db-to-date"], "2026-11-13");

	dashboard.applyQuickRange("30d");
	assert.equal(values["#rt-db-from-date"], "2026-10-15");
	assert.equal(values["#rt-db-to-date"], "2026-11-13");
	assert.deepEqual([...activeButtons], ["30d"]);
});

test("initial 30-day selection uses the same dates sent to the server", () => {
	const { dashboard, values, activeButtons } = makeDashboard();
	dashboard.populateDefaults({ default_from_date: "2026-11-01", default_to_date: "2026-11-13" });
	assert.equal(values["#rt-db-from-date"], "2026-10-15");
	assert.equal(values["#rt-db-to-date"], "2026-11-13");
	assert.deepEqual([...activeButtons], ["30d"]);
});

test("editing a date clears the preset without reacting to its own update", () => {
	const { dashboard, activeButtons } = makeDashboard();
	let refreshes = 0;
	dashboard.refreshData = () => { refreshes += 1; };
	dashboard.applyQuickRange("30d");
	dashboard.onDateControlChange();
	assert.equal(refreshes, 1);
	assert.deepEqual([...activeButtons], ["30d"]);

	dashboard.fromDateControl.set_input("2026-10-01");
	dashboard.onDateControlChange();
	assert.equal(refreshes, 2);
	assert.equal(dashboard.activeRangeKey, null);
	assert.deepEqual([...activeButtons], []);
});

test("period note follows the System Settings date format", () => {
	const { dashboard, values } = makeDashboard();
	dashboard.renderPeriodNote({
		from_date: "2026-11-01",
		to_date: "2026-11-13",
		prev_from_date: "2026-10-01",
		prev_to_date: "2026-10-13",
		period_days: 13,
	});
	assert.match(values["#rt-db-period-note"], /01-11-2026.*13-11-2026/);
	assert.match(values["#rt-db-period-note"], /01-10-2026.*13-10-2026/);
});

test("an older response cannot replace the selected period or its figures", async () => {
	const { dashboard, context, values, activeButtons } = makeDashboard();
	const pending = [];
	const rendered = [];
	context.frappe.call = (request) => new Promise((resolve) => pending.push({ request, resolve }));
	dashboard.renderAll = (data) => rendered.push(data.marker);

	dashboard.applyQuickRange("this_month");
	dashboard.applyQuickRange("30d");
	assert.equal(pending[0].request.args.range_key, "this_month");
	assert.equal(pending[1].request.args.range_key, "30d");

	pending[1].resolve({
		message: { marker: "30d", filters: { from_date: "2026-10-15", to_date: "2026-11-13" } },
	});
	await new Promise((resolve) => setImmediate(resolve));
	pending[0].resolve({
		message: { marker: "this_month", filters: { from_date: "2026-11-01", to_date: "2026-11-13" } },
	});
	await new Promise((resolve) => setImmediate(resolve));

	assert.deepEqual(rendered, ["30d"]);
	assert.equal(values["#rt-db-from-date"], "2026-10-15");
	assert.deepEqual([...activeButtons], ["30d"]);
});

test("PDF chart snapshots use a fixed print size and finish animations", () => {
	const { dashboard, context } = makeDashboard();
	const elements = [];
	const copies = [];
	context.window = {
		echarts: {
			init(node) {
				const copy = {
					setOption(option) { this.option = option; },
					getDataURL() { return "data:image/png;base64,AAAA"; },
					dispose() { this.disposed = true; },
				};
				copies.push(copy);
				return copy;
			},
		},
	};
	context.document = {
		body: { appendChild(node) { elements.push(node); } },
		createElement() { return { style: {}, remove() { this.removed = true; } }; },
	};
	const keys = [
		"rt-chart-balance", "rt-chart-pnl", "rt-chart-daily", "rt-chart-category",
		"rt-chart-top-items", "rt-chart-payments", "rt-chart-calendar",
		"rt-chart-heatmap", "rt-chart-stock-vs-sales",
	];
	dashboard.charts = Object.fromEntries(keys.map((key) => [key, { getOption: () => ({ series: [] }) }]));
	const snapshots = dashboard.collectPdfCharts();
	assert.deepEqual(Object.keys(snapshots), keys);
	assert.equal(copies.length, 9);
	assert.ok(copies.every((copy) => copy.disposed));
	assert.ok(elements.slice(0, -1).every((node) => node.removed && node.style.cssText.includes("width:900px;height:700px")));
	assert.ok(elements.at(-1).removed && elements.at(-1).style.cssText.includes("width:1060px;height:700px"));
});

test("PDF export sends the visible period and downloads the returned file", async () => {
	const { dashboard, context } = makeDashboard();
	let request;
	let clicked = false;
	let buttonDisabled = false;
	context.frappe.csrf_token = "csrf-test";
	context.frappe.msgprint = () => { throw new Error("Unexpected message"); };
	context.fetch = async (url, options) => {
		request = { url, options };
		return { ok: true, headers: { get: () => "application/pdf" }, blob: async () => ({ size: 100 }) };
	};
	context.URL = { createObjectURL: () => "blob:report", revokeObjectURL() {} };
	context.setTimeout = () => 1;
	context.document = {
		body: { appendChild() {} },
		createElement: () => ({ click() { clicked = true; }, remove() {} }),
	};
	dashboard.$exportPdfButton = { prop(_name, value) { buttonDisabled = value; } };
	dashboard.collectPdfCharts = () => ({ "rt-chart-balance": "data:image/png;base64,AAAA" });
	dashboard.payload = { filters: {
		company: "Tienda", warehouse: "Sucursal", from_date: "2026-10-15",
		to_date: "2026-11-13", include_pending_pos: 1,
	} };
	dashboard.payloadRangeKey = "30d";
	dashboard.pnlMode = "expenses";
	dashboard.trendMode = "monthly";
	dashboard.indicatorMode = "annualized";
	await dashboard.exportDashboardPdf();
	assert.equal(request.options.headers["X-Frappe-CSRF-Token"], "csrf-test");
	const body = JSON.parse(request.options.body);
	assert.equal(body.from_date, "2026-10-15");
	assert.equal(body.range_key, "30d");
	assert.equal(body.chart_modes.pnl, "expenses");
	assert.equal(body.chart_modes.trend, "monthly");
	assert.equal(body.chart_modes.indicators, "annualized");
	assert.equal(clicked, true);
	assert.equal(buttonDisabled, false);
});

test("indicator mode updates DuPont and the table together and survives refresh and category filters", () => {
	const { dashboard, values } = makeDashboard();
	dashboard.charts = {};
	dashboard.indicatorFilter = "all";
	dashboard.refreshData = () => { throw new Error("Switching modes must not fetch sales again"); };
	const view = (annualized) => ({
		mode: annualized ? "annualized" : "period",
		label: annualized ? "Anualizado" : "Del período",
		note: annualized ? "Estimación lineal: 365 / 30" : "30 días analizados",
		dupont: {
			sales: 10000, net_profit: 1000, assets: 100000, equity: 50000,
			scaled_sales: annualized ? 121666.67 : 10000, scaled_profit: annualized ? 12166.67 : 1000,
			margin: 10, turnover: annualized ? 1.2166667 : 0.1, multiplier: 2,
			roe: annualized ? 24.333333 : 2, status: "warning", status_label: "Moderado",
			reference_formatted: annualized ? "Meta anual >= 60.8%" : "Meta en 30 días >= 5.0%",
		},
		indicators: [
			{category: "Rentabilidad", name: "ROE", value_formatted: annualized ? "24.3%" : "2.0%", formula: "", reference_formatted: "", status: "warning"},
			{category: "Liquidez y Solvencia", name: "Liquidez", value_formatted: "1.50x", formula: "", reference_formatted: ""},
		],
		inventory_details: [{ group: "Categoría", name: "Ropa", average: "C$ 12,000", gmroi: annualized ? "3.65x" : "0.30x", dead_value: "C$ 1,500", dead_pct: "12.5%", stockout: "2 / 20", stockout_pct: "10.0%" }],
	});
	dashboard.payload = { indicator_views: { period: view(false), annualized: view(true) }, indicator_settings: { can_configure: true } };
	dashboard.setIndicatorMode("annualized");
	assert.match(values["#rt-chart-dupont"], /24\.3%/);
	assert.match(values["#rt-chart-dupont"], /1\.22x/);
	assert.match(values["#rt-chart-dupont"], /10\.0%/);
	assert.match(values["#rt-chart-dupont"], /2\.00x/);
	assert.match(values["#rt-chart-dupont"], /Meta anual &gt;= 60.8%|Meta anual >= 60.8%/);
	assert.match(values["#rt-db-indicators-tbody"], /24\.3%/);
	assert.match(values["#rt-db-indicator-note"], /365 \/ 30/);
	assert.match(values["#rt-db-inventory-details"], /3\.65x/);
	assert.match(values["#rt-db-indicator-settings"], /Configurar gastos y metas/);
	for (const method of ["renderPeriodNote", "renderKpiCards", "renderBalanceSheetChart", "renderPnlChart", "renderTrendChart", "renderCategoryChart", "renderTopItemsChart", "renderPaymentsChart", "renderCalendarHeatmapChart", "renderHeatmapChart", "renderStockVsSalesChart", "renderAlertTables"]) dashboard[method] = () => {};
	dashboard.indicatorFilter = "Rentabilidad";
	dashboard.renderAll({ ...dashboard.payload, financials: {}, charts: {} });
	assert.match(values["#rt-db-indicators-tbody"], /24\.3%/);
	assert.doesNotMatch(values["#rt-db-indicators-tbody"], /Liquidez/);
	dashboard.setIndicatorMode("period");
	assert.match(values["#rt-chart-dupont"], /2\.0%/);
	assert.doesNotMatch(values["#rt-chart-dupont"], /24\.3%/);
	assert.equal(dashboard.indicatorFilter, "Rentabilidad");
	assert.match(values["#rt-db-inventory-details"], /0\.30x/);
	dashboard.payload.indicator_settings.can_configure = false;
	dashboard.renderIndicatorSection(dashboard.payload);
	assert.equal(values["#rt-db-indicator-settings"], "");
	dashboard.setIndicatorMode("invalid");
	assert.equal(dashboard.indicatorMode, "period");
});

test("daily and monthly charts combine POS and normal invoices into one sales series", () => {
	const { dashboard } = makeDashboard();
	dashboard.isMobileViewport = () => false;
	let option;
	dashboard.getOrCreateChart = () => ({ setOption(value) { option = value; } });
	const trend = { dates: ["2026-11-01"], sales: [150], pos_sales: [100], direct_sales: [50], profit: [30], margin_pct: [20] };
	for (const monthly of [false, true]) {
		dashboard.renderDailyTrendChart(trend, monthly);
		assert.deepEqual(Array.from(option.series, (series) => series.name), ["Ventas", "Utilidad Bruta", "Margen Bruto (%)"]);
		assert.equal(option.series[0].data[0], 150);
		assert.equal(option.xAxis[0].data[0], monthly ? "Nov 2026" : "01-11-2026");
	}
});

test("switching trend views uses monthly history and keeps the daily data intact", () => {
	const { dashboard, values } = makeDashboard();
	let selected;
	dashboard.renderDailyTrendChart = (trend, monthly) => { selected = { trend, monthly }; };
	const charts = {
		daily_trend: { sales: [10] },
		monthly_trend: { from_date: "2025-11-01", to_date: "2026-11-14", scope: "13m", sales: [100] },
	};
	dashboard.trendMode = "monthly";
	dashboard.renderTrendChart(charts);
	assert.equal(selected.trend, charts.monthly_trend);
	assert.equal(selected.monthly, true);
	assert.match(values["#rt-db-trend-subtitle"], /Últimos 13 meses.*01-11-2025.*14-11-2026/);
	charts.monthly_trend = { from_date: "2026-01-01", to_date: "2026-11-14", scope: "ytd" };
	dashboard.renderTrendChart(charts);
	assert.match(values["#rt-db-trend-subtitle"], /Este Año.*01-01-2026/);
	dashboard.trendMode = "daily";
	dashboard.renderTrendChart(charts);
	assert.equal(selected.trend, charts.daily_trend);
	assert.equal(selected.monthly, false);
});

test("month-to-day view selects partial totals and describes the cutoff without changing monthly totals", () => {
	const { dashboard, values } = makeDashboard();
	let selected;
	dashboard.renderDailyTrendChart = (trend, monthly) => { selected = { trend, monthly }; };
	const charts = { monthly_trend: {
		from_date: "2025-11-01", to_date: "2026-11-14", scope: "13m", sales: [1000],
		to_day: { from_date: "2025-11-01", to_date: "2026-11-14", scope: "13m", cutoff_day: 14, sales: [400] },
	} };
	dashboard.trendMode = "monthly_to_day";
	dashboard.renderTrendChart(charts);
	assert.equal(selected.trend, charts.monthly_trend.to_day);
	assert.equal(selected.monthly, true);
	assert.match(values["#rt-db-trend-subtitle"], /Últimos 13 meses.*Hasta el día 14 de cada mes/);
	assert.match(values["#rt-db-trend-title"], /Mensual al Día/);
	dashboard.trendMode = "monthly";
	dashboard.renderTrendChart(charts);
	assert.equal(selected.trend, charts.monthly_trend);
	assert.doesNotMatch(values["#rt-db-trend-subtitle"], /Hasta el día 14/);
});
