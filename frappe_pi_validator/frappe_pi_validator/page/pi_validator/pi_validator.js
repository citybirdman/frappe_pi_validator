// Copyright (c) 2026, Ahmed Zaytoon and contributors
// For license information, please see license.txt

frappe.pages["pi-validator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("PI Validator"),
		single_column: true,
	});

	new PIValidator(page);
};

const ITEM_COLUMNS = [
	["source", __("Source")],
	["item_no", __("Item No / Code")],
	["brand", __("Brand")],
	["size", __("Size")],
	["pattern", __("Pattern")],
	["load_index", __("Load Index")],
	["speed_rating", __("Speed Rating")],
	["pr", __("PR")],
	["sidewall", __("Sidewall")],
	["description", __("Description")],
	["quantity", __("Quantity"), "number"],
	["unit", __("Unit")],
	["unit_price", __("Unit Price"), "number"],
	["amount", __("Amount"), "number"],
	["currency", __("Currency")],
	["qty_in_40hq", __("Qty / 40HQ"), "number"],
];

class PIValidator {
	constructor(page) {
		this.page = page;
		this.data = null;

		this.page.set_primary_action(__("Upload PI"), () => this.upload(), "upload");
		this.download_button = this.page.add_button(__("Download CSV"), () => this.download());
		this.download_button.hide();

		this.$body = $(`<div class="pi-validator"></div>`).appendTo(this.page.main);
		this.render_empty();
	}

	upload() {
		new frappe.ui.FileUploader({
			allow_multiple: false,
			make_attachments_public: false,
			restrictions: {
				allowed_file_types: [".pdf", ".xlsx", ".xlsm", ".xls"],
			},
			on_success: (file_doc) => this.extract(file_doc.file_url),
		});
	}

	extract(file_url) {
		frappe
			.call({
				method: "frappe_pi_validator.api.extract_file",
				args: { file_url },
				freeze: true,
				freeze_message: __("Extracting PI..."),
			})
			.then((r) => {
				this.data = r.message;
				this.render();
			});
	}

	render_empty() {
		this.$body.html(`
			<div class="text-muted text-center" style="padding: 60px 0;">
				${__("Upload a proforma invoice (PDF, XLSX, XLSM or XLS) to extract its items.")}
			</div>
		`);
	}

	render() {
		const { summary, items, raw_tables, file_name } = this.data;
		const esc = frappe.utils.escape_html;

		this.download_button.toggle(items.length > 0);

		const stat = (label, value) => `
			<div class="col-sm-3" style="margin-bottom: 12px;">
				<div class="text-muted small">${label}</div>
				<div class="h5" style="margin: 4px 0 0;">${esc(String(value ?? ""))}</div>
			</div>`;

		let html = `
			<div class="frappe-card" style="padding: 16px; margin-bottom: 16px;">
				<div class="h6" style="margin-bottom: 12px;">${esc(file_name)}</div>
				<div class="row">
					${stat(__("Items"), summary.item_count)}
					${stat(__("Total Quantity"), format_number(summary.total_quantity, null, 0))}
					${stat(__("Total Amount"), `${format_number(summary.total_amount, null, 2)} ${summary.currency || ""}`)}
					${stat(__("Document Type"), summary.document_type)}
				</div>
				${
					summary.warnings && summary.warnings.length
						? `<div class="text-warning small">${summary.warnings.map(esc).join("<br>")}</div>`
						: ""
				}
			</div>`;

		if (items.length) {
			html += this.table_html(
				ITEM_COLUMNS.map(([, label]) => label),
				items.map((item) =>
					ITEM_COLUMNS.map(([field, , type]) =>
						type === "number" && item[field] != null
							? format_number(item[field], null, field === "quantity" ? 0 : 2)
							: item[field]
					)
				),
				ITEM_COLUMNS.map(([, , type]) => type)
			);
		} else {
			html += `
				<div class="alert alert-warning">
					${__("No product table recognized. The tables found in the file are shown below as found.")}
				</div>`;
		}

		for (const table of raw_tables) {
			html += `<div class="h6" style="margin: 20px 0 8px;">${esc(table.source)}</div>`;
			html += this.table_html(table.headers, table.rows);
		}

		this.$body.html(html);
	}

	table_html(headers, rows, types = []) {
		const esc = frappe.utils.escape_html;
		const cell = (value, index) => {
			const align = types[index] === "number" ? ' class="text-right"' : "";
			const text = value == null || value === "" ? '<span class="text-muted">—</span>' : esc(String(value));
			return `<td${align}>${text}</td>`;
		};

		return `
			<div class="frappe-card" style="padding: 0; overflow-x: auto; margin-bottom: 16px;">
				<table class="table table-bordered table-condensed" style="margin: 0; font-size: 12px;">
					<thead>
						<tr>${headers.map((h) => `<th style="white-space: nowrap;">${esc(String(h ?? ""))}</th>`).join("")}</tr>
					</thead>
					<tbody>
						${rows.map((row) => `<tr>${row.map(cell).join("")}</tr>`).join("")}
					</tbody>
				</table>
			</div>`;
	}

	download() {
		if (!this.data || !this.data.items.length) {
			return;
		}

		const rows = [ITEM_COLUMNS.map(([, label]) => label)];

		for (const item of this.data.items) {
			rows.push(ITEM_COLUMNS.map(([field]) => item[field] ?? ""));
		}

		const name = (this.data.file_name || "pi").replace(/\.[^.]+$/, "");
		frappe.tools.downloadify(rows, null, `${name}_items`);
	}
}
