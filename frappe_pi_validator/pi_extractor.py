"""
Bridge between the extraction engine and Frappe.

Pure Python (no frappe import), so it can be tested outside a bench:

    from frappe_pi_validator.pi_extractor import extract_document
    data = extract_document("/path/PI.pdf", "PI.pdf")
"""

from __future__ import annotations

from typing import Any

# Item fields returned to the PI Validator page, in display order.
ITEM_FIELDS = [
    "item_no",
    "brand",
    "size",
    "pattern",
    "load_index",
    "speed_rating",
    "pr",
    "sidewall",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "currency",
    "qty_in_40hq",
]

NUMERIC_FIELDS = {"quantity", "unit_price", "amount", "qty_in_40hq"}


def _value(field: str, value: Any) -> Any:
    if value in (None, ""):
        return None

    if field in NUMERIC_FIELDS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return str(value)


def _tables(result) -> list[tuple[str, Any]]:
    """(source, table) for every PDF page and Excel sheet table."""

    tables = [
        (f"Page {page.page_number}", table)
        for page in result.pages
        for table in page.tables
    ]

    tables += [
        (f"Sheet {sheet.name}", table)
        for sheet in result.sheets
        for table in sheet.tables
    ]

    return tables


def extract_document(file_path: str, file_name: str) -> dict[str, Any]:
    """
    Run the engine on a file and return:

        items:       product rows (canonical fields) for the child table
        raw_tables:  tables found without recognizable product columns
        summary:     counts and totals
        result:      full engine output (JSON-serializable)
    """

    from frappe_pi_validator.extraction.services.document_service import (
        DocumentService,
    )

    result = DocumentService().process(file_path, file_name)

    items: list[dict[str, Any]] = []
    raw_tables: list[dict[str, Any]] = []

    for source, table in _tables(result):

        if table.extraction_method == "raw":
            raw_tables.append(
                {
                    "source": source,
                    "headers": table.headers,
                    "rows": table.rows,
                }
            )
            continue

        for row in table.rows:

            cells = dict(zip(table.headers, row))

            item = {
                field: _value(field, cells.get(field))
                for field in ITEM_FIELDS
            }
            item["source"] = source
            item["extraction_method"] = table.extraction_method

            # Joined rating kept for pages that still show one column.
            item["load_speed_rating"] = (
                f"{item['load_index'] or ''}{item['speed_rating'] or ''}" or None
            )

            items.append(item)

    currencies = sorted({item["currency"] for item in items if item["currency"]})

    summary = {
        "document_type": result.document_type,
        "item_count": len(items),
        "total_quantity": sum(item["quantity"] or 0 for item in items),
        "total_amount": round(sum(item["amount"] or 0 for item in items), 2),
        "currency": ", ".join(currencies),
        "raw_table_count": len(raw_tables),
        "engine": result.metadata.get("engine"),
        "warnings": list(result.warnings),
    }

    return {
        "items": items,
        "raw_tables": raw_tables,
        "summary": summary,
        "result": result.model_dump(mode="json"),
    }
