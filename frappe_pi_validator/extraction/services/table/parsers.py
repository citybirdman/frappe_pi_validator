from __future__ import annotations

import re

from frappe_pi_validator.extraction.services.table.field_resolver import TireProductResolver
from frappe_pi_validator.extraction.services.table.generic import _expand_in_cell, _pattern_after_brand

from frappe_pi_validator.extraction.services.table.detectors import (
    detect_load_speed,
    detect_speed_symbol,
    detect_pr,
    detect_quantity,
    detect_sidewall,
    detect_tire_size,
    is_tire_row,
)
from frappe_pi_validator.extraction.services.table.models import OCRBlock, ParsedRow
from frappe_pi_validator.extraction.services.table.normalizers import (
    normalize_currency,
    normalize_load_speed,
    normalize_number,
    normalize_pr,
    normalize_quantity,
    normalize_text,
    normalize_unit,
    split_currency_amount,
)


ITEM_NO_PATTERN = re.compile(r"^\d{6,}$")

# Strict standalone currency token.
#
# normalize_currency() returns unknown text unchanged, so it must not
# be used to decide whether a token IS a currency. Otherwise semantic
# tokens such as "RapidDragon" are consumed as currency and lost.
CURRENCY_TOKEN_PATTERN = re.compile(
    r"^(?:US\$|USD|\$|EUR|€|GBP|£)$",
    re.IGNORECASE,
)

# Size split over two PDF columns:
#
#   P185/65 | R15   -> P185/65R15
#   195 | R15       -> 195R15
SPLIT_SIZE_PATTERN = re.compile(
    r"(?<![A-Z0-9/.])((?:P|LT)?\d{3}(?:/\d{2})?)\s*\|\s*(Z?R\d{2}(?:LT|C)?)(?![0-9])",
    re.IGNORECASE,
)

# Vehicle category in front of the pattern in an ITEM column:
#
#   PCR CP672       -> pattern CP672
#   PCR ROADIAN HT  -> pattern ROADIAN HT
#   LTR AP-01       -> pattern AP-01
CATEGORY_PATTERN_PATTERN = re.compile(
    r"^(?P<category>PCR|LTR|TBR|OTR|SUV|LT)\s+(?P<pattern>\S.*)$",
    re.IGNORECASE,
)

# Shipping-mark column values that are not product data.
SHIPPING_MARKS = {"N/M", "NM", "NO MARK", "NO MARKS"}

UNIT_TOKEN_PATTERN = re.compile(
    r"^(?:PC|PCS|EA|SET|SETS|UNIT|UNITS)\.?$",
    re.IGNORECASE,
)


