from __future__ import annotations

import pdfplumber

from frappe_pi_validator.extraction.models.extraction import (
    BoundingBox,
    DocumentResult,
    Page,
    TextBlock,
)
from frappe_pi_validator.extraction.services.ocr_service import OCRService
from frappe_pi_validator.extraction.services.table.generic import (
    GenericTableExtractor,
    raw_table,
    rows_to_table,
    table_score,
)
from frappe_pi_validator.extraction.services.table_extractor import TableExtractor


OCR_TEXT_THRESHOLD = 20

SEPARATOR = " | "

# PDF points, not pixels.
GAP_THRESHOLD = 10


class PDFProcessor:

    def __init__(self):
        self.ocr = OCRService()
        self.dpi = getattr(self.ocr, "dpi", 300)

        self.table_extractor = TableExtractor()

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    # ------------------------------------------------------------------
    # Table selection
    # ------------------------------------------------------------------

    def _select_tables(
        self,
        page_number: int,
        tire_tables: list,
        grid_tables: list[list[list]],
        words: list[dict],
        generic: GenericTableExtractor,
    ) -> list:
        """
        Try every strategy and keep the table with the most product
        data, so no single document layout is required:

            1. grid        - bordered table cells + header words
            2. words       - borderless table, header positions
            3. tire rows   - known supplier row layouts

        When none of them recognizes product rows, the table is
        returned as found (raw), so the page still shows a table.
        """

        for table in tire_tables:
            table.extraction_method = "tire_rows"

        grid_rows = []

        for grid in grid_tables:
            grid_rows.extend(generic.rows_from_grid(grid))

        word_rows = generic.rows_from_words(words) if words else []

        candidates = [
            rows_to_table(
                grid_rows, f"table_{page_number}_1", page_number, "grid"
            ) if grid_rows else None,
            rows_to_table(
                word_rows, f"table_{page_number}_1", page_number, "words"
            ) if word_rows else None,
            tire_tables[0] if tire_tables else None,
        ]

        # max() keeps the first of equal scores. Header-based results
        # come first: they know which column is which, while tire
        # rows infer it from position (e.g. a PLY column next to the
        # quantity).
        best = max(candidates, key=lambda table: table_score(table)[0])

        if table_score(best)[0] > 0:
            return [best]

        raw_tables = []

        for index, grid in enumerate(grid_tables, start=1):
            table = raw_table(
                grid, f"table_{page_number}_raw_{index}", page_number
            )
            if table is not None:
                raw_tables.append(table)

        return raw_tables

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def process(
        self,
        file_path,
        document_id,
        file_name,
        mime_type,
    ):

        pages = []
        all_text = []
        warnings = []

        generic = GenericTableExtractor()

        with pdfplumber.open(file_path) as pdf:

            for index, pdf_page in enumerate(pdf.pages):

                page_number = index + 1

                extracted_text = pdf_page.extract_text()

                native_text = (
                    extracted_text.strip()
                    if extracted_text
                    else ""
                )

                width = float(pdf_page.width)
                height = float(pdf_page.height)

                # ======================================================
                # Native PDF text
                # ======================================================

                if len(native_text) >= OCR_TEXT_THRESHOLD:

                    blocks = []

                    words = pdf_page.extract_words()

                    words = sorted(
                        words,
                        key=lambda w: (
                            w["top"],
                            w["x0"],
                        ),
                    )

                    if words:

                        lines = [[words[0]]]

                        for word in words[1:]:

                            last_word = lines[-1][-1]

                            if abs(
                                word["top"]
                                - last_word["top"]
                            ) <= 4:

                                lines[-1].append(word)

                            else:

                                lines.append([word])

                        for line in lines:

                            line = sorted(
                                line,
                                key=lambda w: w["x0"],
                            )

                            txt_parts = [
                                line[0]["text"].strip()
                            ]

                            last_x1 = line[0]["x1"]

                            for word in line[1:]:

                                clean_text = (
                                    word["text"].strip()
                                )

                                if not clean_text:
                                    continue

                                gap = (
                                    word["x0"]
                                    - last_x1
                                )

                                if gap > GAP_THRESHOLD:
                                    txt_parts.append(
                                        SEPARATOR
                                    )
                                else:
                                    txt_parts.append(" ")

                                txt_parts.append(
                                    clean_text
                                )

                                last_x1 = word["x1"]

                            txt = "".join(txt_parts)

                            if not txt:
                                continue

                            blocks.append(
                                TextBlock(
                                    text=txt,
                                    page=page_number,
                                    bbox=BoundingBox(
                                        x1=float(
                                            min(
                                                w["x0"]
                                                for w in line
                                            )
                                        ),
                                        y1=float(
                                            min(
                                                w["top"]
                                                for w in line
                                            )
                                        ),
                                        x2=float(
                                            max(
                                                w["x1"]
                                                for w in line
                                            )
                                        ),
                                        y2=float(
                                            max(
                                                w["bottom"]
                                                for w in line
                                            )
                                        ),
                                    ),
                                    confidence=1.0,
                                    source="native_text",
                                )
                            )

                    # --------------------------------------------------
                    # Table extraction from native PDF text
                    # --------------------------------------------------

                    tables = self._select_tables(
                        page_number=page_number,
                        tire_tables=(
                            self.table_extractor
                            .extract_page_tables(
                                blocks=blocks,
                                page=page_number,
                            )
                        ),
                        grid_tables=pdf_page.extract_tables(),
                        words=words,
                        generic=generic,
                    )

                    # No bordered table and nothing recognized:
                    # tables inferred from text alignment.
                    if not tables:
                        tables = self._select_tables(
                            page_number=page_number,
                            tire_tables=[],
                            grid_tables=pdf_page.extract_tables(
                                {
                                    "vertical_strategy": "text",
                                    "horizontal_strategy": "text",
                                }
                            ),
                            words=[],
                            generic=generic,
                        )

                    page = Page(
                        page_number=page_number,
                        width=width,
                        height=height,
                        text=native_text,
                        blocks=blocks,
                        tables=tables,
                    )

                # ======================================================
                # OCR branch
                # ======================================================

                else:

                    page_image = pdf_page.to_image(
                        resolution=self.dpi
                    )

                    image = (
                        page_image.original
                        .convert("RGB")
                    )

                    parsed = self.ocr.extract(
                        image
                    )

                    blocks = [
                        b.model_copy(
                            update={
                                "page": page_number
                            }
                        )
                        for b in parsed.get(
                            "blocks",
                            [],
                        )
                    ]

                    # --------------------------------------------------
                    # Tire-row table extraction
                    # --------------------------------------------------

                    # OCR lines act as words for the header-based
                    # column extractor.
                    ocr_words = [
                        {
                            "text": b.text,
                            "x0": b.bbox.x1,
                            "x1": b.bbox.x2,
                            "top": b.bbox.y1,
                            "bottom": b.bbox.y2,
                        }
                        for b in blocks
                        if b.bbox is not None
                    ]

                    tables = self._select_tables(
                        page_number=page_number,
                        tire_tables=(
                            self.table_extractor
                            .extract_page_tables(
                                blocks=blocks,
                                page=page_number,
                            )
                        ),
                        grid_tables=[],
                        words=ocr_words,
                        generic=generic,
                    )

                    # --------------------------------------------------
                    # Native PPStructure table results
                    # --------------------------------------------------

                    ocr_tables = [
                        t.model_copy(
                            update={
                                "page": page_number
                            }
                        )
                        for t in parsed.get(
                            "tables",
                            [],
                        )
                    ]

                    # Keep both extraction mechanisms.
                    tables.extend(ocr_tables)

                    page = Page(
                        page_number=page_number,
                        width=width,
                        height=height,
                        text=parsed.get(
                            "text",
                            "",
                        ),
                        blocks=blocks,
                        tables=tables,
                    )

                    warnings.extend(
                        parsed.get(
                            "warnings",
                            [],
                        )
                    )

                pages.append(page)

                if page.text:
                    all_text.append(page.text)

        # Raw tables are a fallback for documents without any
        # recognized product table; otherwise they are noise
        # (terms, bank details, signatures).
        if any(
            table.extraction_method != "raw"
            for page in pages
            for table in page.tables
        ):
            for page in pages:
                page.tables = [
                    table
                    for table in page.tables
                    if table.extraction_method != "raw"
                ]

        return DocumentResult(
            document_id=document_id,
            file_name=file_name,
            mime_type=mime_type,
            document_type="pdf",
            text="\n\n".join(all_text),
            pages=pages,
            warnings=list(
                dict.fromkeys(warnings)
            ),
            metadata={
                "engine": (
                    "pdfplumber + "
                    "paddleocr_pp_structure_v3"
                )
            },
        )
