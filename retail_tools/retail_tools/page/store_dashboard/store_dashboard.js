frappe.pages["store-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Panel de Control de Tienda"),
		single_column: true,
	});

	wrapper.store_dashboard = new RetailStoreDashboard(page, wrapper);
};

frappe.pages["store-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.store_dashboard && typeof wrapper.store_dashboard.resizeAllCharts === "function") {
		setTimeout(() => wrapper.store_dashboard.resizeAllCharts(), 120);
	}
};

class RetailStoreDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.$container = $(this.page.main);
		this.charts = {};
		this.payload = null;
		this.currency = "USD";
		this.currencySymbol = "$";
		this.pnlMode = "waterfall"; // "waterfall" | "expenses"
		this.topItemsMode = "by_revenue"; // "by_revenue" | "by_profit" | "by_qty"
		this.indicatorFilter = "all";

		this.setupPageActions();
		this.renderSkeleton();
		this.bindWindowResize();
		this.init();
	}

	setupPageActions() {
		this.page.set_primary_action(
			__("Actualizar Panel"),
			() => this.refreshData(),
			"refresh"
		);
	}

	renderSkeleton() {
		this.$container.html(`
			<div class="rt-dashboard-wrapper">
				<!-- Barra de Filtros -->
				<div class="rt-db-filter-bar">
					<div class="rt-db-filter-top">
						<div class="rt-db-filter-group">
							<div class="rt-db-field">
								<label for="rt-db-company">${__("Empresa")}</label>
								<select id="rt-db-company"></select>
							</div>
							<div class="rt-db-field">
								<label for="rt-db-warehouse">${__("Almacén / Tienda")}</label>
								<select id="rt-db-warehouse">
									<option value="">${__("Todos los almacenes")}</option>
								</select>
							</div>
							<div class="rt-db-field">
								<label for="rt-db-from-date">${__("Desde")}</label>
								<input type="date" id="rt-db-from-date" />
							</div>
							<div class="rt-db-field">
								<label for="rt-db-to-date">${__("Hasta")}</label>
								<input type="date" id="rt-db-to-date" />
							</div>
							<label class="rt-db-pos-toggle" title="${__("Incluye tickets de POS emitidos hoy aún no consolidados en cierre de caja")}">
								<input type="checkbox" id="rt-db-include-pos" checked />
								<span>${__("Incluir POS en curso")}</span>
							</label>
						</div>
					</div>
					<div class="rt-db-filter-bottom">
						<div class="rt-db-quick-ranges">
							<button type="button" class="rt-db-quick-btn" data-range="today">${__("Hoy")}</button>
							<button type="button" class="rt-db-quick-btn" data-range="7d">${__("Últimos 7 días")}</button>
							<button type="button" class="rt-db-quick-btn active" data-range="30d">${__("Últimos 30 días")}</button>
							<button type="button" class="rt-db-quick-btn" data-range="this_month">${__("Este Mes")}</button>
							<button type="button" class="rt-db-quick-btn" data-range="last_month">${__("Mes Anterior")}</button>
							<button type="button" class="rt-db-quick-btn" data-range="ytd">${__("Este Año")}</button>
						</div>
						<div class="rt-db-period-note" id="rt-db-period-note"></div>
					</div>
				</div>

				<!-- 6 Tarjetas KPI Ejecutivas -->
				<div class="rt-db-kpi-grid" id="rt-db-kpi-grid"></div>

				<!-- Sección 1: Estados Financieros -->
				<div class="rt-db-section-header">
					<h3 class="rt-db-section-title">${__("1. Panorama Financiero Contable (Balance General y Estado de Resultados)")}</h3>
					<span class="rt-db-section-subtitle">${__("Estructura patrimonial al corte y cascada de rentabilidad del período")}</span>
				</div>
				<div class="rt-db-grid-2">
					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Balance General (Activo vs. Pasivo y Patrimonio)")}</h4>
								<div class="rt-db-card-subtitle" id="rt-db-bs-subtitle">${__("Gráfico ECharts Bar Stack: Activo en barra izquierda y Pasivo + Patrimonio en barra derecha")}</div>
							</div>
						</div>
						<div id="rt-chart-balance" class="rt-db-chart-box tall"></div>
						<div class="rt-db-fin-summary" id="rt-db-bs-footer"></div>
					</div>

					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Estado de Resultados y Estructura de Gastos")}</h4>
								<div class="rt-db-card-subtitle">${__("Conversión de Ingresos en Utilidad Neta y principales cuentas de gasto")}</div>
							</div>
							<div class="rt-db-segmented" id="rt-db-pnl-toggle">
								<button type="button" class="rt-db-seg-btn active" data-mode="waterfall">${__("Estado de Resultados")}</button>
								<button type="button" class="rt-db-seg-btn" data-mode="expenses">${__("Desglose de Gastos")}</button>
							</div>
						</div>
						<div id="rt-chart-pnl" class="rt-db-chart-box tall"></div>
						<div class="rt-db-fin-summary" id="rt-db-pnl-footer"></div>
					</div>
				</div>

				<!-- Sección 2: Desempeño Comercial y Ventas -->
				<div class="rt-db-section-header">
					<h3 class="rt-db-section-title">${__("2. Desempeño Comercial, Categorías y Medios de Pago")}</h3>
					<span class="rt-db-section-subtitle">${__("Tendencia diaria de facturación, margen bruto, ranking de productos y recaudación")}</span>
				</div>
				<div class="rt-db-grid-65-35">
					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Evolución Diaria de Ventas, Utilidad Bruta y Margen (%)")}</h4>
								<div class="rt-db-card-subtitle">${__("Use la barra inferior o rueda del ratón para hacer zoom en días específicos")}</div>
							</div>
						</div>
						<div id="rt-chart-daily" class="rt-db-chart-box"></div>
					</div>

					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Participación de Ventas por Categoría")}</h4>
								<div class="rt-db-card-subtitle">${__("Distribución de ingresos netos por Grupo de Artículo")}</div>
							</div>
						</div>
						<div id="rt-chart-category" class="rt-db-chart-box"></div>
					</div>
				</div>

				<div class="rt-db-grid-65-35">
					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Top 10 Productos Estrella")}</h4>
								<div class="rt-db-card-subtitle">${__("Haga clic en una barra para inspeccionar el artículo en detalle")}</div>
							</div>
							<div class="rt-db-segmented" id="rt-db-top-toggle">
								<button type="button" class="rt-db-seg-btn active" data-mode="by_revenue">${__("Por Ingresos")}</button>
								<button type="button" class="rt-db-seg-btn" data-mode="by_profit">${__("Por Utilidad")}</button>
								<button type="button" class="rt-db-seg-btn" data-mode="by_qty">${__("Por Unidades")}</button>
							</div>
						</div>
						<div id="rt-chart-top-items" class="rt-db-chart-box"></div>
					</div>

					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Arqueo por Método de Pago")}</h4>
								<div class="rt-db-card-subtitle">${__("Efectivo, tarjetas, transferencias y crédito pendiente")}</div>
							</div>
						</div>
						<div id="rt-chart-payments" class="rt-db-chart-box"></div>
					</div>
				</div>

				<!-- Sección 3: Operación e Inventario -->
				<div class="rt-db-section-header">
					<h3 class="rt-db-section-title">${__("3. Inteligencia Operativa y Salud de Inventario")}</h3>
					<span class="rt-db-section-subtitle">${__("Horarios pico en tienda y relación entre capital inmovilizado en bodega vs. ventas")}</span>
				</div>
				<div class="rt-db-grid-2">
					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Mapa de Calor de Ventas (Día de la Semana vs. Hora)")}</h4>
								<div class="rt-db-card-subtitle">${__("Identifique las horas de mayor tráfico para optimizar turnos de personal y caja")}</div>
							</div>
						</div>
						<div id="rt-chart-heatmap" class="rt-db-chart-box"></div>
					</div>

					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Capital en Stock (Costo) vs. Ventas por Categoría")}</h4>
								<div class="rt-db-card-subtitle">${__("Detecte categorías sobrestockeadas frente a las de mayor rotación")}</div>
							</div>
						</div>
						<div id="rt-chart-stock-vs-sales" class="rt-db-chart-box"></div>
					</div>
				</div>

				<!-- Sección 4: Alertas Operativas -->
				<div class="rt-db-section-header">
					<h3 class="rt-db-section-title">${__("4. Alertas Accionables de Reposición y Capital Inmovilizado")}</h3>
					<span class="rt-db-section-subtitle">${__("Prevención de quiebres de stock en productos estrella y liquidación de mercadería lenta")}</span>
				</div>
				<div class="rt-db-grid-2">
					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Alerta de Reposición (Productos con Venta y Bajo Stock)")}</h4>
								<div class="rt-db-card-subtitle">${__("Artículos vendidos en los últimos 30 días con cobertura menor a 7 días o agotados")}</div>
							</div>
						</div>
						<div class="rt-db-table-wrap" id="rt-db-low-stock-wrap"></div>
					</div>

					<div class="rt-db-card">
						<div class="rt-db-card-header">
							<div>
								<h4 class="rt-db-card-title">${__("Inventario Estancado (+60 Días sin Venta)")}</h4>
								<div class="rt-db-card-subtitle">${__("Artículos con stock positivo ordenados por mayor capital inmovilizado")}</div>
							</div>
						</div>
						<div class="rt-db-table-wrap" id="rt-db-dead-stock-wrap"></div>
					</div>
				</div>

				<!-- Sección 5: Tabla Final de Indicadores -->
				<div class="rt-db-section-header">
					<h3 class="rt-db-section-title">${__("5. Tabla Ejecutiva de Indicadores Financieros y Operativos")}</h3>
					<span class="rt-db-section-subtitle">${__("Resumen integral de ratios de rentabilidad, liquidez, solvencia y rotación de tienda")}</span>
				</div>
				<div class="rt-db-card">
					<div class="rt-db-card-header">
						<div>
							<h4 class="rt-db-card-title">${__("Tablero de Indicadores Clave para el Dueño de Negocio")}</h4>
							<div class="rt-db-card-subtitle">${__("Evaluación automática con semáforo frente a metas recomendadas de retail y período anterior")}</div>
						</div>
						<div class="rt-db-segmented" id="rt-db-ind-filter">
							<button type="button" class="rt-db-seg-btn active" data-cat="all">${__("Todos")}</button>
							<button type="button" class="rt-db-seg-btn" data-cat="Rentabilidad">${__("Rentabilidad")}</button>
							<button type="button" class="rt-db-seg-btn" data-cat="Liquidez y Solvencia">${__("Liquidez y Solvencia")}</button>
							<button type="button" class="rt-db-seg-btn" data-cat="Inventario y Operación">${__("Inventario y Operación")}</button>
						</div>
					</div>
					<div class="rt-db-table-wrap">
						<table class="rt-db-table">
							<thead>
								<tr>
									<th>${__("Categoría")}</th>
									<th>${__("Indicador")}</th>
									<th>${__("Fórmula / Base de Cálculo")}</th>
									<th style="text-align:right;">${__("Valor Actual")}</th>
									<th>${__("Referencia / Meta")}</th>
									<th style="text-align:center;">${__("Estado")}</th>
								</tr>
							</thead>
							<tbody id="rt-db-indicators-tbody"></tbody>
						</table>
					</div>
				</div>
			</div>
		`);

		this.bindEvents();
	}

	bindEvents() {
		const self = this;

		this.$container.on("change", "#rt-db-company", function () {
			self.onCompanyChange($(this).val());
		});

		this.$container.on(
			"change",
			"#rt-db-warehouse, #rt-db-from-date, #rt-db-to-date, #rt-db-include-pos",
			function () {
				self.refreshData();
			}
		);

		this.$container.on("click", ".rt-db-quick-btn", function () {
			const $btn = $(this);
			self.$container.find(".rt-db-quick-btn").removeClass("active");
			$btn.addClass("active");
			self.applyQuickRange($btn.data("range"));
		});

		this.$container.on("click", "#rt-db-pnl-toggle .rt-db-seg-btn", function () {
			const $btn = $(this);
			self.$container.find("#rt-db-pnl-toggle .rt-db-seg-btn").removeClass("active");
			$btn.addClass("active");
			self.pnlMode = $btn.data("mode");
			if (self.payload) {
				self.renderPnlChart(self.payload.financials.income_statement);
			}
		});

		this.$container.on("click", "#rt-db-top-toggle .rt-db-seg-btn", function () {
			const $btn = $(this);
			self.$container.find("#rt-db-top-toggle .rt-db-seg-btn").removeClass("active");
			$btn.addClass("active");
			self.topItemsMode = $btn.data("mode");
			if (self.payload) {
				self.renderTopItemsChart(self.payload.charts.top_items);
			}
		});

		this.$container.on("click", "#rt-db-ind-filter .rt-db-seg-btn", function () {
			const $btn = $(this);
			self.$container.find("#rt-db-ind-filter .rt-db-seg-btn").removeClass("active");
			$btn.addClass("active");
			self.indicatorFilter = $btn.data("cat");
			if (self.payload) {
				self.renderIndicatorsTable(self.payload.indicators_table || []);
			}
		});
	}

	bindWindowResize() {
		this._resizeHandler = () => this.resizeAllCharts();
		window.addEventListener("resize", this._resizeHandler);
	}

	resizeAllCharts() {
		Object.values(this.charts).forEach((chart) => {
			if (chart && typeof chart.resize === "function") {
				chart.resize();
			}
		});
	}

	async ensureECharts() {
		if (window.echarts) {
			return window.echarts;
		}
		await new Promise((resolve) => {
			frappe.require(["/assets/retail_tools/js/echarts.min.js"], () => resolve());
		});
		if (window.echarts) {
			return window.echarts;
		}
		// Fallback to CDN if assets symlink is not yet refreshed
		await new Promise((resolve, reject) => {
			const s = document.createElement("script");
			s.src = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js";
			s.onload = () => resolve();
			s.onerror = (err) => reject(err);
			document.head.appendChild(s);
		});
		return window.echarts;
	}

	async init() {
		try {
			await this.ensureECharts();
			const res = await frappe.call({
				method: "retail_tools.retail_tools.page.store_dashboard.store_dashboard.get_dashboard_defaults",
			});
			const defaults = (res && res.message) || {};
			this.populateDefaults(defaults);
			await this.refreshData();
		} catch (e) {
			console.error("Error inicializando Store Dashboard:", e);
			frappe.msgprint({
				title: __("Error"),
				indicator: "red",
				message: __("No se pudo inicializar el Panel de Control de Tienda."),
			});
		}
	}

	populateDefaults(defaults) {
		this.currency = defaults.currency || "USD";
		this.currencySymbol = defaults.currency_symbol || "$";

		const $company = this.$container.find("#rt-db-company");
		$company.empty();
		(defaults.companies || []).forEach((c) => {
			const selected = c.name === defaults.company ? "selected" : "";
			$company.append(
				`<option value="${frappe.utils.escape_html(c.name)}" ${selected}>${frappe.utils.escape_html(
					c.company_name || c.name
				)}</option>`
			);
		});

		this.populateWarehouses(defaults.warehouses || []);
		this.$container.find("#rt-db-from-date").val(defaults.default_from_date || frappe.datetime.add_days(frappe.datetime.get_today(), -29));
		this.$container.find("#rt-db-to-date").val(defaults.default_to_date || frappe.datetime.get_today());
	}

	populateWarehouses(warehouses) {
		const $wh = this.$container.find("#rt-db-warehouse");
		$wh.html(`<option value="">${__("Todos los almacenes")}</option>`);
		warehouses.forEach((w) => {
			$wh.append(
				`<option value="${frappe.utils.escape_html(w.name)}">${frappe.utils.escape_html(
					w.warehouse_name || w.name
				)}</option>`
			);
		});
	}

	async onCompanyChange(company) {
		try {
			const res = await frappe.call({
				method: "retail_tools.retail_tools.page.store_dashboard.store_dashboard.get_dashboard_defaults",
				args: { company },
			});
			const defaults = (res && res.message) || {};
			this.currency = defaults.currency || this.currency;
			this.currencySymbol = defaults.currency_symbol || this.currencySymbol;
			this.populateWarehouses(defaults.warehouses || []);
			await this.refreshData();
		} catch (e) {
			console.error(e);
		}
	}

	applyQuickRange(rangeKey) {
		const today = frappe.datetime.get_today();
		let fromDate = today;
		let toDate = today;

		if (rangeKey === "today") {
			fromDate = today;
			toDate = today;
		} else if (rangeKey === "7d") {
			fromDate = frappe.datetime.add_days(today, -6);
			toDate = today;
		} else if (rangeKey === "30d") {
			fromDate = frappe.datetime.add_days(today, -29);
			toDate = today;
		} else if (rangeKey === "this_month") {
			fromDate = frappe.datetime.month_start(today);
			toDate = today;
		} else if (rangeKey === "last_month") {
			const firstThisMonth = frappe.datetime.month_start(today);
			toDate = frappe.datetime.add_days(firstThisMonth, -1);
			fromDate = frappe.datetime.month_start(toDate);
		} else if (rangeKey === "ytd") {
			fromDate = frappe.datetime.year_start(today);
			toDate = today;
		}

		this.$container.find("#rt-db-from-date").val(fromDate);
		this.$container.find("#rt-db-to-date").val(toDate);
		this.refreshData();
	}

	async refreshData() {
		const company = this.$container.find("#rt-db-company").val();
		const warehouse = this.$container.find("#rt-db-warehouse").val();
		const from_date = this.$container.find("#rt-db-from-date").val();
		const to_date = this.$container.find("#rt-db-to-date").val();
		const include_pending_pos = this.$container.find("#rt-db-include-pos").is(":checked") ? 1 : 0;

		try {
			const res = await frappe.call({
				method: "retail_tools.retail_tools.page.store_dashboard.store_dashboard.get_store_dashboard_data",
				args: {
					company,
					warehouse,
					from_date,
					to_date,
					include_pending_pos,
				},
				freeze: false,
			});

			const data = (res && res.message) || null;
			if (!data) return;

			this.payload = data;
			this.currency = (data.filters && data.filters.currency) || this.currency;
			this.currencySymbol = (data.filters && data.filters.currency_symbol) || this.currencySymbol;

			this.renderPeriodNote(data.filters);
			this.renderKpiCards(data.kpis);
			this.renderBalanceSheetChart(data.financials.balance_sheet);
			this.renderPnlChart(data.financials.income_statement);
			this.renderDailyTrendChart(data.charts.daily_trend);
			this.renderCategoryChart(data.charts.by_category);
			this.renderTopItemsChart(data.charts.top_items);
			this.renderPaymentsChart(data.charts.payment_methods);
			this.renderHeatmapChart(data.charts.hourly_heatmap);
			this.renderStockVsSalesChart(data.charts.by_category);
			this.renderAlertTables(data.alerts);
			this.renderIndicatorsTable(data.indicators_table);
		} catch (e) {
			console.error("Error cargando datos del dashboard:", e);
		}
	}

	fmtMoney(value) {
		const num = Number(value || 0);
		const sign = num < 0 ? "-" : "";
		return `${sign}${this.currencySymbol}\u00a0${Math.abs(num).toLocaleString("en-US", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		})}`;
	}

	fmtCompact(value) {
		const num = Number(value || 0);
		const abs = Math.abs(num);
		const sign = num < 0 ? "-" : "";
		if (abs >= 1e6) {
			return `${sign}${this.currencySymbol}${(abs / 1e6).toFixed(1)}M`;
		}
		if (abs >= 1e3) {
			return `${sign}${this.currencySymbol}${(abs / 1e3).toFixed(1)}k`;
		}
		return `${sign}${this.currencySymbol}${abs.toFixed(0)}`;
	}

	deltaBadgeHtml(pct) {
		const val = Number(pct || 0);
		if (Math.abs(val) < 0.05) {
			return `<span class="rt-db-kpi-delta neutral">0.0%</span>`;
		}
		const cls = val > 0 ? "up" : "down";
		const arrow = val > 0 ? "▲" : "▼";
		return `<span class="rt-db-kpi-delta ${cls}">${arrow} ${Math.abs(val).toFixed(1)}%</span>`;
	}

	getOrCreateChart(domId) {
		const el = document.getElementById(domId);
		if (!el || !window.echarts) return null;
		if (this.charts[domId]) {
			this.charts[domId].dispose();
		}
		const instance = window.echarts.init(el);
		this.charts[domId] = instance;
		return instance;
	}

	renderPeriodNote(filters) {
		if (!filters) return;
		this.$container
			.find("#rt-db-period-note")
			.html(
				`${__("Período analizado")}: <strong>${filters.from_date}</strong> ${__("al")} <strong>${
					filters.to_date
				}</strong> (${filters.period_days} ${__("días")}) · ${__("Comparado contra")}: ${
					filters.prev_from_date
				} ${__("al")} ${filters.prev_to_date}`
			);
	}

	renderKpiCards(kpis) {
		if (!kpis) return;
		const potentialProfit = Math.max(
			0,
			Number(kpis.potential_profit || (Number(kpis.stock_retail_value || 0) - Number(kpis.stock_cost_value || 0)))
		);
		const html = `
			<div class="rt-db-kpi-card" style="--kpi-accent: #2563eb; --kpi-soft: #eff6ff;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Ventas Netas")}</span>
					</div>
					${this.deltaBadgeHtml(kpis.net_sales_delta_pct)}
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.net_sales)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Período Anterior")}</span>
						<span class="rt-db-kpi-metric-val">${this.fmtMoney(kpis.prev_net_sales)}</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Transacciones")}</span>
						<span class="rt-db-kpi-metric-val">${Number(kpis.ticket_count || 0).toLocaleString()} ${__("tickets")}</span>
					</div>
				</div>
			</div>

			<div class="rt-db-kpi-card" style="--kpi-accent: #10b981; --kpi-soft: #ecfdf5;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Utilidad Bruta Comercial")}</span>
					</div>
					${this.deltaBadgeHtml(kpis.gross_profit_delta_pct)}
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.gross_profit)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Margen Bruto Actual")}</span>
						<span class="rt-db-kpi-metric-val" style="color:#059669;">${Number(kpis.gross_margin_pct || 0).toFixed(1)}%</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Margen Anterior")}</span>
						<span class="rt-db-kpi-metric-val">${Number(kpis.prev_gross_margin_pct || 0).toFixed(1)}%</span>
					</div>
				</div>
			</div>

			<div class="rt-db-kpi-card" style="--kpi-accent: #0d9488; --kpi-soft: #f0fdfa;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Utilidad Neta Contable")}</span>
					</div>
					${this.deltaBadgeHtml(kpis.net_profit_delta_pct)}
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.net_profit)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Margen Neto")}</span>
						<span class="rt-db-kpi-metric-val" style="color:#0d9488;">${Number(kpis.net_margin_pct || 0).toFixed(1)}%</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Gastos Operativos")}</span>
						<span class="rt-db-kpi-metric-val">${this.fmtMoney(kpis.operating_expenses)}</span>
					</div>
				</div>
			</div>

			<div class="rt-db-kpi-card" style="--kpi-accent: #8b5cf6; --kpi-soft: #f5f3ff;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Ticket Promedio")}</span>
					</div>
					${this.deltaBadgeHtml(kpis.avg_ticket_delta_pct)}
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.avg_ticket)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Unid. por Ticket (UPT)")}</span>
						<span class="rt-db-kpi-metric-val">${Number(kpis.upt || 0).toFixed(2)} ${__("u/ticket")}</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Unidades Vendidas")}</span>
						<span class="rt-db-kpi-metric-val">${Number(kpis.total_units || 0).toLocaleString()} ${__("unid.")}</span>
					</div>
				</div>
			</div>

			<div class="rt-db-kpi-card" style="--kpi-accent: #f59e0b; --kpi-soft: #fffbeb;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Capital en Inventario")}</span>
					</div>
					<span class="rt-db-kpi-delta neutral">${Number(kpis.sku_with_stock || 0).toLocaleString()} SKUs</span>
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.stock_cost_value)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Venta Potencial")}</span>
						<span class="rt-db-kpi-metric-val">${this.fmtMoney(kpis.stock_retail_value)}</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Ganancia Potencial")}</span>
						<span class="rt-db-kpi-metric-val" style="color:#d97706;">${this.fmtMoney(potentialProfit)}</span>
					</div>
				</div>
			</div>

			<div class="rt-db-kpi-card" style="--kpi-accent: #0284c7; --kpi-soft: #f0f9ff;">
				<div class="rt-db-kpi-head">
					<div class="rt-db-kpi-head-left">
						<span class="rt-db-kpi-icon">
							<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"/></svg>
						</span>
						<span class="rt-db-kpi-title">${__("Efectivo y Bancos")}</span>
					</div>
					<span class="rt-db-kpi-delta neutral">${__("Al Corte")}</span>
				</div>
				<div class="rt-db-kpi-value">${this.fmtMoney(kpis.cash_and_bank)}</div>
				<div class="rt-db-kpi-footer">
					<div class="rt-db-kpi-metric">
						<span class="rt-db-kpi-metric-label">${__("Por Cobrar (CxC)")}</span>
						<span class="rt-db-kpi-metric-val">${this.fmtMoney(kpis.accounts_receivable)}</span>
					</div>
					<div class="rt-db-kpi-metric" style="text-align:right;">
						<span class="rt-db-kpi-metric-label">${__("Por Pagar (CxP)")}</span>
						<span class="rt-db-kpi-metric-val" style="color:#dc2626;">${this.fmtMoney(kpis.accounts_payable)}</span>
					</div>
				</div>
			</div>
		`;
		this.$container.find("#rt-db-kpi-grid").html(html);
	}

	/**
	 * 1. Balance Sheet Chart (ECharts bar-stack)
	 * Left bar = Activo (index 0)
	 * Right bar = Pasivo y Patrimonio (index 1)
	 * Both bars share stack: "balance" and barWidth: "45%" so both columns have identical thickness and are centered.
	 */
	renderBalanceSheetChart(bs) {
		const chart = this.getOrCreateChart("rt-chart-balance");
		if (!chart || !bs) return;

		const self = this;
		const categories = [__("Activo"), __("Pasivo y Patrimonio")];

		const cashVal = Math.max(0, Number(bs.cash_and_bank || 0));
		const arVal = Math.max(0, Number(bs.accounts_receivable || 0));
		const invVal = Math.max(0, Number(bs.inventory || 0));
		const otherAssetVal = Math.max(0, Number(bs.other_assets || 0));

		const apVal = Math.max(0, Number(bs.accounts_payable || 0));
		const otherLiabVal = Math.max(0, Number(bs.other_liabilities || 0));
		const equityCapVal = Math.max(0, Number(bs.equity_capital || 0));
		const retainedVal = Math.max(0, Number(bs.retained_and_current_earnings || 0));

		const sharedBarWidth = "45%";
		const sharedBarMaxWidth = 110;

		const seriesDefs = [
			// Barra Izquierda: Activo (index 0)
			{
				name: __("Efectivo y Bancos"),
				side: 0,
				color: "#2563eb",
				data: [cashVal, 0],
			},
			{
				name: __("Cuentas por Cobrar"),
				side: 0,
				color: "#3b82f6",
				data: [arVal, 0],
			},
			{
				name: __("Inventario de Mercadería"),
				side: 0,
				color: "#06b6d4",
				data: [invVal, 0],
			},
			{
				name: __("Otros Activos / Fijos"),
				side: 0,
				color: "#6366f1",
				data: [otherAssetVal, 0],
			},
			// Barra Derecha: Pasivo y Patrimonio (index 1)
			{
				name: __("Cuentas por Pagar"),
				side: 1,
				color: "#f97316",
				data: [0, apVal],
			},
			{
				name: __("Impuestos y Otros Pasivos"),
				side: 1,
				color: "#fbbf24",
				data: [0, otherLiabVal],
			},
			{
				name: __("Capital / Patrimonio"),
				side: 1,
				color: "#10b981",
				data: [0, equityCapVal],
			},
			{
				name: __("Utilidad Acumulada y Ejercicio"),
				side: 1,
				color: "#059669",
				data: [0, retainedVal],
			},
		];

		const series = seriesDefs.map((s) => ({
			name: s.name,
			type: "bar",
			stack: "balance",
			barWidth: sharedBarWidth,
			barMaxWidth: sharedBarMaxWidth,
			emphasis: { focus: "series" },
			itemStyle: {
				color: s.color,
			},
			label: {
				show: true,
				position: "inside",
				color: "#ffffff",
				fontWeight: 600,
				fontSize: 11,
				formatter: (params) => {
					const val = Number(params.value || 0);
					return val > 0 ? self.fmtCompact(val) : "";
				},
			},
			data: s.data,
		}));

		chart.setOption({
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (params) => {
					if (!params || !params.length) return "";
					const dataIndex = params[0].dataIndex;
					const colTitle = categories[dataIndex];
					let sum = 0;
					const lines = [];
					params.forEach((p) => {
						const val = Number(p.value || 0);
						if (val > 0) {
							sum += val;
							lines.push(
								`<div style="display:flex;justify-content:space-between;gap:16px;margin:3px 0;">
									<span>${p.marker} ${frappe.utils.escape_html(p.seriesName)}</span>
									<strong>${self.fmtMoney(val)}</strong>
								</div>`
							);
						}
					});
					lines.push(
						`<div style="border-top:1px solid #cbd5e1;margin-top:6px;padding-top:4px;display:flex;justify-content:space-between;gap:16px;">
							<span><strong>Total ${frappe.utils.escape_html(colTitle)}</strong></span>
							<strong>${self.fmtMoney(sum)}</strong>
						</div>`
					);
					return `<div style="min-width:230px;"><div style="font-weight:700;margin-bottom:6px;">${frappe.utils.escape_html(
						colTitle
					)}</div>${lines.join("")}</div>`;
				},
			},
			legend: {
				bottom: 0,
				type: "scroll",
				itemWidth: 12,
				itemHeight: 12,
				textStyle: { fontSize: 11 },
			},
			grid: {
				top: 24,
				left: "4%",
				right: "4%",
				bottom: 46,
				containLabel: true,
			},
			xAxis: [
				{
					type: "category",
					data: categories,
					axisTick: { alignWithLabel: true },
					axisLabel: {
						fontWeight: 700,
						fontSize: 13,
						color: "#0f172a",
					},
				},
			],
			yAxis: [
				{
					type: "value",
					axisLabel: {
						formatter: (v) => self.fmtCompact(v),
					},
					splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
				},
			],
			series,
		});

		this.$container.find("#rt-db-bs-footer").html(`
			<span><strong>${__("Total Activo")}:</strong> ${this.fmtMoney(bs.total_assets)}</span>
			<span><strong>${__("Total Pasivo")}:</strong> ${this.fmtMoney(bs.total_liabilities)}</span>
			<span><strong>${__("Total Patrimonio")}:</strong> ${this.fmtMoney(bs.total_equity)}</span>
		`);
	}

	/**
	 * 2. Income Statement Chart (Waterfall or Expense Breakdown)
	 */
	renderPnlChart(pnl) {
		const chart = this.getOrCreateChart("rt-chart-pnl");
		if (!chart || !pnl) return;

		const self = this;

		if (this.pnlMode === "expenses") {
			const breakdown = pnl.expense_breakdown || [];
			const labels = breakdown.map((d) => d.account).reverse();
			const values = breakdown.map((d) => Number(d.amount || 0)).reverse();

			chart.setOption({
				tooltip: {
					trigger: "axis",
					axisPointer: { type: "shadow" },
					formatter: (params) => {
						const p = params[0];
						if (!p) return "";
						return `<strong>${frappe.utils.escape_html(p.name)}</strong><br/>${self.fmtMoney(
							p.value
						)}`;
					},
				},
				grid: { top: 20, left: "4%", right: "8%", bottom: 20, containLabel: true },
				xAxis: {
					type: "value",
					axisLabel: { formatter: (v) => self.fmtCompact(v) },
					splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
				},
				yAxis: {
					type: "category",
					data: labels.length ? labels : [__("Sin gastos registrados")],
					axisLabel: { width: 150, overflow: "truncate" },
				},
				series: [
					{
						name: __("Gasto"),
						type: "bar",
						barMaxWidth: 32,
						itemStyle: { color: "#f97316", borderRadius: [0, 6, 6, 0] },
						label: {
							show: true,
							position: "right",
							formatter: (p) => self.fmtCompact(p.value),
						},
						data: values.length ? values : [0],
					},
				],
			});
		} else {
			// Waterfall chart: Ingresos -> (- Costo de Ventas) -> Utilidad Bruta -> (- Gastos Operativos) -> Utilidad Neta
			const income = Number(pnl.total_income || 0);
			const cogs = Number(pnl.cogs || 0);
			const gross = Number(pnl.gross_profit || 0);
			const opex = Number(pnl.operating_expenses || 0);
			const net = Number(pnl.net_profit || 0);

			const categories = [
				__("Ingresos"),
				__("- Costo Ventas"),
				__("= Utilidad Bruta"),
				__("- Gastos Oper."),
				__("= Utilidad Neta"),
			];

			// Base transparent offset for waterfall steps
			const helperBase = [
				0,
				Math.max(0, gross),
				0,
				Math.max(0, net),
				0,
			];

			const barValues = [
				{ value: income, itemStyle: { color: "#2563eb", borderRadius: [6, 6, 0, 0] }, raw: income },
				{ value: cogs, itemStyle: { color: "#f59e0b", borderRadius: [6, 6, 0, 0] }, raw: -cogs },
				{ value: gross, itemStyle: { color: "#0ea5e9", borderRadius: [6, 6, 0, 0] }, raw: gross },
				{ value: opex, itemStyle: { color: "#f97316", borderRadius: [6, 6, 0, 0] }, raw: -opex },
				{
					value: net,
					itemStyle: {
						color: net >= 0 ? "#10b981" : "#ef4444",
						borderRadius: [6, 6, 0, 0],
					},
					raw: net,
				},
			];

			chart.setOption({
				tooltip: {
					trigger: "axis",
					axisPointer: { type: "shadow" },
					formatter: (params) => {
						const valSeries = params.find((p) => p.seriesName === __("Monto"));
						if (!valSeries) return "";
						const rawVal = valSeries.data && valSeries.data.raw !== undefined ? valSeries.data.raw : valSeries.value;
						return `<strong>${frappe.utils.escape_html(
							valSeries.name
						)}</strong><br/>${self.fmtMoney(rawVal)}`;
					},
				},
				grid: {
					top: 28,
					left: "4%",
					right: "4%",
					bottom: 24,
					containLabel: true,
				},
				xAxis: {
					type: "category",
					data: categories,
					axisLabel: { interval: 0, fontWeight: 600, fontSize: 11.5 },
				},
				yAxis: {
					type: "value",
					axisLabel: { formatter: (v) => self.fmtCompact(v) },
					splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
				},
				series: [
					{
						name: "Base",
						type: "bar",
						stack: "pnl_waterfall",
						silent: true,
						itemStyle: { borderColor: "transparent", color: "transparent" },
						emphasis: { itemStyle: { borderColor: "transparent", color: "transparent" } },
						data: helperBase,
					},
					{
						name: __("Monto"),
						type: "bar",
						stack: "pnl_waterfall",
						barWidth: "48%",
						barMaxWidth: 74,
						label: {
							show: true,
							position: "top",
							fontWeight: 700,
							fontSize: 11,
							formatter: (p) => self.fmtCompact(p.data.raw),
						},
						data: barValues,
					},
				],
			});
		}

		this.$container.find("#rt-db-pnl-footer").html(`
			<span><strong>${__("Ingresos")}:</strong> ${this.fmtMoney(pnl.total_income)}</span>
			<span><strong>${__("Utilidad Bruta")}:</strong> ${this.fmtMoney(pnl.gross_profit)}</span>
			<span><strong>${__("Utilidad Neta")}:</strong> ${this.fmtMoney(pnl.net_profit)} (${Number(
			pnl.net_margin_pct || 0
		).toFixed(1)}%)</span>
		`);
	}

	/**
	 * 3. Daily Trend Chart (Mixed Line & Bar + DataZoom)
	 * Shows POS Sales + Direct Invoice Sales (without duplicating consolidated POS invoices),
	 * alongside Gross Profit and Gross Margin %.
	 */
	renderDailyTrendChart(daily) {
		const chart = this.getOrCreateChart("rt-chart-daily");
		if (!chart || !daily) return;
		const self = this;

		const hasChannelSplit = Array.isArray(daily.pos_sales) && Array.isArray(daily.direct_sales);
		const salesArr = daily.sales || [];
		const marginData = (daily.margin_pct || []).map((val, idx) => {
			if (val === null || val === undefined) return null;
			if (Math.abs(Number(salesArr[idx] || 0)) < 1e-9) return null;
			return val;
		});

		chart.setOption({
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "cross" },
			},
			legend: {
				top: 0,
				data: hasChannelSplit
					? [
							__("Ventas POS"),
							__("Factura Normal"),
							__("Utilidad Bruta"),
							__("Margen Bruto (%)"),
					  ]
					: [__("Ventas Netas"), __("Utilidad Bruta"), __("Margen Bruto (%)")],
			},
			grid: { top: 36, left: "4%", right: "4%", bottom: 52, containLabel: true },
			dataZoom: [
				{ type: "inside", start: 0, end: 100 },
				{ type: "slider", height: 18, bottom: 8, start: 0, end: 100 },
			],
			xAxis: [
				{
					type: "category",
					data: daily.dates || [],
					axisPointer: { type: "shadow" },
				},
			],
			yAxis: [
				{
					type: "value",
					name: __("Monto"),
					axisLabel: { formatter: (v) => self.fmtCompact(v) },
					splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
				},
				{
					type: "value",
					name: "%",
					axisLabel: { formatter: "{value}%" },
					splitLine: { show: false },
				},
			],
			series: hasChannelSplit
				? [
						{
							name: __("Ventas POS"),
							type: "bar",
							stack: "ventas_diarias",
							barMaxWidth: 26,
							itemStyle: { color: "#2563eb" },
							data: daily.pos_sales || [],
						},
						{
							name: __("Factura Normal"),
							type: "bar",
							stack: "ventas_diarias",
							barMaxWidth: 26,
							itemStyle: { color: "#6366f1", borderRadius: [4, 4, 0, 0] },
							data: daily.direct_sales || [],
						},
						{
							name: __("Utilidad Bruta"),
							type: "bar",
							barMaxWidth: 26,
							itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] },
							data: daily.profit || [],
						},
						{
							name: __("Margen Bruto (%)"),
							type: "line",
							yAxisIndex: 1,
							smooth: true,
							connectNulls: true,
							symbolSize: 6,
							itemStyle: { color: "#f59e0b" },
							lineStyle: { width: 2.5 },
							data: marginData,
						},
				  ]
				: [
						{
							name: __("Ventas Netas"),
							type: "bar",
							barMaxWidth: 28,
							itemStyle: { color: "#3b82f6", borderRadius: [4, 4, 0, 0] },
							data: daily.sales || [],
						},
						{
							name: __("Utilidad Bruta"),
							type: "bar",
							barMaxWidth: 28,
							itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] },
							data: daily.profit || [],
						},
						{
							name: __("Margen Bruto (%)"),
							type: "line",
							yAxisIndex: 1,
							smooth: true,
							connectNulls: true,
							symbolSize: 6,
							itemStyle: { color: "#f59e0b" },
							lineStyle: { width: 2.5 },
							data: marginData,
						},
				  ],
		});
	}

	/**
	 * 4. Sales by Category (Nightingale Rose Chart)
	 */
	renderCategoryChart(byCategory) {
		const chart = this.getOrCreateChart("rt-chart-category");
		if (!chart) return;
		const self = this;

		const pieData = (byCategory || [])
			.filter((c) => Number(c.sales || 0) > 0)
			.slice(0, 8)
			.map((c) => ({
				name: c.item_group,
				value: Number(c.sales || 0),
			}));

		chart.setOption({
			tooltip: {
				trigger: "item",
				formatter: (p) =>
					`<strong>${frappe.utils.escape_html(p.name)}</strong><br/>${self.fmtMoney(
						p.value
					)} (${p.percent}%)`,
			},
			legend: {
				bottom: 0,
				type: "scroll",
			},
			series: [
				{
					name: __("Categoría"),
					type: "pie",
					radius: ["22%", "68%"],
					center: ["50%", "45%"],
					roseType: "radius",
					itemStyle: {
						borderRadius: 6,
						borderColor: "#fff",
						borderWidth: 2,
					},
					data: pieData.length
						? pieData
						: [{ name: __("Sin ventas en el período"), value: 0 }],
				},
			],
		});
	}

	/**
	 * 5. Top 10 Products (Horizontal Bar Chart + click to Item Inspector)
	 */
	renderTopItemsChart(topItems) {
		const chart = this.getOrCreateChart("rt-chart-top-items");
		if (!chart || !topItems) return;
		const self = this;

		const list = (topItems[this.topItemsMode] || []).slice(0, 10).reverse();
		const isQty = this.topItemsMode === "by_qty";
		const field =
			this.topItemsMode === "by_profit"
				? "profit"
				: this.topItemsMode === "by_qty"
				? "qty"
				: "revenue";

		const barColor =
			this.topItemsMode === "by_profit"
				? "#10b981"
				: this.topItemsMode === "by_qty"
				? "#8b5cf6"
				: "#2563eb";

		chart.setOption({
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (params) => {
					const p = params[0];
					if (!p || !p.data) return "";
					const item = p.data.item;
					if (!item) return "";
					return `
						<div>
							<strong>${frappe.utils.escape_html(item.item_name)}</strong> (${frappe.utils.escape_html(
						item.item_code
					)})<br/>
							${__("Ingresos")}: <strong>${self.fmtMoney(item.revenue)}</strong><br/>
							${__("Utilidad Bruta")}: <strong>${self.fmtMoney(item.profit)}</strong> (${item.margin_pct}%)<br/>
							${__("Unidades")}: <strong>${item.qty}</strong>
						</div>
					`;
				},
			},
			grid: { top: 14, left: "3%", right: "10%", bottom: 18, containLabel: true },
			xAxis: {
				type: "value",
				axisLabel: {
					formatter: (v) => (isQty ? v : self.fmtCompact(v)),
				},
				splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
			},
			yAxis: {
				type: "category",
				data: list.length ? list.map((i) => i.item_name || i.item_code) : [__("Sin datos")],
				axisLabel: { width: 155, overflow: "truncate" },
			},
			series: [
				{
					type: "bar",
					barMaxWidth: 24,
					itemStyle: { color: barColor, borderRadius: [0, 6, 6, 0] },
					label: {
						show: true,
						position: "right",
						formatter: (p) => (isQty ? `${p.value} u.` : self.fmtCompact(p.value)),
					},
					data: list.length
						? list.map((i) => ({ value: Number(i[field] || 0), item: i }))
						: [{ value: 0 }],
				},
			],
		});

		chart.off("click");
		chart.on("click", (params) => {
			if (params && params.data && params.data.item && params.data.item.item_code) {
				frappe.set_route("item-inspector", { item_code: params.data.item.item_code });
			}
		});
	}

	/**
	 * 6. Payment Methods Doughnut Chart
	 */
	renderPaymentsChart(payments) {
		const chart = this.getOrCreateChart("rt-chart-payments");
		if (!chart) return;
		const self = this;

		const list = payments || [];
		const total = list.reduce((acc, r) => acc + Number(r.value || 0), 0);

		chart.setOption({
			tooltip: {
				trigger: "item",
				formatter: (p) =>
					`<strong>${frappe.utils.escape_html(p.name)}</strong><br/>${self.fmtMoney(
						p.value
					)} (${p.percent}%)`,
			},
			legend: { bottom: 0, type: "scroll" },
			series: [
				{
					name: __("Método de Pago"),
					type: "pie",
					radius: ["45%", "70%"],
					center: ["50%", "44%"],
					avoidLabelOverlap: true,
					itemStyle: {
						borderRadius: 6,
						borderColor: "#fff",
						borderWidth: 2,
					},
					label: {
						show: true,
						formatter: "{b}: {d}%",
					},
					data: list.length
						? list
						: [{ name: __("Sin cobros en el período"), value: 0 }],
				},
			],
			graphic: [
				{
					type: "text",
					left: "center",
					top: "40%",
					style: {
						text: `${__("Total")}\n${self.fmtCompact(total)}`,
						textAlign: "center",
						fill: "#0f172a",
						fontSize: 13,
						fontWeight: 700,
					},
				},
			],
		});
	}

	/**
	 * 7. Sales Heatmap (Day of Week x Hour of Day)
	 */
	renderHeatmapChart(heatmap) {
		const chart = this.getOrCreateChart("rt-chart-heatmap");
		if (!chart || !heatmap) return;
		const self = this;

		const rawData = heatmap.data || [];
		const positiveValues = rawData
			.map((r) => Number(r[2] || 0))
			.filter((v) => v > 0);
		const minPositive = positiveValues.length ? Math.min(...positiveValues) : 1;
		const maxVal = Math.max(1, Number(heatmap.max_value || 1));
		const visualMin = positiveValues.length ? Math.max(0.01, minPositive * 0.85) : 1;

		const ticketsMap = heatmap.tickets_by_cell || {};
		const seriesData = rawData.map((r) => {
			const hourIdx = Number(r[0] || 0);
			const dayIdx = Number(r[1] || 0);
			const salesVal = Number(r[2] || 0);
			const tickets = Number(ticketsMap[`${hourIdx}_${dayIdx}`] || r[3] || 0);
			return {
				value: [hourIdx, dayIdx, salesVal],
				tickets,
				label: {
					color: salesVal >= maxVal * 0.35 ? "#ffffff" : "#0f172a",
				},
			};
		});

		chart.setOption({
			tooltip: {
				position: "top",
				formatter: (p) => {
					const val = p.value || [0, 0, 0];
					const tickets = (p.data && p.data.tickets) || 0;
					const hourLabel = (heatmap.hours && heatmap.hours[val[0]]) || `${val[0]}:00`;
					const dayLabel = (heatmap.days && heatmap.days[val[1]]) || "";
					return `<strong>${dayLabel} · ${hourLabel}</strong><br/>${__("Ventas")}: <strong>${self.fmtMoney(
						val[2]
					)}</strong><br/>${__("Tickets")}: <strong>${tickets}</strong>`;
				},
			},
			grid: {
				top: 16,
				left: "3%",
				right: "4%",
				bottom: 52,
				containLabel: true,
			},
			xAxis: {
				type: "category",
				data: heatmap.hours || [],
				splitArea: { show: false },
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "category",
				data: heatmap.days || [],
				splitArea: { show: false },
				axisLabel: { fontWeight: 600, fontSize: 11.5 },
			},
			visualMap: {
				dimension: 2,
				min: visualMin,
				max: Math.max(maxVal, visualMin + 1),
				calculable: true,
				orient: "horizontal",
				left: "center",
				bottom: 0,
				inRange: {
					color: ["#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e3a8a"],
				},
				outOfRange: {
					color: ["#f8fafc"],
				},
				formatter: (value) => self.fmtCompact(value),
			},
			series: [
				{
					name: __("Ventas por Hora"),
					type: "heatmap",
					data: seriesData,
					itemStyle: {
						borderColor: "#ffffff",
						borderWidth: 2,
						borderRadius: 4,
					},
					label: {
						show: true,
						fontSize: 9.5,
						fontWeight: 700,
						color: "#0f172a",
						formatter: (p) => {
							const v = Number((p.value && p.value[2]) || 0);
							return v > 0 ? self.fmtCompact(v) : "";
						},
					},
					emphasis: {
						itemStyle: {
							shadowBlur: 8,
							shadowColor: "rgba(15, 23, 42, 0.35)",
						},
					},
				},
			],
		});
	}

	/**
	 * 8. Inventory Health: Stock Value (Cost) vs Sales by Item Group
	 */
	renderStockVsSalesChart(byCategory) {
		const chart = this.getOrCreateChart("rt-chart-stock-vs-sales");
		if (!chart) return;
		const self = this;

		const topCats = (byCategory || []).slice(0, 8);
		const names = topCats.map((c) => c.item_group);
		const stockVals = topCats.map((c) => Number(c.stock_value || 0));
		const salesVals = topCats.map((c) => Number(c.sales || 0));
		const profitVals = topCats.map((c) => Number(c.profit || 0));

		chart.setOption({
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
			},
			legend: {
				top: 0,
				data: [__("Capital en Stock (Costo)"), __("Ventas del Período"), __("Utilidad Bruta")],
			},
			grid: {
				top: 36,
				left: "4%",
				right: "4%",
				bottom: 24,
				containLabel: true,
			},
			xAxis: {
				type: "category",
				data: names.length ? names : [__("Sin datos")],
				axisLabel: { interval: 0, rotate: names.length > 4 ? 18 : 0 },
			},
			yAxis: {
				type: "value",
				axisLabel: { formatter: (v) => self.fmtCompact(v) },
				splitLine: { lineStyle: { type: "dashed", color: "#e2e8f0" } },
			},
			series: [
				{
					name: __("Capital en Stock (Costo)"),
					type: "bar",
					barMaxWidth: 26,
					itemStyle: { color: "#f59e0b", borderRadius: [4, 4, 0, 0] },
					data: stockVals.length ? stockVals : [0],
				},
				{
					name: __("Ventas del Período"),
					type: "bar",
					barMaxWidth: 26,
					itemStyle: { color: "#2563eb", borderRadius: [4, 4, 0, 0] },
					data: salesVals.length ? salesVals : [0],
				},
				{
					name: __("Utilidad Bruta"),
					type: "bar",
					barMaxWidth: 26,
					itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] },
					data: profitVals.length ? profitVals : [0],
				},
			],
		});
	}

	/**
	 * Operational Alert Tables (Low Stock Stars & Dead Stock)
	 */
	renderAlertTables(alerts) {
		const lowStock = (alerts && alerts.low_stock_stars) || [];
		const deadStock = (alerts && alerts.dead_stock) || [];

		const $lowWrap = this.$container.find("#rt-db-low-stock-wrap");
		if (!lowStock.length) {
			$lowWrap.html(
				`<div class="rt-db-empty">${__("Excelente: No hay productos estrella con riesgo inmediato de quiebre de stock.")}</div>`
			);
		} else {
			const rowsHtml = lowStock
				.map((r) => {
					const badgeCls = r.actual_qty <= 0 ? "danger" : "warning";
					const badgeText =
						r.actual_qty <= 0 ? __("Agotado") : `${r.coverage_days} ${__("días")}`;
					return `
						<tr>
							<td>
								<a href="/app/item-inspector?item_code=${encodeURIComponent(r.item_code)}" style="font-weight:600;color:#2563eb;">
									${frappe.utils.escape_html(r.item_name)}
								</a>
								<div style="font-size:11px;color:#64748b;">${frappe.utils.escape_html(r.item_code)}</div>
							</td>
							<td style="text-align:right;font-weight:700;white-space:nowrap;">${r.actual_qty}</td>
							<td style="text-align:right;white-space:nowrap;">${r.qty_sold_30d}</td>
							<td style="text-align:right;white-space:nowrap;">${this.fmtMoney(r.revenue_30d)}</td>
							<td style="text-align:center;white-space:nowrap;"><span class="rt-db-badge ${badgeCls}">${badgeText}</span></td>
						</tr>
					`;
				})
				.join("");

			$lowWrap.html(`
				<table class="rt-db-table">
					<thead>
						<tr>
							<th>${__("Producto")}</th>
							<th style="text-align:right;">${__("Stock Actual")}</th>
							<th style="text-align:right;">${__("Vendidos (30d)")}</th>
							<th style="text-align:right;">${__("Venta (30d)")}</th>
							<th style="text-align:center;">${__("Cobertura")}</th>
						</tr>
					</thead>
					<tbody>${rowsHtml}</tbody>
				</table>
			`);
		}

		const $deadWrap = this.$container.find("#rt-db-dead-stock-wrap");
		if (!deadStock.length) {
			$deadWrap.html(
				`<div class="rt-db-empty">${__("Sin mercadería estancada (+60 días sin venta) en los almacenes seleccionados.")}</div>`
			);
		} else {
			const rowsHtml = deadStock
				.map((r) => {
					const daysLabel =
						r.days_without_sale === null || r.days_without_sale === undefined
							? __("Nunca vendido")
							: `${r.days_without_sale} ${__("días")}`;
					const lastSaleFormatted = frappe.utils
						.escape_html(r.last_sale_date || "")
						.replace(/-/g, "\u2011");
					return `
						<tr>
							<td>
								<a href="/app/item-inspector?item_code=${encodeURIComponent(r.item_code)}" style="font-weight:600;color:#2563eb;">
									${frappe.utils.escape_html(r.item_name)}
								</a>
								<div style="font-size:11px;color:#64748b;">${frappe.utils.escape_html(r.item_code)}</div>
							</td>
							<td style="text-align:right;white-space:nowrap;">${r.actual_qty}</td>
							<td style="text-align:right;font-weight:700;white-space:nowrap;">${this.fmtMoney(r.stock_value)}</td>
							<td style="white-space:nowrap;min-width:96px;">${lastSaleFormatted}</td>
							<td style="text-align:center;white-space:nowrap;"><span class="rt-db-badge warning">${daysLabel}</span></td>
						</tr>
					`;
				})
				.join("");

			$deadWrap.html(`
				<table class="rt-db-table">
					<thead>
						<tr>
							<th>${__("Producto")}</th>
							<th style="text-align:right;white-space:nowrap;">${__("Stock")}</th>
							<th style="text-align:right;white-space:nowrap;">${__("Capital en Stock")}</th>
							<th style="white-space:nowrap;min-width:96px;">${__("Última Venta")}</th>
							<th style="text-align:center;white-space:nowrap;">${__("Inactividad")}</th>
						</tr>
					</thead>
					<tbody>${rowsHtml}</tbody>
				</table>
			`);
		}
	}

	/**
	 * Final Executive Indicators Table at the bottom of the page
	 */
	renderIndicatorsTable(indicators) {
		const $tbody = this.$container.find("#rt-db-indicators-tbody");
		const list = (indicators || []).filter(
			(ind) => this.indicatorFilter === "all" || ind.category === this.indicatorFilter
		);

		if (!list.length) {
			$tbody.html(
				`<tr><td colspan="6" class="rt-db-empty">${__("No hay indicadores disponibles para este filtro.")}</td></tr>`
			);
			return;
		}

		const rowsHtml = list
			.map(
				(ind) => `
				<tr>
					<td><span class="rt-db-cat-pill">${frappe.utils.escape_html(ind.category)}</span></td>
					<td><strong>${frappe.utils.escape_html(ind.name)}</strong></td>
					<td style="color:#64748b;font-size:12px;">${frappe.utils.escape_html(ind.formula)}</td>
					<td style="text-align:right;font-weight:800;font-size:13.5px;white-space:nowrap;">${frappe.utils.escape_html(
						ind.value_formatted
					)}</td>
					<td style="color:#475569;font-size:12px;">${frappe.utils.escape_html(
						ind.reference_formatted
					)}</td>
					<td style="text-align:center;">
						<span class="rt-db-badge ${frappe.utils.escape_html(ind.status || "neutral")}">
							${frappe.utils.escape_html(ind.status_label || "")}
						</span>
					</td>
				</tr>
			`
			)
			.join("");

		$tbody.html(rowsHtml);
	}
}