class TireRowParser:
    def __init__(self):
        self.product_resolver = TireProductResolver()

    # =========================================================
    # Main entry point
    # =========================================================

    def parse(
        self,
        block: OCRBlock,
    ) -> ParsedRow | None:

        text = normalize_text(block.text)

        if not text:
            return None

        if block.source != "excel":
            text = SPLIT_SIZE_PATTERN.sub(r"\1\2", text)

        # Shared tire-row detector.
        if not is_tire_row(text):
            return None

        # -----------------------------------------------------
        # Excel
        # -----------------------------------------------------

        if block.source == "excel":

            excel_format = block.metadata.get(
                "excel_format"
            )

            if excel_format == "compact":
                return self._parse_compact_excel_row(
                    block
                )

            if excel_format == "mapped":
                return self._parse_mapped_excel_row(
                    block
                )

            return self._parse_excel_row(
                block
            )

        # -----------------------------------------------------
        # PDF / OCR
        # -----------------------------------------------------

        # Pipe-separated rows must be handled first.
        #
        # Example:
        #
        # LANDSAIL | 285/45R22 | LS588 SUV | 114/XL_V |
        # 200 | PCS | USD | 61.15 | USD | 12230.00
        #
        # The compact parser assumes a completely different layout,
        # so it must NOT get first chance on pipe-separated rows.

        if "|" in text:

            parsed = self._parse_pipe_row(
                block,
                text,
            )

            if parsed is not None:
                return parsed

        # -----------------------------------------------------
        # Compact PDF / OCR
        # -----------------------------------------------------

        compact = self._parse_compact_pdf_row(
            block,
            text,
        )

        if compact is not None:
            return compact

        return self._parse_free_text_row(
            block,
            text,
        )

    # =========================================================
    # COMPACT EXCEL
    # =========================================================

    def _parse_compact_excel_row(
        self,
        block: OCRBlock,
    ) -> ParsedRow | None:

        values = block.metadata.get("values")

        if not isinstance(values, list):
            return None

        # Actual compact Excel layout:
        #
        # 0 = SIZE AND PATTERN
        # 1 = Quantity
        # 2 = Unit
        # 3 = Unit Price
        # 4 = Amount
        # 5 = empty
        # 6 = Qty in 40HQ
        # 7 = Container ratio formula

        def get(index: int):
            if index >= len(values):
                return None

            value = values[index]

            if value is None:
                return None

            text = str(value).strip()

            return text or None

        product_text = get(0)

        if not product_text:
            return None

        parsed = self._parse_compact_product(
            product_text
        )

        if parsed is None:
            return None

        quantity_raw = get(1)
        unit_raw = get(2)
        unit_price_raw = get(3)
        amount_raw = get(4)
        qty_in_40hq_raw = get(6)

        container_ratio_raw = None

        quantity = (
            normalize_number(quantity_raw)
            if quantity_raw is not None
            else None
        )

        qty_in_40hq = (
            normalize_number(qty_in_40hq_raw)
            if qty_in_40hq_raw is not None
            else None
        )

        if (
            isinstance(quantity, (int, float))
            and isinstance(qty_in_40hq, (int, float))
            and qty_in_40hq != 0
        ):
            container_ratio_raw = (
                quantity / qty_in_40hq
            )

        return self._build_compact_result(
            block=block,
            parsed=parsed,
            quantity_raw=quantity_raw,
            unit_raw=unit_raw,
            unit_price_raw=unit_price_raw,
            amount_raw=amount_raw,
            qty_in_40hq_raw=qty_in_40hq_raw,
            container_ratio_raw=container_ratio_raw,
        )

    # =========================================================
    # COMPACT PDF
    # =========================================================

    def _parse_compact_pdf_row(
        self,
        block: OCRBlock,
        text: str,
    ) -> ParsedRow | None:

        # -----------------------------------------------------
        # Pipe-separated compact PDF
        # -----------------------------------------------------

        if "|" in text:

            parts = [
                normalize_text(part)
                for part in text.split("|")
            ]

            if len(parts) >= 7:

                product_text = parts[0]

                if not is_tire_row(product_text):
                    return None

                parsed = self._parse_compact_product(
                    product_text
                )

                if parsed is None:
                    return None

                return self._build_compact_result(
                    block=block,
                    parsed=parsed,
                    quantity_raw=parts[1],
                    unit_raw=parts[2],
                    unit_price_raw=parts[3],
                    amount_raw=parts[4],
                    qty_in_40hq_raw=parts[5],
                    container_ratio_raw=parts[6],
                )

        # -----------------------------------------------------
        # Non-pipe compact PDF
        # -----------------------------------------------------
        #
        # Example:
        #
        # TH185/60R15PR[G-127]84H GOODRIDE TL
        # 20 PC $18.10 $362.00 1370 0.01
        #
        # Extract numeric columns from the right side.

        remainder = text

        # Container ratio.
        match = re.search(
            r"(?P<value>\d+(?:\.\d+)?)\s*$",
            remainder,
        )

        if not match:
            return None

        container_ratio_raw = match.group(
            "value"
        )

        remainder = remainder[
            :match.start()
        ].rstrip()

        # Qty in 40HQ.
        match = re.search(
            r"(?P<value>[\d,]+)\s*$",
            remainder,
        )

        if not match:
            return None

        qty_in_40hq_raw = match.group(
            "value"
        )

        remainder = remainder[
            :match.start()
        ].rstrip()

        # Amount.
        match = re.search(
            r"""
            (?P<value>
                (?:USD|US\$|\$|EUR|€|GBP|£|¥)?
                \s*
                [\d,]+(?:\.\d+)?
            )
            \s*$
            """,
            remainder,
            re.IGNORECASE | re.VERBOSE,
        )

        if not match:
            return None

        amount_raw = match.group(
            "value"
        )

        remainder = remainder[
            :match.start()
        ].rstrip()

        # Unit price.
        match = re.search(
            r"""
            (?P<value>
                (?:USD|US\$|\$|EUR|€|GBP|£|¥)?
                \s*
                [\d,]+(?:\.\d+)?
            )
            \s*$
            """,
            remainder,
            re.IGNORECASE | re.VERBOSE,
        )

        if not match:
            return None

        unit_price_raw = match.group(
            "value"
        )

        remainder = remainder[
            :match.start()
        ].rstrip()

        # Unit.
        match = re.search(
            r"""
            (?P<value>
                PC|PCS|EA|SET|SETS|UNIT|UNITS
            )
            \s*$
            """,
            remainder,
            re.IGNORECASE | re.VERBOSE,
        )

        if not match:
            return None

        unit_raw = match.group(
            "value"
        )

        remainder = remainder[
            :match.start()
        ].rstrip()

        # Quantity.
        match = re.search(
            r"(?P<value>[\d,]+)\s*$",
            remainder,
        )

        if not match:
            return None

        quantity_raw = match.group(
            "value"
        )

        product_text = remainder[
            :match.start()
        ].strip()

        if not is_tire_row(product_text):
            return None

        parsed = self._parse_compact_product(
            product_text
        )

        if parsed is None:
            return None

        return self._build_compact_result(
            block=block,
            parsed=parsed,
            quantity_raw=quantity_raw,
            unit_raw=unit_raw,
            unit_price_raw=unit_price_raw,
            amount_raw=amount_raw,
            qty_in_40hq_raw=qty_in_40hq_raw,
            container_ratio_raw=container_ratio_raw,
        )

    # =========================================================
    # SEMANTIC PRODUCT PARSER
    # =========================================================

    def _parse_compact_product(
        self,
        text: str,
    ) -> dict[str, object] | None:

        if not text:
            return None

        resolved = self.product_resolver.resolve(
            text
        )

        # A valid tire product must have a size.
        if not resolved.size:
            return None

        return {
            "brand": resolved.brand,
            "size": resolved.size,
            "pattern": resolved.pattern,
            "load_speed_rating": (
                resolved.load_speed_rating
            ),
            "pr": normalize_pr(resolved.pr),
            "sidewall": resolved.sidewall,
        }

    # =========================================================
    # BUILD COMPACT RESULT
    # =========================================================

    def _build_compact_result(
        self,
        block: OCRBlock,
        parsed: dict,
        quantity_raw,
        unit_raw,
        unit_price_raw,
        amount_raw,
        qty_in_40hq_raw,
        container_ratio_raw,
    ) -> ParsedRow:

        # -----------------------------------------------------
        # Quantity
        # -----------------------------------------------------

        quantity = None

        if quantity_raw:

            quantity = normalize_number(
                str(quantity_raw)
            )

            if quantity is None:
                quantity = normalize_quantity(
                    str(quantity_raw)
                )

        # -----------------------------------------------------
        # Unit
        # -----------------------------------------------------

        unit = None

        if unit_raw:
            unit = self._normalize_compact_unit(
                str(unit_raw)
            )

        # -----------------------------------------------------
        # Currency
        # -----------------------------------------------------

        currency = "USD"

        # -----------------------------------------------------
        # Unit price
        # -----------------------------------------------------

        unit_price = None

        if unit_price_raw:

            detected_currency, detected_value = (
                split_currency_amount(
                    str(unit_price_raw)
                )
            )

            if detected_value is not None:

                unit_price = detected_value

                if detected_currency:
                    currency = normalize_currency(
                        detected_currency
                    )

            else:
                unit_price = normalize_number(
                    str(unit_price_raw)
                )

        # -----------------------------------------------------
        # Amount
        # -----------------------------------------------------

        amount = None

        if amount_raw:

            # Excel formulas such as =B17*D17
            # are not numeric values.
            if (
                isinstance(amount_raw, str)
                and amount_raw.startswith("=")
            ):
                if (
                    isinstance(quantity, (int, float))
                    and isinstance(unit_price, (int, float))
                ):
                    amount = (
                        quantity * unit_price
                    )
                else:
                    amount = None

            else:

                detected_currency, detected_value = (
                    split_currency_amount(
                        str(amount_raw)
                    )
                )

                if detected_value is not None:

                    amount = detected_value

                    if detected_currency:
                        currency = normalize_currency(
                            detected_currency
                        )

                else:
                    amount = normalize_number(
                        str(amount_raw)
                    )

        # -----------------------------------------------------
        # Numeric cleanup
        #
        # 20.0               -> 20
        # 2996.9999999999995 -> 2997.0
        # -----------------------------------------------------

        if (
            isinstance(quantity, float)
            and quantity.is_integer()
        ):
            quantity = int(quantity)

        if isinstance(amount, float):
            amount = round(amount, 2)

        # -----------------------------------------------------
        # Extra columns
        # -----------------------------------------------------

        qty_in_40hq = None

        if qty_in_40hq_raw:

            qty_in_40hq = normalize_number(
                str(qty_in_40hq_raw)
            )

        container_ratio = None

        if container_ratio_raw:

            container_ratio = normalize_number(
                str(container_ratio_raw)
            )

        # -----------------------------------------------------
        # Cells
        # -----------------------------------------------------

        cells = {
            "item_no": None,
            "brand": parsed["brand"],
            "size": parsed["size"],
            "pattern": parsed["pattern"],
            "load_speed_rating": (
                parsed["load_speed_rating"]
            ),
            "pr": parsed["pr"],
            "sidewall": parsed["sidewall"],
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "amount": amount,
            "currency": currency,
            "qty_in_40hq": qty_in_40hq,
            "container_ratio": container_ratio,
        }

        return ParsedRow(
            page=block.page,
            y1=block.y1,
            y2=block.y2,
            cells=cells,
            cell_bboxes={},
        )

    # =========================================================
    # UNIT NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_compact_unit(
        value: str,
    ) -> str:

        value = value.strip().upper()

        mapping = {
            "PC": "PCS",
            "PCS": "PCS",
            "EA": "EA",
            "SET": "SET",
            "SETS": "SET",
            "UNIT": "UNIT",
            "UNITS": "UNIT",
        }

        return mapping.get(
            value,
            normalize_unit(value),
        )

    # =========================================================
    # EXISTING STRUCTURED EXCEL PARSER
    # =========================================================

    def _parse_excel_row(
        self,
        block: OCRBlock,
    ) -> ParsedRow | None:

        values = block.metadata.get(
            "values"
        )

        if not isinstance(values, list):
            return None

        # Existing Excel schema:
        #
        # 0  No.
        # 1  Brand
        # 2  Trademark
        # 3  Specification
        # 4  LI/SR
        # 5  Pattern
        # 6  Terms of Trade
        # 7  Unit Price
        # 8  Quantity
        # 9  Total Price
        # 10 Package
        # 11 Market
        # 12 Port of Loading
        # 13 Port of Destination
        # 14 Carrier
        # 15 Authentication
        # 16 Expected shipment date

        def get(index: int):

            if index >= len(values):
                return None

            value = values[index]

            if value is None:
                return None

            return str(value).strip() or None

        item_no = get(0)
        brand = get(1)
        size_raw = get(3)

        size_detection = detect_tire_size(
            size_raw or ""
        )

        if not size_detection:
            return None

        size = size_detection.value

        pattern = get(4)
        load_speed_raw = get(5)

        load_speed = None

        if load_speed_raw:

            detection = detect_load_speed(
                load_speed_raw
            )

            if detection:
                load_speed = (
                    normalize_load_speed(
                        load_speed_raw
                    )
                )

            # Only the speed symbol: "V"
            elif detect_speed_symbol(load_speed_raw):
                load_speed = detect_speed_symbol(
                    load_speed_raw
                ).value

        quantity_raw = get(8)

        quantity = None
        unit = None

        if quantity_raw is not None:

            quantity_detection = detect_quantity(
                f"{quantity_raw} PCS"
            )

            if quantity_detection:

                quantity = normalize_quantity(
                    quantity_raw
                )

                unit = "PCS"

            else:

                number = normalize_number(
                    quantity_raw
                )

                if number is not None:
                    quantity = number
                    unit = "PCS"

        unit_price = None

        unit_price_raw = get(7)

        if unit_price_raw:
            unit_price = normalize_number(
                unit_price_raw
            )

        amount = None
        currency = "USD"

        amount_raw = get(9)

        if amount_raw:

            # Formula without a cached value, e.g. =H7*I7.
            if amount_raw.startswith("="):
                if (
                    quantity is not None
                    and unit_price is not None
                ):
                    amount = round(
                        quantity * unit_price,
                        2,
                    )

            else:
                amount = normalize_number(
                    amount_raw
                )

        cells = {
            "item_no": item_no,
            "brand": brand,
            "size": size,
            "pattern": pattern,
            "load_speed_rating": load_speed,
            "pr": None,  # no PR column in this layout
            "sidewall": None,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "amount": amount,
            "currency": currency,
        }

        return ParsedRow(
            page=block.page,
            y1=block.y1,
            y2=block.y2,
            cells=cells,
            cell_bboxes={},
        )

    # =========================================================
    # HEADER-MAPPED EXCEL
    # =========================================================

    def _parse_mapped_excel_row(
        self,
        block: OCRBlock,
    ) -> ParsedRow | None:
        """
        Excel layout whose columns are located by header text
        (see ExcelProcessor.COLUMN_KEYWORDS), e.g.:

        No. | CODE | Brand | Pattern | Size | L.I&S.R |
        Order Qty | QTY/40HQ | FOB (US$/PC) | Total Amount

        Pattern and load/speed are verified by grammar and swapped
        when a sheet has them under each other's header.
        """

        values = block.metadata.get("values")
        columns = block.metadata.get("columns") or {}

        if not isinstance(values, list):
            return None

        def get(field: str):

            index = columns.get(field)

            if index is None or index >= len(values):
                return None

            value = values[index]

            if value is None:
                return None

            return str(value).strip() or None

        size_detection = detect_tire_size(
            get("size") or ""
        )

        if not size_detection:
            return None

        pattern = get("pattern")
        load_speed_raw = get("load_speed_rating")

        if (
            pattern
            and detect_load_speed(pattern)
            and not (
                load_speed_raw
                and detect_load_speed(load_speed_raw)
            )
        ):
            pattern, load_speed_raw = (
                load_speed_raw,
                pattern,
            )

        load_speed = None

        if load_speed_raw and detect_load_speed(
            load_speed_raw
        ):
            load_speed = normalize_load_speed(
                load_speed_raw
            )

        # Only the speed symbol: "V"
        elif detect_speed_symbol(load_speed_raw):
            load_speed = detect_speed_symbol(
                load_speed_raw
            ).value

        quantity = normalize_number(get("quantity"))

        if (
            isinstance(quantity, float)
            and quantity.is_integer()
        ):
            quantity = int(quantity)

        unit_price = normalize_number(get("unit_price"))

        amount_raw = get("amount")
        amount = None

        if amount_raw and not amount_raw.startswith("="):
            amount = normalize_number(amount_raw)

        elif (
            quantity is not None
            and unit_price is not None
        ):
            amount = quantity * unit_price

        if amount is not None:
            amount = round(amount, 2)

        qty_in_40hq = normalize_number(
            get("qty_in_40hq")
        )

        container_ratio = None

        if quantity is not None and qty_in_40hq:
            container_ratio = quantity / qty_in_40hq

        cells = {
            "item_no": get("item_code") or get("item_no"),
            "brand": get("brand"),
            "size": size_detection.value,
            "pattern": pattern,
            "load_speed_rating": load_speed,
            "pr": None,  # no PR column in this layout
            "sidewall": None,
            "quantity": quantity,
            "unit": "PCS" if quantity is not None else None,
            "unit_price": unit_price,
            "amount": amount,
            "currency": "USD",
            "qty_in_40hq": qty_in_40hq,
            "container_ratio": container_ratio,
        }

        return ParsedRow(
            page=block.page,
            y1=block.y1,
            y2=block.y2,
            cells=cells,
            cell_bboxes={},
        )

    # =========================================================
    # PIPE PARSER
    # =========================================================

    def _parse_pipe_row(
        self,
        block: OCRBlock,
        text: str,
    ) -> ParsedRow | None:

        parts = [
            normalize_text(part)
            for part in text.split("|")
        ]

        parts = [
            part
            for part in parts
            if part
        ]

        if not parts:
            return None

        # -----------------------------------------------------
        # Split a size glued to a neighbouring column.
        #
        # When the column gap is small, pdfplumber joins them:
        #
        # INVOVIC | RADIAL 913 EL 205/70R15 | 106/104R
        #
        # becomes:
        #
        # INVOVIC | RADIAL 913 EL | 205/70R15 | 106/104R
        # -----------------------------------------------------

        split_parts = []

        for part in parts:

            detection = detect_tire_size(part)

            if detection is None:
                split_parts.append(part)
                continue

            split_parts.extend(
                piece
                for piece in (
                    part[:detection.start].strip(),
                    part[detection.start:detection.end].strip(),
                    part[detection.end:].strip(),
                )
                if piece
            )

        parts = split_parts

        # -----------------------------------------------------
        # Leading row number + item code.
        #
        # 1 I06C3HB INVOVIC | EL601 | 205/70R15 | ...
        #
        # The code is the item number, not the pattern.
        # -----------------------------------------------------

        item_code = None

        code_match = re.match(
            r"^\d{1,3}\s+(?P<code>[A-Z0-9-]*\d[A-Z0-9-]*[A-Z][A-Z0-9-]*|[A-Z][A-Z0-9-]*\d[A-Z0-9-]*)(?:\s+|$)",
            parts[0],
        )

        if (
            code_match
            and not detect_tire_size(code_match.group("code"))
            and not detect_load_speed(code_match.group("code"))
            and not detect_pr(code_match.group("code"))
        ):

            item_code = code_match.group("code")

            rest = parts[0][code_match.end():].strip()

            parts = (
                [rest] if rest else []
            ) + parts[1:]

            if not parts:
                return None

        # Leading bare row number:
        #
        # 1 | 175/70R14 84T RW-581 | ROADWING | ...

        row_number = None

        if (
            item_code is None
            and len(parts) > 1
            and re.fullmatch(r"\d{1,3}", parts[0])
        ):
            row_number = parts.pop(0)

        # Shipping marks are not product data.

        parts = [
            part
            for part in parts
            if part.upper() not in SHIPPING_MARKS
        ]

        if not parts:
            return None

        # Vehicle category + pattern:
        #
        # PCR ROADIAN HT | P225/70R15 | ...

        category_pattern = None

        for part in parts:

            category_match = CATEGORY_PATTERN_PATTERN.match(part)

            if (
                category_match
                and not detect_tire_size(part)
            ):
                category_pattern = category_match.group(
                    "pattern"
                )
                break

        # -----------------------------------------------------
        # Find the tire-size part.
        #
        # The product may be distributed over multiple columns.
        #
        # Example:
        #
        # LANDSAIL | 285/45R22 | LS588 SUV | 114/XL_V |
        # 200 | PCS | USD | 61.15 | USD | 12230.00
        #
        # The tire size identifies the semantic product area.
        # -----------------------------------------------------

        product_index = None

        for index, part in enumerate(parts):

            if detect_tire_size(part):
                product_index = index
                break

        if product_index is None:
            return None

        # -----------------------------------------------------
        # Item number
        # -----------------------------------------------------

        item_no = None

        for index, part in enumerate(parts):

            if index == product_index:
                continue

            if ITEM_NO_PATTERN.fullmatch(part):
                item_no = part
                break

        # -----------------------------------------------------
        # Code column before the brand.
        #
        # CODE | BRAND | SIZE | INDEX | PATTERN
        # FZ2030 | FRIEZZA | P225/70R15 WSW | 100S | V64
        #
        # A code-like value in front of the brand is the item
        # code; the pattern is searched in the other columns.
        # -----------------------------------------------------

        brand_before_size = self.product_resolver.resolve(
            " ".join(parts[:product_index + 1])
        ).brand

        if brand_before_size and brand_before_size in parts[:product_index]:

            brand_index = parts.index(brand_before_size)

            leading_codes = [
                part
                for part in parts[:brand_index]
                if re.fullmatch(
                    r"(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+",
                    part,
                )
            ]

            if leading_codes:

                if item_code is None:
                    item_code = leading_codes[0]

                parts = parts[brand_index:]
                product_index -= brand_index

        if item_no is None:
            item_no = item_code or row_number

        # -----------------------------------------------------
        # Remove item number.
        #
        # Keep every other field because fields before and after
        # the tire size may belong to the semantic product.
        # -----------------------------------------------------

        remaining = [
            part
            for index, part in enumerate(parts)
            if index != product_index
            and part != item_no
        ]

        # -----------------------------------------------------
        # Semantic product parts before numeric/business columns.
        #
        # Important:
        #
        # We do NOT assume:
        #
        #     pattern = X
        #
        # or:
        #
        #     brand = last token
        #
        # The resolver determines those fields.
        # -----------------------------------------------------

        product_parts = [
            parts[index]
            for index in range(product_index)
            if index != product_index
            and parts[index] != item_no
        ]

        product_parts.append(
            parts[product_index]
        )

        # Everything after the size can contain:
        #
        # pattern
        # load/speed
        # quantity
        # unit
        # currency
        # price
        # amount
        #
        # We extract only the clearly structural fields.

        after_product = [
            parts[index]
            for index in range(
                product_index + 1,
                len(parts),
            )
            if parts[index] != item_no
        ]

        # -----------------------------------------------------
        # Row layout
        #
        # Descriptive fields are at the BEGINNING of the row,
        # business fields at the END:
        #
        #   beginning: item/code | brand | pattern | size | load/speed
        #   end:       quantity [unit] | ... | unit price [currency]
        #              | amount [currency]
        #
        # Examples:
        #
        #   ... | 114/XL_V | 200 | PCS | USD | 61.15 | USD | 12230.00
        #   ... | 96H      | 350 | 1200 | 19.38 | $6,783.00
        #
        # The end section is the trailing run of numbers, units
        # and currencies. Everything before it is descriptive.
        # -----------------------------------------------------

        after_product, end_section = (
            self._split_end_section(after_product)
        )

        (
            quantity,
            unit,
            unit_price,
            amount,
            currency,
            qty_in_40hq,
        ) = self._parse_end_section(end_section)

        # -----------------------------------------------------
        # Semantic product
        #
        # Combine:
        #
        #   fields before size
        #   size
        #   remaining semantic fields after size
        #
        # Example:
        #
        # LANDSAIL
        # 285/45R22
        # LS588 SUV
        # 114/XL_V
        #
        # becomes:
        #
        # LANDSAIL 285/45R22 LS588 SUV 114/XL_V
        #
        # The resolver then determines:
        #
        # brand            = LANDSAIL
        # size             = 285/45R22
        # pattern          = LS588
        # load_speed       = 114/XL_V
        # -----------------------------------------------------

        # A column holding only the speed symbol, after the size:
        #
        # LANDSAIL | 205/55R16 | LS588 | V | 200 | PCS ...
        #
        # Used only when no full load/speed is in the row, and kept
        # out of the pattern.
        lone_speed = None

        if not any(
            detect_load_speed(token)
            for part in parts
            for token in part.split()
        ):
            for part in after_product:
                if detect_speed_symbol(part):
                    lone_speed = detect_speed_symbol(part).value
                    after_product = [
                        other for other in after_product if other is not part
                    ]
                    break

        semantic_product_parts = [
            *product_parts,
            *after_product,
        ]

        semantic_product_text = " ".join(
            semantic_product_parts
        )

        resolved = self.product_resolver.resolve(
            semantic_product_text
        )

        if not resolved.size:
            return None

        # -----------------------------------------------------
        # Semantic fields
        # -----------------------------------------------------

        load_speed = (
            resolved.load_speed_rating
            or lone_speed
        )

        pr = resolved.pr

        sidewall = resolved.sidewall

        # -----------------------------------------------------
        # Fallback detection
        #
        # Only use detectors when resolver did not identify
        # the field.
        # -----------------------------------------------------

        new_remaining = []

        for value in after_product:

            consumed = False

            # -------------------------------------------------
            # PR
            # -------------------------------------------------

            if not pr:

                detection = detect_pr(
                    value
                )

                if detection:

                    pr = detection.value
                    consumed = True

            # -------------------------------------------------
            # Sidewall
            # -------------------------------------------------

            if not consumed and not sidewall:

                detection = detect_sidewall(
                    value
                )

                if detection:

                    sidewall = detection.value
                    consumed = True

            # -------------------------------------------------
            # Load / Speed
            # -------------------------------------------------

            if not consumed and not load_speed:

                detection = detect_load_speed(
                    value
                )

                if detection:

                    load_speed = (
                        normalize_load_speed(
                            value
                        )
                    )

                    consumed = True

            if not consumed:
                new_remaining.append(value)

        # -----------------------------------------------------
        # PR as a bare number next to load/speed:
        #
        # 88H 04       -> 4PR
        # 106/104R 08  -> 8PR
        # -----------------------------------------------------

        if not pr:

            for value in after_product:

                pr_match = re.fullmatch(
                    r"(?P<load>\S+)\s+(?P<pr>\d{1,2})",
                    value,
                )

                if (
                    pr_match
                    and detect_load_speed(
                        pr_match.group("load")
                    )
                    and int(pr_match.group("pr")) > 0
                ):
                    pr = f"{int(pr_match.group('pr'))}PR"
                    break

        # No PR in the document -> no PR (no 4PR default).

        # -----------------------------------------------------
        # Currency fallback
        # -----------------------------------------------------

        if currency is None:
            currency = "USD"

        # -----------------------------------------------------
        # Full pattern column
        # -----------------------------------------------------

        pattern = self._expand_pipe_pattern(
            resolved.pattern,
            semantic_product_parts,
            resolved.brand,
        )

        # A column holding size, load/speed, brand and pattern together:
        #
        #   1 165/65 R13 77T Achilles 122           -> 122
        #   16 215/65 R15 96H Achilles 868 All Seasons -> 868 All Seasons
        mixed_part = next(
            (
                part
                for part in semantic_product_parts
                if (pattern and pattern in part.split())
                or (resolved.brand and resolved.brand.upper() in part.upper().split())
            ),
            None,
        )

        if mixed_part and (not pattern or pattern == resolved.pattern):
            pattern = (
                _expand_in_cell(pattern, mixed_part, self.product_resolver, resolved.brand)
                if pattern
                else _pattern_after_brand(mixed_part, resolved.brand, self.product_resolver)
            ) or pattern

        brand = resolved.brand

        if category_pattern:

            pattern = category_pattern

            # PCR ROADIAN HT: ROADIAN is the pattern, not a brand.
            if brand and brand in category_pattern.split():
                brand = None

        # -----------------------------------------------------
        # Cells
        # -----------------------------------------------------

        cells = {
            "_tail": (semantic_product_text.split() or [None])[-1],
            "item_no": item_no,
            "brand": brand,
            "size": resolved.size,
            "pattern": pattern,
            "load_speed_rating": load_speed,
            "pr": normalize_pr(pr),
            "sidewall": sidewall,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "amount": amount,
            "currency": currency,
            "qty_in_40hq": qty_in_40hq,
        }

        return ParsedRow(
            page=block.page,
            y1=block.y1,
            y2=block.y2,
            cells=cells,
            cell_bboxes={},
        )

    @classmethod
    def _split_end_section(
        cls,
        after_product: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Split the parts after the size into descriptive parts and
        the business end section, token by token:

            88H 04 | T/L | BS | 270 USD | 29.45 | 7,951.50 12957APK
            -> descriptive: 88H 04 | T/L | BS
            -> end:         270 USD 29.45 7,951.50

        Anything after the last business value (material code,
        remark, date) is dropped:

            ... | $12.10 | $18,150.00 | 2026/9/1
            ... | $8,325.00 | only tyre
            ... | 7,951.50 12957APK

        Remarks are skipped only when the end section still holds
        at least two numbers, so descriptive tokens are never
        swallowed.
        """

        tokens = [
            (part_index, token)
            for part_index, part in enumerate(after_product)
            for token in part.split()
        ]

        def run_from(last: int) -> int:
            start = last + 1
            while (
                start > 0
                and cls._is_business_token(tokens[start - 1][1])
            ):
                start -= 1
            return start

        def number_count(start: int, last: int) -> int:
            return sum(
                1
                for _, token in tokens[start:last + 1]
                if split_currency_amount(token)[1] is not None
                or detect_quantity(token)
            )

        last = len(tokens) - 1
        start = run_from(last)

        if number_count(start, last) < 2:

            # Skip trailing remarks.
            for candidate in range(len(tokens) - 2, -1, -1):

                if not cls._is_business_token(tokens[candidate][1]):
                    continue

                candidate_start = run_from(candidate)

                if number_count(candidate_start, candidate) >= 2:
                    start, last = candidate_start, candidate

                break

        # The end section starts at a column boundary: a column that
        # also holds product text keeps its trailing number.
        #
        #   1 165/65 R13 77T Achilles 122 | Pcs | 100 | $ | 16.45 ...
        #
        # 122 is the pattern, not the quantity.
        while (
            0 < start <= last
            and tokens[start][0] == tokens[start - 1][0]
            and number_count(start, last) > 2
        ):
            part_index = tokens[start][0]
            while start <= last and tokens[start][0] == part_index:
                start += 1

        end_section = [
            token
            for _, token in tokens[start:last + 1]
        ]

        descriptive: dict[int, list[str]] = {}

        for part_index, token in tokens[:start]:
            descriptive.setdefault(part_index, []).append(token)

        return (
            [
                " ".join(descriptive[index])
                for index in sorted(descriptive)
            ],
            end_section,
        )

    @staticmethod
    def _is_business_token(value: str) -> bool:
        """
        Token that belongs to the end (business) section of a row:

            200 | PCS | USD | 61.15 | $6,783.00 | USD 12230.00
        """

        return bool(
            CURRENCY_TOKEN_PATTERN.fullmatch(value)
            or UNIT_TOKEN_PATTERN.fullmatch(value)
            or split_currency_amount(value)[1] is not None
            or detect_quantity(value)
        )

    @staticmethod
    def _parse_end_section(
        end_section: list[str],
    ) -> tuple:
        """
        Parse the business fields at the end of a row.

        Read right to left:

            last number          -> amount
            number before it     -> unit price
            first number         -> quantity
            numbers in between   -> QTY/40HQ

        Units attach to the quantity, currencies to the amounts.

        Returns:
            (quantity, unit, unit_price, amount, currency,
             qty_in_40hq)
        """

        numbers: list[tuple[int, float, str]] = []
        currency = None
        unit = None

        for index, value in enumerate(end_section):

            if CURRENCY_TOKEN_PATTERN.fullmatch(value):
                currency = currency or normalize_currency(value)
                continue

            if UNIT_TOKEN_PATTERN.fullmatch(value):
                unit = unit or normalize_unit(value.rstrip("."))
                continue

            # 200 PCS
            quantity_detection = detect_quantity(value)

            if quantity_detection:
                number_text, unit_text = (
                    quantity_detection.value.split()
                )
                unit = unit or normalize_unit(unit_text)
                numbers.append(
                    (index, float(number_text), "quantity")
                )
                continue

            detected_currency, number = (
                split_currency_amount(value)
            )

            if number is None:
                continue

            if detected_currency:
                currency = currency or detected_currency

            numbers.append((index, number, value))

        quantity = None
        unit_price = None
        amount = None
        qty_in_40hq = None

        if numbers:
            amount = numbers.pop()[1]

        if len(numbers) >= 2:
            unit_price = numbers.pop()[1]

        elif numbers:

            # One number left: quantity if it carries a unit,
            # otherwise the unit price.
            #
            # 200 | PCS | 12230.00    -> quantity
            # 61.15 | USD 12230.00    -> unit price

            index, number, _ = numbers[0]

            next_value = (
                end_section[index + 1]
                if index + 1 < len(end_section)
                else ""
            )

            if not (
                numbers[0][2] == "quantity"
                or UNIT_TOKEN_PATTERN.fullmatch(next_value)
            ):
                unit_price = numbers.pop()[1]

        if numbers:
            quantity = numbers.pop(0)[1]

        if numbers:
            qty_in_40hq = numbers[0][1]

        if (
            isinstance(quantity, float)
            and quantity.is_integer()
        ):
            quantity = int(quantity)

        if quantity is not None and unit is None:
            unit = "PCS"

        return (
            quantity,
            unit,
            unit_price,
            amount,
            currency or "USD",
            qty_in_40hq,
        )

    @staticmethod
    def _expand_pipe_pattern(
        pattern: str | None,
        parts: list[str],
        brand: str | None,
    ) -> str | None:
        """
        The resolver returns only the first pattern token.

        In pipe rows each part is a PDF column, so the whole column
        containing the pattern is the pattern:

            LS588 SUV  -> LS588 SUV   (not LS588)
            LS588 UHP  -> LS588 UHP

        Whole numbers are allowed inside the pattern:

            VAN 916 EL     -> VAN 916 EL
            RADIAL 913 EL  -> RADIAL 913 EL

        Expansion is rejected when the column also contains another
        recognizable field (brand, size, load/speed, PR, sidewall,
        decimal amounts or currency).
        """

        if not pattern:
            return pattern

        for part in parts:

            tokens = part.split()

            if pattern not in tokens or len(tokens) == 1:
                continue

            for token in tokens:

                if token == pattern:
                    continue

                if (
                    token == brand
                    or re.fullmatch(r"\d[\d,]*[.]\d+", token)
                    or CURRENCY_TOKEN_PATTERN.fullmatch(token)
                    or UNIT_TOKEN_PATTERN.fullmatch(token)
                    or detect_tire_size(token)
                    or detect_load_speed(token)
                    or detect_pr(token)
                    or detect_sidewall(token)
                ):
                    return pattern

            return part

        return pattern

    # =========================================================
    # FREE TEXT PDF / OCR
    # =========================================================

    def _parse_free_text_row(
        self,
        block: OCRBlock,
        text: str,
    ) -> ParsedRow | None:

        if not is_tire_row(text):
            return None

        working_text = normalize_text(text)

        amount = None
        unit_price = None
        quantity = None
        unit = None
        currency = None
        item_no = None

        # =========================================================
        # Item number
        # =========================================================

        item_match = re.match(
            r"^\s*(?P<item>\d+)\s+",
            working_text,
        )

        if item_match:

            item_no = item_match.group("item")

            working_text = working_text[
                item_match.end():
            ].strip()

        # =========================================================
        # Amount
        #
        # Example:
        # $66,550.00
        # USD 66,550.00
        # 66,550.00
        # =========================================================

        amount_match = re.search(
            r"""
            (?P<currency>
                US\$|USD|\$|EUR|€|GBP|£|¥
            )?
            \s*
            (?P<amount>
                [\d,]+(?:\.\d{1,4})?
            )
            \s*$
            """,
            working_text,
            re.IGNORECASE | re.VERBOSE,
        )

        if amount_match:

            amount_currency = (
                amount_match.group("currency")
            )

            amount = normalize_number(
                amount_match.group("amount")
            )

            if amount_currency:
                currency = normalize_currency(
                    amount_currency
                )

            working_text = working_text[
                :amount_match.start()
            ].strip()

        # =========================================================
        # Unit price
        #
        # Example:
        # $12.10
        # USD 12.10
        # 12.10
        # =========================================================

        price_match = re.search(
            r"""
            (?P<currency>
                US\$|USD|\$|EUR|€|GBP|£|¥
            )?
            \s*
            (?P<price>
                [\d,]+\.\d{1,4}
            )
            \s*$
            """,
            working_text,
            re.IGNORECASE | re.VERBOSE,
        )

        if price_match:

            price_currency = (
                price_match.group("currency")
            )

            unit_price = normalize_number(
                price_match.group("price")
            )

            if price_currency and not currency:
                currency = normalize_currency(
                    price_currency
                )

            working_text = working_text[
                :price_match.start()
            ].strip()

        # =========================================================
        # Quantity + optional unit
        #
        # Examples:
        # 5500
        # 5500 PCS
        # 450 PC
        # =========================================================

        quantity_match = re.search(
            r"""
            (?P<quantity>[\d,]+)
            \s*
            (?P<unit>
                PCS?|EA|SETS?|UNITS?
            )?
            \.?
            \s*$
            """,
            working_text,
            re.IGNORECASE | re.VERBOSE,
        )

        if quantity_match:

            quantity_text = (
                quantity_match.group("quantity")
            )

            unit_text = (
                quantity_match.group("unit")
            )

            quantity = normalize_quantity(
                quantity_text
            )

            if unit_text:
                unit = normalize_unit(
                    unit_text
                )

            working_text = working_text[
                :quantity_match.start()
            ].strip()

        # =========================================================
        # Semantic tire product
        #
        # Everything left is the product description.
        #
        # Example:
        #
        # 175/70R14 84T VI-786 OVATION
        #
        # Resolver:
        #   size             = 175/70R14
        #   load_speed       = 84T
        #   pattern          = VI-786
        #   brand            = OVATION
        #
        # Pattern has no fixed grammar.
        # It is resolved from the remaining semantic tokens.
        # =========================================================

        resolved = self.product_resolver.resolve(
            working_text
        )

        if not resolved.size:
            return None

        # =========================================================
        # Currency fallback
        # =========================================================

        if currency is None:
            currency = "USD"

        # =========================================================
        # Cells
        # =========================================================

        cells = {
            "item_no": item_no,
            "brand": resolved.brand,
            "size": resolved.size,
            "pattern": resolved.pattern,
            "load_speed_rating": (
                resolved.load_speed_rating
            ),
            "pr": normalize_pr(
                resolved.pr
            ),
            "sidewall": resolved.sidewall,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "amount": amount,
            "currency": currency,
        }

        return ParsedRow(
            page=block.page,
            y1=block.y1,
            y2=block.y2,
            cells=cells,
            cell_bboxes={},
        )


def parse_tire_row(
    block: OCRBlock,
) -> ParsedRow | None:

    return TireRowParser().parse(
        block
    )
