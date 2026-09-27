from typing import Any, Literal
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    polygon: list[list[float]] | None = None


class TextBlock(BaseModel):
    text: str
    page: int | None = None
    bbox: BoundingBox | None = None
    confidence: float | None = None
    source: Literal["native_text", "ocr_paddle"]


class TableCell(BaseModel):
    row: int | None = None
    column: int | None = None
    value: Any = None
    bbox: BoundingBox | None = None
    confidence: float | None = None


class Table(BaseModel):
    table_id: str
    page: int | None = None

    # Logical/canonical headers
    headers: list[str] = Field(default_factory=list)

    # Structured values
    rows: list[list[Any]] = Field(default_factory=list)

    # Individual cells with geometry
    cells: list[TableCell] = Field(default_factory=list)

    # Original PP-Structure HTML, if available
    html: str | None = None

    # Additional metadata
    confidence: float | None = None
    extraction_method: str | None = None


class ImageContent(BaseModel):
    image_id: str
    page: int | None = None
    file_path: str | None = None
    bbox: BoundingBox | None = None
    ocr_text: str | None = None
    confidence: float | None = None


class Sheet(BaseModel):
    name: str
    max_row: int
    max_column: int
    rows: list[list[Any]] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


class Page(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    text: str = ""
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    images: list[ImageContent] = Field(default_factory=list)


class DocumentResult(BaseModel):
    document_id: str
    file_name: str
    mime_type: str
    document_type: str
    text: str = ""
    pages: list[Page] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)