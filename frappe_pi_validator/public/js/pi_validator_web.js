// Copyright (c) 2026, Ahmed Zaytoon and contributors
// For license information, please see license.txt

// Script of the public PI Validator page (www/pi-validator.html).
// Served as /assets/frappe_pi_validator/js/pi_validator_web.js

(function () {
	var root = document.querySelector(".pi-validator");
	var form = root.querySelector(".pi-validator-head");
	var input = form.querySelector("input[type=file]");
	var uploadButton = form.querySelector(".pi-upload");
	var downloadButton = form.querySelector(".pi-download");
	var errorBox = root.querySelector(".pi-error");
	var result = root.querySelector(".pi-result");
	var maxBytes = Number(root.dataset.maxFileMb) * 1024 * 1024;
	var csrfToken = root.dataset.csrfToken;
	var data = null;

	var t = function (text) {
		return typeof window.__ === "function" ? window.__(text) : text;
	};

	// Same columns as the desk page (page/pi_validator).
	var COLUMNS = [
		["source", "Source"],
		["item_no", "Item No / Code"],
		["brand", "Brand"],
		["size", "Size"],
		["pattern", "Pattern"],
		["load_speed_rating", "Load / Speed"],
		["pr", "PR"],
		["sidewall", "Sidewall"],
		["description", "Description"],
		["quantity", "Quantity", 0],
		["unit", "Unit"],
		["unit_price", "Unit Price", 2],
		["amount", "Amount", 2],
		["currency", "Currency"],
		["qty_in_40hq", "Qty / 40HQ", 2]
	];

	function esc(value) {
		return String(value).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	function isEmpty(value) {
		return value === null || value === undefined || value === "";
	}

	function number(value, digits) {
		return Number(value).toLocaleString(undefined, {
			minimumFractionDigits: digits,
			maximumFractionDigits: digits
		});
	}

	function showError(message) {
		errorBox.textContent = message;
		errorBox.hidden = !message;
	}

	function serverMessage(json) {
		try {
			if (json._server_messages) {
				return JSON.parse(JSON.parse(json._server_messages)[0]).message;
			}
		} catch (e) {
			// fall through
		}
		return json.message || t("Extraction failed.");
	}

	// The page never reloads: the button is type="button" and the form
	// cannot be submitted (e.g. with Enter).
	form.addEventListener("submit", function (event) {
		event.preventDefault();
	});

	uploadButton.addEventListener("click", function () {
		var file = input.files[0];

		if (!file) {
			showError(t("Choose a PI file first."));
			return;
		}

		if (file.size > maxBytes) {
			showError(t("The file is too large."));
			return;
		}

		var body = new FormData();
		body.append("file", file);

		var headers = { Accept: "application/json" };
		if (csrfToken) {
			headers["X-Frappe-CSRF-Token"] = csrfToken;
		}

		showError("");
		uploadButton.disabled = true;
		downloadButton.hidden = true;
		result.innerHTML = '<div class="text-muted text-center" style="padding: 60px 0;">' +
			esc(t("Extracting PI...")) + "</div>";

		fetch("/api/method/frappe_pi_validator.api.extract_public", {
			method: "POST",
			body: body,
			headers: headers,
			credentials: "same-origin"
		})
			.then(function (response) {
				return response.json().catch(function () {
					return {};
				}).then(function (json) {
					if (response.status === 429) {
						throw new Error(t("Too many requests. Please try again later."));
					}
					if (!response.ok || !json.message || !json.message.summary) {
						throw new Error(serverMessage(json));
					}
					return json.message;
				});
			})
			.then(function (message) {
				data = message;
				render();
			})
			.catch(function (error) {
				result.innerHTML = "";
				showError(error.message || t("Extraction failed."));
			})
			.then(function () {
				uploadButton.disabled = false;
			});
	});

	function stat(label, value) {
		return '<div class="col-sm-3" style="margin-bottom: 12px;">' +
			'<div class="text-muted small">' + esc(t(label)) + "</div>" +
			'<div class="h5" style="margin: 4px 0 0;">' + esc(isEmpty(value) ? "" : value) + "</div>" +
			"</div>";
	}

	function tableHtml(headers, rows, digits) {
		digits = digits || [];

		var head = headers.map(function (h) {
			return '<th style="white-space: nowrap;">' + esc(isEmpty(h) ? "" : h) + "</th>";
		}).join("");

		var body = rows.map(function (row) {
			return "<tr>" + row.map(function (value, index) {
				var numeric = digits[index] !== undefined && !isEmpty(value);
				var text = isEmpty(value)
					? '<span class="text-muted">—</span>'
					: esc(numeric ? number(value, digits[index]) : value);
				return "<td" + (numeric ? ' class="text-right"' : "") + ">" + text + "</td>";
			}).join("") + "</tr>";
		}).join("");

		return '<div class="frappe-card" style="padding: 0; overflow-x: auto; margin-bottom: 16px;">' +
			'<table class="table table-bordered table-condensed" style="margin: 0; font-size: 12px;">' +
			"<thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table></div>";
	}

	function render() {
		var summary = data.summary;
		var items = data.items;

		var html = '<div class="frappe-card" style="padding: 16px; margin-bottom: 16px;">' +
			'<div class="h6" style="margin-bottom: 12px;">' + esc(data.file_name) + "</div>" +
			'<div class="row">' +
			stat("Items", summary.item_count) +
			stat("Total Quantity", number(summary.total_quantity, 0)) +
			stat("Total Amount", number(summary.total_amount, 2) + " " + (summary.currency || "")) +
			stat("Document Type", summary.document_type) +
			"</div>" +
			(summary.warnings && summary.warnings.length
				? '<div class="text-warning small">' + summary.warnings.map(esc).join("<br>") + "</div>"
				: "") +
			"</div>";

		if (items.length) {
			html += tableHtml(
				COLUMNS.map(function (c) { return t(c[1]); }),
				items.map(function (item) {
					return COLUMNS.map(function (c) { return item[c[0]]; });
				}),
				COLUMNS.map(function (c) { return c[2]; })
			);
		} else {
			html += '<div class="alert alert-warning">' +
				esc(t("No product table recognized. The tables found in the file are shown below as found.")) +
				"</div>";
		}

		data.raw_tables.forEach(function (table) {
			html += '<div class="h6" style="margin: 20px 0 8px;">' + esc(table.source) + "</div>";
			html += tableHtml(table.headers, table.rows);
		});

		result.innerHTML = html;
		downloadButton.hidden = items.length === 0;
	}

	downloadButton.addEventListener("click", function () {
		if (!data || !data.items.length) {
			return;
		}

		var quote = function (value) {
			var text = isEmpty(value) ? "" : String(value);
			return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
		};

		var lines = [COLUMNS.map(function (c) { return quote(t(c[1])); }).join(",")];

		data.items.forEach(function (item) {
			lines.push(COLUMNS.map(function (c) { return quote(item[c[0]]); }).join(","));
		});

		// BOM so Excel reads UTF-8 (Arabic, symbols) correctly.
		var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
		var link = document.createElement("a");
		link.href = URL.createObjectURL(blob);
		link.download = (data.file_name || "pi").replace(/\.[^.]+$/, "") + "_items.csv";
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(link.href);
	});
})();
