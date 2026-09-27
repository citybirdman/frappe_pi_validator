from __future__ import annotations

from frappe_pi_validator.extraction.services.table.models import OCRBlock, ParsedRow
from frappe_pi_validator.extraction.services.table.parsers import TireRowParser


class TableService:
    """
    High-level table extraction service.

    Detection and parsing logic live inside app.services.table.
    This class only coordinates the extraction flow.
    """

    def __init__(self):
        self.row_parser = TireRowParser()

    def parse_rows(
        self,
        blocks: list[OCRBlock],
    ) -> list[ParsedRow]:

        rows: list[ParsedRow] = []

        for block in blocks:
            parsed = self.row_parser.parse(block)

            if parsed is None:
                continue

            rows.append(parsed)

        return self._deduplicate_rows(rows)

    @staticmethod
    def _deduplicate_rows(
        rows: list[ParsedRow],
    ) -> list[ParsedRow]:

        result: list[ParsedRow] = []
        seen: set[tuple] = set()

        for row in rows:
            cells = row.cells

            key = (
                row.page,
                cells.get("item_no"),
                cells.get("size"),
                cells.get("quantity"),
                cells.get("amount"),
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(row)

        return result
