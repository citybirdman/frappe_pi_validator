from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from frappe_pi_validator.extraction.models.extraction import BoundingBox


@dataclass
class OCRBlock:
    text: str
    page: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 1.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


@dataclass
class HeaderColumn:
    name: str
    x1: float
    x2: float
    aliases: list[str] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2


@dataclass
class ParsedRow:
    page: int
    y1: float
    y2: float
    cells: dict[str, Optional[str]]
    cell_bboxes: dict[str, BoundingBox | None] = field(default_factory=dict)

    @property
    def size(self) -> Optional[str]:
        return self.cells.get("size")

    @property
    def item_no(self) -> Optional[str]:
        return self.cells.get("item_no")

    @property
    def brand(self) -> Optional[str]:
        return self.cells.get("brand")