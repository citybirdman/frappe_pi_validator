from PIL import Image

from frappe_pi_validator.extraction.models.extraction import (
    DocumentResult,
    Page,
)

from frappe_pi_validator.extraction.services.ocr_service import OCRService
from frappe_pi_validator.extraction.services.table_service import TableService


class ImageProcessor:

    def __init__(self):
        self.ocr = OCRService()
        self.table_service = TableService()

    def supports(
        self,
        mime_type: str,
    ) -> bool:

        return mime_type.startswith(
            "image/"
        )

    def process(
        self,
        file_path,
        document_id,
        file_name,
        mime_type,
    ):

        image = (
            Image.open(file_path)
            .convert("RGB")
        )

        parsed = self.ocr.extract(
            image
        )

        blocks = parsed.get(
            "blocks",
            [],
        )

        tables = parsed.get(
            "tables",
            [],
        )

        # ----------------------------------------------
        # Hybrid OCR block table extraction
        # ----------------------------------------------

        table = (
            self.table_service.extract_from_blocks(
                blocks=blocks,
                table_id="ocr_table_1",
                page=1,
            )
        )

        if table:
            tables.append(table)

        page = Page(
            page_number=1,
            width=image.width,
            height=image.height,
            text=parsed.get(
                "text",
                "",
            ),
            blocks=blocks,
            tables=tables,
        )

        return DocumentResult(
            document_id=document_id,
            file_name=file_name,
            mime_type=mime_type,
            document_type="image",
            text=parsed.get(
                "text",
                "",
            ),
            pages=[page],
            metadata={
                "engine": (
                    "paddleocr_pp_structure_v3 + "
                    "hybrid_table_extractor"
                ),
                "layout": parsed.get(
                    "layout"
                ),
                "raw_ocr": parsed.get(
                    "raw",
                    [],
                ),
            },
            warnings=parsed.get(
                "warnings",
                [],
            ),
        )