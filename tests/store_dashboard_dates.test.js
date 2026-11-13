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
		__: (value) => value,
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
				val(value) {
					if (arguments.length === 0) return values[selector];
					values[selector] = value;
					return this;
				},
				is: () => Boolean(values[selector]),
				empty() {},
				append() {},
				html(value) { values[selector] = value; },
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
	assert.ok(elements.every((node) => node.removed && node.style.cssText.includes("960px")));
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
	await dashboard.exportDashboardPdf();
	assert.equal(request.options.headers["X-Frappe-CSRF-Token"], "csrf-test");
	const body = JSON.parse(request.options.body);
	assert.equal(body.from_date, "2026-10-15");
	assert.equal(body.range_key, "30d");
	assert.equal(body.chart_modes.pnl, "expenses");
	assert.equal(clicked, true);
	assert.equal(buttonDisabled, false);
});
