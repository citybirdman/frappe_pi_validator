from __future__ import annotations

from frappe_pi_validator.extraction.models.extraction import Table, TextBlock
from frappe_pi_validator.extraction.services.table.models import OCRBlock, ParsedRow
from frappe_pi_validator.extraction.services.table_service import TableService


class TableExtractor:
    """
    High-level table extraction facade.

    Responsibilities:
    - Convert TextBlock objects to OCRBlock objects.
    - Detect and parse tire rows.
    - Convert ParsedRow objects into API Table objects.

    Detection/parsing logic is intentionally kept outside this class.
    """

    def __init__(self):
        self.table_service = TableService()

    # ------------------------------------------------------------------
    # TextBlock -> OCRBlock
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ocr_block(
        block: TextBlock,
        page: int,
    ) -> OCRBlock:

        if block.bbox is None:
            return OCRBlock(
                text=block.text,
                page=page,
                x1=0.0,
                y1=0.0,
                x2=0.0,
                y2=0.0,
                confidence=block.confidence or 1.0,
                source=block.source,
            )

        return OCRBlock(
            text=block.text,
            page=page,
            x1=block.bbox.x1,
            y1=block.bbox.y1,
            x2=block.bbox.x2,
            y2=block.bbox.y2,
            confidence=block.confidence or 1.0,
            source=block.source,
        )

    # ------------------------------------------------------------------
    # Extract parsed rows
    # ------------------------------------------------------------------

    def extract_rows(
        self,
        blocks: list[TextBlock],
        page: int,
    ) -> list[ParsedRow]:

        ocr_blocks = [
            self._to_ocr_block(
                block=block,
                page=page,
            )
            for block in blocks
        ]

        return self.table_service.parse_rows(
            ocr_blocks
        )

    # ------------------------------------------------------------------
    # Convert ParsedRow -> Table
    # ------------------------------------------------------------------

    @staticmethod
    def rows_to_table(
        rows: list[ParsedRow],
        table_id: str,
        page: int,
    ) -> Table | None:

        if not rows:
            return None

        headers = [
            "item_no",
            "brand",
            "size",
            "pattern",
            "load_speed_rating",
            "pr",
            "sidewall",
            "quantity",
            "unit",
            "unit_price",
            "amount",
            "currency",
            "qty_in_40hq",
        ]

        table_rows = []

        for row in rows:
            table_rows.append([
                row.cells.get(header)
                for header in headers
            ])

        return Table(
            table_id=table_id,
            page=page,
            headers=headers,
            rows=table_rows,
        )

    # ------------------------------------------------------------------
    # Extract tables from one page
    # ------------------------------------------------------------------

    def extract_page_tables(
        self,
        blocks: list[TextBlock],
        page: int,
    ) -> list[Table]:

        rows = self.extract_rows(
            blocks=blocks,
            page=page,
        )

        if not rows:
            return []

        table = self.rows_to_table(
            rows=rows,
            table_id=f"table_{page}_1",
            page=page,
        )

        if table is None:
            return []

        return [table]
