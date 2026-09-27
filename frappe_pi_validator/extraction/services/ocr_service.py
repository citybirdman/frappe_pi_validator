from __future__ import annotations

from typing import Any
import numpy as np
from PIL import Image
from frappe_pi_validator.extraction.config import settings
from frappe_pi_validator.extraction.models.extraction import TextBlock, BoundingBox, Table, TableCell

class OCRService:
    def __init__(self):
        self.pipeline = None
        self.dpi = settings.ocr_dpi

    def _ensure_pipeline(self):
        if self.pipeline is None:
            from paddleocr import PPStructureV3
            self.pipeline = PPStructureV3(
                lang=settings.ocr_language,
                device=settings.device,
                engine="paddle",
                enable_mkldnn=False,
                use_doc_orientation_classify=settings.use_doc_orientation_classify,
                use_doc_unwarping=settings.use_doc_unwarping,
                use_textline_orientation=settings.use_textline_orientation,
                use_table_recognition=settings.use_table_recognition,
                use_formula_recognition=settings.use_formula_recognition,
                use_chart_recognition=settings.use_chart_recognition,
            )
        return self.pipeline

    @staticmethod
    def _json_value(value: Any):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): OCRService._json_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [OCRService._json_value(v) for v in value]
        try:
            return value.tolist()
        except Exception:
            return str(value)

    @staticmethod
    def _result_dict(result):
        data = getattr(result, "json", None)
        if callable(data):
            data = data()
        if data is None:
            data = getattr(result, "to_dict", None)
            if callable(data):
                data = data()
        if data is None:
            return {}
        return OCRService._json_value(data)

    @staticmethod
    def _find_dicts(obj, predicate):
        found = []
        def walk(x):
            if isinstance(x, dict):
                if predicate(x):
                    found.append(x)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(obj)
        return found

    @staticmethod
    def _bbox(value):
        if value is None:
            return None
        try:
            if isinstance(value, dict):
                for key in ("box", "bbox", "points", "poly"):
                    if key in value:
                        return OCRService._bbox(value[key])
            if len(value) == 4 and all(isinstance(v, (int, float)) for v in value):
                return BoundingBox(x1=float(value[0]), y1=float(value[1]),
                                   x2=float(value[2]), y2=float(value[3]))
            pts = value
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            return BoundingBox(x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys),
                               polygon=[[float(p[0]), float(p[1])] for p in pts])
        except Exception:
            return None

    def extract(self, image: Image.Image):
        pipeline = self._ensure_pipeline()

        print("IMAGE TYPE:", type(image))
        print("IMAGE SIZE:", image.size)
        print("PIPELINE:", pipeline)

        image_np = np.asarray(image)

        results = list(pipeline.predict(image_np))

        print("RESULT COUNT:", len(results))

        for i, result in enumerate(results):
            print("=" * 80)
            print("RESULT:", i)
            print("TYPE:", type(result))
            print("RESULT:", result)

        raw = [self._result_dict(r) for r in results]

        print("RAW COUNT:", len(raw))
        print("RAW:", raw)

        blocks, tables = [], []
        text_parts = []
        warnings = []

        for data in raw:
            ocr_candidates = self._find_dicts(
                data,
                lambda d: isinstance(d.get("rec_texts"), list)
            )
            for ocr in ocr_candidates[:1]:
                texts = ocr.get("rec_texts", [])
                scores = ocr.get("rec_scores", [])
                boxes = ocr.get("rec_boxes", ocr.get("rec_polys", []))
                for i, txt in enumerate(texts):
                    if not str(txt).strip():
                        continue
                    score = scores[i] if i < len(scores) else None
                    box = boxes[i] if i < len(boxes) else None
                    blocks.append(TextBlock(
                        text=str(txt), bbox=self._bbox(box),
                        confidence=float(score) if isinstance(score, (int, float)) else None,
                        source="ocr_paddle"
                    ))
                text_parts.extend(str(t) for t in texts if str(t).strip())

            table_candidates = self._find_dicts(
                data,
                lambda d: "pred_html" in d or "html" in d
            )
            for i, table_data in enumerate(table_candidates):
                html = table_data.get("pred_html", table_data.get("html"))
                if not isinstance(html, str) or not html.strip():
                    continue
                tables.append(Table(table_id=f"table_{len(tables)+1}", html=html))

        if not raw:
            warnings.append("PaddleOCR returned no result objects.")

        return {
            "text": "\n".join(text_parts),
            "blocks": blocks,
            "tables": tables,
            "layout": None,
            "raw": raw,
            "warnings": warnings,
        }
