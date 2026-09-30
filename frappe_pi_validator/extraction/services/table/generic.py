"""
Layout-independent table extraction.

The row parsers in parsers.py understand specific supplier layouts.
This module works for any layout that has a header row:

    1. Find the header row by its words (size, pattern, qty, price,
       amount, ...), wherever it is and in any column order.
    2. Map every column to a field from its header text.
    3. Read each data row by column, validate every value with the
       tire grammars, and fill gaps with TireProductResolver.

Two sources of rows:

    - grid:  cell grid of a bordered table (pdfplumber tables,
             Excel sheets)
    - words: word positions of a borderless table; the header
             words define the column boundaries

raw_table() is the last resort: the table exactly as found, so a
document never ends up without a table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from frappe_pi_validator.extraction.models.extraction import Table
from frappe_pi_validator.extraction.services.table.brands import canonical_brand, fill_truncated_brands
from frappe_pi_validator.extraction.services.table.detectors import (
    contains_tire_size,
    split_load_speed,
    combine_load_speed,
    detect_load_speed,
    detect_speed_symbol,
    detect_sidewall,
    detect_tire_size,
)
from frappe_pi_validator.extraction.services.table.field_resolver import TireProductResolver
from frappe_pi_validator.extraction.services.table.normalizers import (
    format_size,
    normalize_currency,
    normalize_load_speed,
    normalize_pr,
    normalize_unit,
    split_currency_amount,
)


CANONICAL_HEADERS = [
    "item_no",
    "brand",
    "size",
    "pattern",
    "load_index",
    "speed_rating",
    "pr",
    "sidewall",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "currency",
    "qty_in_40hq",
]


# Tables without tire sizes (other goods) keep the description.
GENERAL_HEADERS = [
    "item_no",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "currency",
]


# =============================================================
# Header vocabulary
#
# Checked in order; the first rule that matches wins, so the more
# specific rules come first:
#
#   "Qty in 40HQ"  -> qty_in_40hq  (before quantity)
#   "Total Price"  -> amount       (before unit_price)
#   "Unit Price"   -> unit_price   (before unit)
#   "Size&Pattern" -> description  (before size / pattern)
# =============================================================

FIELD_RULES = [
    (field_name, re.compile(pattern, re.IGNORECASE))
    for field_name, pattern in [
        ("qty_in_40hq", r"40\s*h[qc]|container"),
        (
            "amount",
            r"amount|total\s*price|total\s*value|^value$"
            r"|\btotal\b(?!\s*(qty|quantity|pcs|pieces|q\s+ty))",
        ),
        (
            "unit_price",
            r"unit\s*price|\bprice\b|\bfob\b|\bcfr\b|\bcif\b|\bexw\b"
            r"|(usd|us\$|\$)\s*/\s*(pc|pcs|set|unit)|\brate\b",
        ),
        ("quantity", r"\bqty\b|q\s+ty|quantity|\bpcs\b|\bpieces\b|sets\s*/\s*pcs"),
        # "Service description" is the tire term for load/speed.
        ("load_speed_rating", r"service\s*desc"),
        (
            "description",
            r"size\s*(&|and)\s*pattern|description|commodity|\bgoods\b|\bproduct\b",
        ),
        # Load index and speed symbol in separate columns; joined to a
        # load/speed rating when both fit the formula (91 | V -> 91V).
        ("load_index", r"^(l\.?\s*i\.?|load\s*index|load\s*idx)$"),
        (
            "speed_symbol",
            r"^(s\.?\s*s\.?|s\.?\s*r\.?|s\.?\s*i\.?|speed(\s*(symbol|rating|rate|index|index))?)$",
        ),
        ("load_speed_rating", r"\bl\.?\s*i\b|li\s*[/&]\s*s\.?\s*r|\bload\b|\bspeed\b|\bindex\b|^l\s*/?\s*s$"),
        ("sidewall", r"\bs\s*/\s*w\b|sidewall"),
        ("pr", r"^p\.?\s*r\.?$|\bply\b"),
        ("item_code", r"\bcode\b|material|article|\bsku\b|\b(part|art)\.?\s*no"),
        ("item_no", r"^(no\.?|s\s*/?\s*n|sr\.?|#|item\s*no\.?)$"),
        ("item", r"^item$"),
        ("brand", r"brand|trade\s*mark"),
        ("pattern", r"pattern|tread"),
        ("size", r"\bsize\b|\bspec"),
        ("unit", r"^unit$|^u\.?\s*o\.?\s*m\.?$|^u\s*/\s*m$"),
        ("type", r"^type$"),
        ("remark", r"remark|\bnote\b|\betd\b|delivery|shipment"),
        ("shipping_mark", r"shipping|\bmarks?\b"),
    ]
]

PRODUCT_FIELDS = {"size", "description", "pattern"}
REPEATABLE_FIELDS = {"item_code"}
BUSINESS_FIELDS = {"quantity", "unit_price", "amount"}
CORE_FIELDS = PRODUCT_FIELDS | BUSINESS_FIELDS | {
    "brand",
    "load_speed_rating",
    "load_index",
    "speed_symbol",
    "item_code",
    "item_no",
    "item",
    "pr",
    "sidewall",
}

# Columns whose text describes the product.
DESCRIPTIVE_FIELDS = [
    "brand",
    "description",
    "size",
    "pattern",
    "load_speed_rating",
    "load_index",
    "speed_symbol",
    "pr",
    "sidewall",
]

CURRENCY_TOKEN = re.compile(r"^(?:US\$|USD|\$|EUR|€|GBP|£)$", re.IGNORECASE)
UNIT_TOKEN = re.compile(r"^(?:PC|PCS|EA|SET|SETS|UNIT|UNITS)\.?$", re.IGNORECASE)
NUMBER_TOKEN = re.compile(r"^[\d,]*\d(?:\.\d+)?$")
CODE_TOKEN = re.compile(r"(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+", re.IGNORECASE)

# PCR CP672 / LTR AP-01: vehicle category + pattern.
CATEGORY_PATTERN = re.compile(
    r"^(?P<category>PCR|LTR|TBR|OTR|SUV|LT)\s+(?P<pattern>\S.*)$",
    re.IGNORECASE,
)

# P185/65 R15 -> P185/65R15 (size split over two columns)
SPLIT_SIZE = re.compile(
    r"(?<![A-Z0-9/.])((?:P|LT)?\d{3}(?:/\d{2})?)\s+(Z?R\d{2}(?:LT|C)?)(?![0-9])",
    re.IGNORECASE,
)

SUMMARY_ROW = re.compile(
    r"^(sub\s*total|grand\s*total|total|say\b|合计|总计)",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(str(value).split())


def normalize_header(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("（", "(").replace("）", ")")

    # (1)Brand, (4)Quantity
    text = re.sub(r"\(\d+\)", " ", text)
    text = re.sub(r"[`'’()\[\]:]", " ", text)

    return " ".join(text.lower().split())


def map_header(value: Any) -> str | None:
    text = normalize_header(value)

    if not text:
        return None

    for field_name, rule in FIELD_RULES:
        if rule.search(text):
            return field_name

    return None


# =============================================================
# Header detection
# =============================================================

@dataclass
class HeaderLayout:
    """Field of every column, plus hints taken from header text."""

    fields: list[str | None]
    labels: list[str]
    hints: dict[str, str] = field(default_factory=dict)

    @property
    def mapped(self) -> set[str]:
        return {f for f in self.fields if f}


def _header_hints(labels: list[str], fields: list[str | None]) -> dict[str, str]:
    """
    Currency and unit written only in the header:

        UNIT PRICE (USD)   -> currency USD
        QUANTITY (PCS)     -> unit PCS
        FOB QINGDAO (US$/PC)
    """

    hints: dict[str, str] = {}

    for label, field_name in zip(labels, fields):

        text = normalize_header(label)

        if field_name in ("unit_price", "amount"):
            if re.search(r"\busd\b|us\$", text):
                hints.setdefault("currency", "USD")
            elif re.search(r"\beur\b|€", text):
                hints.setdefault("currency", "EUR")

        if field_name == "quantity":
            # "sets/pcs": pieces unless only sets are named.
            for unit_word in ("pcs", "pc", "ea", "sets", "set", "units", "unit"):
                if re.search(rf"\b{unit_word}\b", text):
                    hints.setdefault("unit", normalize_unit(unit_word))
                    break

    return hints


def build_layout(labels: list[Any]) -> HeaderLayout:
    """
    Map header labels to fields.

    An empty label belongs to the column before it (a header cell
    spanning two columns):

        (4)Quantity | [empty]   ->  200 | PCS
        Amount      | [empty]   ->  USD | 12230.00
    """

    texts = [clean_text(label) for label in labels]
    fields: list[str | None] = []
    used: set[str] = set()
    previous: str | None = None

    for text in texts:

        field_name = map_header(text)

        # Several code columns (PART. NO. | ART. NO.) share the field;
        # their non-empty values are joined.
        if field_name in REPEATABLE_FIELDS:
            fields.append(field_name)
            previous = field_name

        elif field_name and field_name not in used:
            used.add(field_name)
            fields.append(field_name)
            previous = field_name

        elif not text and previous:
            fields.append(previous)

        else:
            fields.append(None)
            previous = None

    return HeaderLayout(
        fields=fields,
        labels=texts,
        hints=_header_hints(texts, fields),
    )


def is_valid_layout(layout: HeaderLayout) -> bool:
    mapped = layout.mapped

    return (
        len(mapped & CORE_FIELDS) >= 3
        and bool(mapped & PRODUCT_FIELDS)
        and bool(mapped & BUSINESS_FIELDS)
    )


def merge_header_rows(upper: list[Any], lower: list[Any]) -> list[str]:
    """
    Two-row header. The lower label (closest to the data) wins when
    it names a field; otherwise both rows are combined:

        COMMODITY            | Order Qty (PCS)
        No.   | CODE | ...   |

        -> No. | CODE | ... | Order Qty (PCS)
    """

    labels = []

    # Lower-row labels: an empty cell between two of them continues
    # the label on its left (a header spanning cells), so text above
    # it is not a header:
    #
    #   N/M  |       |         | FOB QINGDAO |   |        <- note above
    #   BRAND| SIZE  | SPEED   |             |   | QTY    <- header
    #                  114       (span)        H
    filled = [
        index
        for index in range(len(lower))
        if clean_text(lower[index])
    ]
    first, last = (filled[0], filled[-1]) if filled else (None, None)

    for index in range(max(len(upper), len(lower))):

        top = clean_text(upper[index]) if index < len(upper) else ""
        bottom = clean_text(lower[index]) if index < len(lower) else ""

        if not bottom and first is not None and first < index < last:
            labels.append("")
            continue

        if bottom and map_header(bottom):
            labels.append(bottom)
        elif top and bottom:
            labels.append(f"{top} {bottom}")
        else:
            labels.append(top or bottom)

    return labels


def find_grid_header(rows: list[list[Any]]) -> tuple[int, HeaderLayout] | None:
    """Return (header_row_index, layout) of the first valid header."""

    for index, row in enumerate(rows):

        single = build_layout(row)

        options = [single]

        if index > 0:
            options.append(
                build_layout(merge_header_rows(rows[index - 1], row))
            )

        valid = [option for option in options if is_valid_layout(option)]

        if valid:

            best = max(valid, key=lambda layout: len(layout.mapped))

            # The row below may complete a two-row header:
            #
            # COMMODITY |      |       | Order Qty | Amount
            # No.       | CODE | Brand | Pattern ...
            if index + 1 < len(rows):

                merged = build_layout(
                    merge_header_rows(row, rows[index + 1])
                )

                if (
                    is_valid_layout(merged)
                    and len(merged.mapped) > len(best.mapped)
                ):
                    return index + 1, merged

            return index, best

    return None


# =============================================================
# Row building
# =============================================================

def _first_number(text: str) -> float | None:
    for token in text.split():
        currency, number = split_currency_amount(token)
        if number is not None:
            return number
    return None


def _money(text: str) -> tuple[str | None, float | None]:
    """USD | 61.15, $6,783.00, USD 12230.00, 7,951.50 12957APK"""

    currency = None
    number = None

    for token in text.split():

        if CURRENCY_TOKEN.fullmatch(token):
            currency = currency or normalize_currency(token)
            continue

        token_currency, token_number = split_currency_amount(token)

        if token_number is not None and number is None:
            number = token_number
            if token_currency:
                currency = currency or token_currency

    return currency, number


def _as_int(number: float | None):
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _expand_in_cell(
    pattern: str | None,
    cell_text: str,
    resolver: TireProductResolver,
    brand: str | None,
) -> str | None:
    """
    The resolver returns one pattern token. In a description cell
    the pattern is the whole run of unrecognized tokens around it:

        215/60R16 95H ECO PLUS   -> ECO PLUS
        205/55R16 91V SPORT-7 XL -> SPORT-7
        205/55R16 91 V SPORT-7   -> SPORT-7  (91 V is load/speed)
        215/65 R15 96H Achilles 868 All Seasons -> 868 All Seasons
        225/70 R16 107H XL Achilles Desert Hawk H/T 2 -> Desert Hawk H/T 2

    Whole numbers can be part of a pattern (quantities have their own
    column); decimals (prices) cannot.
    """

    if not pattern or not cell_text:
        return pattern

    tokens = cell_text.split()

    if pattern not in tokens:
        return pattern

    def is_other_field(position: int) -> bool:
        token = tokens[position]
        upper = token.upper()
        return bool(
            (position > 0 and combine_load_speed(tokens[position - 1], token))
            or (brand and upper == str(brand).upper())
            or (position + 1 < len(tokens) and combine_load_speed(token, tokens[position + 1]))
            or detect_tire_size(token)
            or detect_load_speed(token)
            or detect_sidewall(token)
            or re.fullmatch(r"\d{1,2}\s*-?P\.?R\.?|P\.?R\.?", token, re.IGNORECASE)
            or upper in resolver.CONSTRUCTION_MARKERS
            or re.fullmatch(r"\d[\d,]*\.\d+", token)
            or CURRENCY_TOKEN.fullmatch(token)
        )

    index = tokens.index(pattern)
    start = end = index

    while start > 0 and not is_other_field(start - 1):
        start -= 1

    while end + 1 < len(tokens) and not is_other_field(end + 1):
        end += 1

    return " ".join(tokens[start:end + 1])


def _load_speed_in_column(text: str, letter_only: bool = True) -> str | None:
    """
    Load/speed in a load/speed column. The header can span two cells,
    so index and symbol arrive apart:

        114H      -> 114H
        114 H     -> 114H     (L/S header over two cells: 114 | H)
        95/93 R   -> 95/93R
        V         -> V        (speed symbol only, letter_only=True)
    """

    tokens = (text or "").split()

    for token in tokens:
        if detect_load_speed(token):
            return normalize_load_speed(token)

    for first, second in zip(tokens, tokens[1:]):
        joined = combine_load_speed(first, second)
        if joined:
            return normalize_load_speed(joined)

    if letter_only and detect_speed_symbol(text):
        return detect_speed_symbol(text).value

    return None


def _pattern_after_brand(
    cell_text: str,
    brand: str | None,
    resolver: TireProductResolver,
) -> str | None:
    """
    Pattern written right after the brand, also when it is only a
    number (the resolver never takes a lone number as pattern):

        165/65 R13 77T Achilles 122           -> 122
        215/45 ZR17 91W XL Achilles 2233      -> 2233
    """

    if not brand or not cell_text:
        return None

    tokens = cell_text.split()
    upper_tokens = [token.upper() for token in tokens]
    brand_words = str(brand).upper().split()

    for index in range(len(tokens) - len(brand_words) + 1):
        if upper_tokens[index:index + len(brand_words)] == brand_words:
            after = index + len(brand_words)
            if after < len(tokens):
                return _expand_in_cell(tokens[after], cell_text, resolver, brand)
            return None

    return None


def build_cells(
    values: dict[str, str],
    extra: list[str],
    hints: dict[str, str],
    resolver: TireProductResolver,
) -> dict[str, Any] | None:
    """
    Build one canonical row from column values.

    values: field -> text of that column
    extra:  text of unmapped columns before the business columns
            (by position these are descriptive)
    """

    all_text = " ".join(filter(None, values.values()))

    if SUMMARY_ROW.match(all_text.strip()):
        return None

    item_no = values.get("item_no") or None
    item_code = values.get("item_code") or None
    category_pattern = None
    extra = list(extra)

    # ITEM column: row number, code, or category + pattern.
    item = values.get("item", "")

    if item:
        category_match = CATEGORY_PATTERN.match(item)

        if re.fullmatch(r"\d{1,4}", item):
            item_no = item_no or item
        elif category_match and not detect_tire_size(item):
            category_pattern = category_match.group("pattern")
        elif CODE_TOKEN.fullmatch(item):
            item_code = item_code or item
        else:
            extra.insert(0, item)

    # ---------------------------------------------------------
    # Product fields
    # ---------------------------------------------------------

    descriptive = " ".join(
        filter(
            None,
            [values.get(name, "") for name in DESCRIPTIVE_FIELDS] + extra,
        )
    )
    descriptive = SPLIT_SIZE.sub(r"\1\2", descriptive)

    resolved = resolver.resolve(descriptive)

    size = None

    for source in (values.get("size", ""), values.get("description", ""), descriptive):
        detection = detect_tire_size(SPLIT_SIZE.sub(r"\1\2", source))
        if detection:
            size = detection.value
            break

    size = size or resolved.size

    # Load/speed column, validated by grammar ("88H 04" -> 88H).
    load_text = values.get("load_speed_rating", "")
    load_speed = _load_speed_in_column(load_text)

    # Load index and speed symbol in separate columns:
    #
    #   Load Index | Speed Symbol      91 | V   -> 91V
    #
    # A "Load Index" column holding the full rating (156/150L) is
    # taken as it is.
    if not load_speed:

        index_text = values.get("load_index", "")
        symbol_text = values.get("speed_symbol", "")

        full = _load_speed_in_column(index_text, letter_only=False) or _load_speed_in_column(symbol_text, letter_only=False)

        if full:
            load_speed = full
        else:
            joined = combine_load_speed(index_text or None, symbol_text or None)
            if joined:
                load_speed = normalize_load_speed(joined)
            elif not index_text and detect_speed_symbol(symbol_text):
                # Only the speed symbol is given.
                load_speed = detect_speed_symbol(symbol_text).value

    # Pattern column, validated: some sheets swap pattern and
    # load/speed columns.
    pattern = values.get("pattern") or None

    if pattern:

        category_match = CATEGORY_PATTERN.match(pattern)

        if category_match:
            pattern = category_match.group("pattern")

        if detect_load_speed(pattern) and not load_speed:
            load_speed = normalize_load_speed(pattern)
            pattern = load_text or None

        if pattern and detect_tire_size(pattern):
            pattern = None

    if not pattern and not category_pattern and size:
        pattern = _expand_in_cell(
            resolved.pattern,
            values.get("description", ""),
            resolver,
            values.get("brand") or resolved.brand,
        ) or _pattern_after_brand(
            values.get("description", ""),
            values.get("brand") or resolved.brand,
            resolver,
        )

    pattern = pattern or category_pattern

    # Tire-only inference applies to tire rows. Other goods keep
    # only what their columns say.
    if size:
        load_speed = load_speed or resolved.load_speed_rating

    # PR: PR column ("04", "8PR"), number beside load/speed
    # ("106/104R 08"), or the resolver.
    pr = None
    pr_text = values.get("pr", "")

    # Token by token: a neighbouring value can spill into the
    # column ("106/104R 08").
    for token in pr_text.split():

        if re.fullmatch(r"\d{1,2}", token) and int(token) > 0:
            pr = f"{int(token)}PR"
            break

        if re.fullmatch(r"\d{1,2}\s*-?P\.?R\.?", token, re.IGNORECASE):
            pr = normalize_pr(token)
            break

    if not pr:
        match = re.fullmatch(r"\S+\s+(\d{1,2})", load_text)
        if match and load_speed and int(match.group(1)) > 0:
            pr = f"{int(match.group(1))}PR"

    pr = normalize_pr(pr or resolved.pr) if size else normalize_pr(pr)

    sidewall = None

    for token in values.get("sidewall", "").split():
        detection = detect_sidewall(token)
        if detection:
            sidewall = detection.value
            break

    if size:
        sidewall = sidewall or resolved.sidewall

    brand = values.get("brand") or (resolved.brand if size else None)

    if brand and pattern and brand in pattern.split():
        brand = None

    # ---------------------------------------------------------
    # Business fields
    # ---------------------------------------------------------

    quantity_text = values.get("quantity", "")
    quantity = None
    unit = None

    for token in quantity_text.split():

        if quantity is None and NUMBER_TOKEN.fullmatch(token):
            quantity = _as_int(_first_number(token))

        elif UNIT_TOKEN.fullmatch(token):
            unit = unit or normalize_unit(token.rstrip("."))

    price_currency, unit_price = _money(values.get("unit_price", ""))
    amount_currency, amount = _money(values.get("amount", ""))

    # Currency written next to the quantity: "270 USD"
    quantity_currency = next(
        (
            normalize_currency(token)
            for token in quantity_text.split()
            if CURRENCY_TOKEN.fullmatch(token)
        ),
        None,
    )

    currency = (
        amount_currency
        or price_currency
        or quantity_currency
        or hints.get("currency")
        or "USD"
    )

    if isinstance(amount, float):
        amount = round(amount, 2)

    qty_in_40hq = _first_number(values.get("qty_in_40hq", ""))

    has_product = bool(size or pattern or values.get("description"))
    has_business = quantity is not None or amount is not None

    if not (has_product and has_business):
        return None

    if quantity is not None:
        unit = unit or values.get("unit") or hints.get("unit") or "PCS"
        unit = normalize_unit(unit)

    container_ratio = (
        quantity / qty_in_40hq
        if quantity is not None and qty_in_40hq
        else None
    )

    description = values.get("description") or " ".join(extra) or None

    return {
        "_tail": (descriptive.split() or [None])[-1],
        "item_no": item_code or item_no,
        "description": description,
        "brand": brand,
        "size": size,
        "pattern": pattern,
        "load_speed_rating": load_speed,
        "pr": pr,
        "sidewall": sidewall,
        "quantity": quantity,
        "unit": unit,
        "unit_price": unit_price,
        "amount": amount,
        "currency": currency,
        "qty_in_40hq": qty_in_40hq,
        "container_ratio": container_ratio,
    }


def row_values(
    cells: list[Any],
    layout: HeaderLayout,
) -> tuple[dict[str, str], list[str]]:
    """Group a row's cells by field (spanned columns are joined)."""

    values: dict[str, list[str]] = {}
    extra: list[str] = []
    business_seen = False

    for index, cell in enumerate(cells):

        text = clean_text(cell)

        if not text:
            continue

        field_name = layout.fields[index] if index < len(layout.fields) else None

        if field_name in BUSINESS_FIELDS:
            business_seen = True

        if field_name is None:
            # Descriptive fields are at the beginning of the row;
            # unmapped columns after the business values are remarks.
            if not business_seen:
                extra.append(text)
            continue

        if field_name in ("remark", "shipping_mark", "type"):
            continue

        values.setdefault(field_name, []).append(text)

    return {name: " ".join(parts) for name, parts in values.items()}, extra


def drop_empty_columns(rows: list[list[Any]]) -> list[list[Any]]:
    """
    Remove columns that are empty in every row. Continuation pages
    of the same table then have the same columns as the header page.
    """

    width = max((len(row) for row in rows), default=0)

    keep = [
        index
        for index in range(width)
        if any(
            index < len(row) and clean_text(row[index])
            for row in rows
        )
    ]

    return [
        [row[index] if index < len(row) else None for index in keep]
        for row in rows
    ]


def is_summary_row(cells: list[Any]) -> bool:
    """TOTAL:(3x40HC) | 3600 | 102384.00, SUB TOTAL AMOUNT ..."""

    return any(
        SUMMARY_ROW.match(clean_text(cell))
        for cell in cells
        if clean_text(cell)
    )


def keep_product_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _keep_product_rows(rows)
    fill_truncated_brands(rows)
    return rows


def _keep_product_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    When a table lists tire sizes, a row without a size is a
    summary or note, not a product:

        | 12HQ | | 14550 | | $267,465.00 |
    """

    if any(row.get("size") for row in rows):
        return [row for row in rows if row.get("size")]

    return rows


# =============================================================
# Extractor
# =============================================================

class GenericTableExtractor:
    """
    One instance per document: the header layout is carried over to
    continuation pages that repeat no header.
    """

    def __init__(self):
        self.resolver = TireProductResolver()
        self.grid_layout: HeaderLayout | None = None
        self.word_columns: list[tuple[float, float]] | None = None
        self.word_layout: HeaderLayout | None = None

    # ---------------------------------------------------------
    # Grid (bordered tables, Excel)
    # ---------------------------------------------------------

    def rows_from_grid(
        self,
        rows: list[list[Any]],
        carry_over: bool = True,
    ) -> list[dict[str, Any]]:

        rows = drop_empty_columns(rows)

        header = find_grid_header(rows)

        if header is not None:
            start, layout = header
            start += 1
            self.grid_layout = layout

        elif carry_over and self.grid_layout is not None and rows:

            # Continuation page without a header. Columns that are
            # empty in every product row (only a footer uses them)
            # are ignored, so the columns line up with the header
            # page again.
            if len(rows[0]) != len(self.grid_layout.fields):

                product_rows = [
                    row
                    for row in rows
                    if any(detect_tire_size(clean_text(cell)) for cell in row)
                ]

                keep = [
                    index
                    for index in range(len(rows[0]))
                    if any(
                        index < len(row) and clean_text(row[index])
                        for row in product_rows
                    )
                ]

                rows = [
                    [row[index] if index < len(row) else None for index in keep]
                    for row in rows
                ]

            if len(rows[0]) != len(self.grid_layout.fields):
                return []

            start, layout = 0, self.grid_layout

        else:
            return []

        result = []

        for cells in rows[start:]:

            if is_summary_row(cells):
                continue

            values, extra = row_values(cells, layout)

            built = build_cells(values, extra, layout.hints, self.resolver)

            if built is not None:
                result.append(built)

        return keep_product_rows(result)

    # ---------------------------------------------------------
    # Words (borderless tables, OCR lines)
    # ---------------------------------------------------------

    @staticmethod
    def _lines(words: list[dict]) -> list[list[dict]]:

        lines: list[list[dict]] = []

        for word in sorted(words, key=lambda w: (w["top"], w["x0"])):

            if lines and abs(word["top"] - lines[-1][0]["top"]) <= 3:
                lines[-1].append(word)
            else:
                lines.append([word])

        return [sorted(line, key=lambda w: w["x0"]) for line in lines]

    @staticmethod
    def _cells(line: list[dict], gap: float = 7.0) -> list[dict]:
        """Join words closer than `gap` into header cells."""

        cells: list[dict] = []

        for word in line:

            if cells and word["x0"] - cells[-1]["x1"] <= gap:
                cells[-1]["text"] += " " + word["text"]
                cells[-1]["x1"] = max(cells[-1]["x1"], word["x1"])
            else:
                cells.append(
                    {"text": word["text"], "x0": word["x0"], "x1": word["x1"]}
                )

        return cells

    def _find_word_header(self, lines):

        for index, line in enumerate(lines):

            cells = self._cells(line)
            layout = build_layout([cell["text"] for cell in cells])

            if is_valid_layout(layout):
                return index, cells, layout

        return None

    @staticmethod
    def _column_boundaries(cells: list[dict], data_lines: list[list[dict]]) -> list[float]:
        """
        Boundary between each pair of header cells.

        Header labels are often centered over left-aligned text:

            No.            Description        u.o.m
            1  165/65 R13 77T Achilles 122    Pcs

        so halfway between the labels can cut through the text. The
        boundary is put in the widest gap that no data word crosses
        (the gutter between the columns); halfway between the labels
        only when there is no such gap.
        """

        # Product rows only: text lines with a tire size or two numbers.
        rows = [
            line
            for line in data_lines
            if contains_tire_size(" ".join(w["text"] for w in line))
            or sum(1 for w in line if NUMBER_TOKEN.fullmatch(w["text"].replace("$", ""))) >= 2
        ]

        occupied = sorted((w["x0"], w["x1"]) for line in rows for w in line)

        boundaries = []

        for left_cell, right_cell in zip(cells, cells[1:]):

            low = (left_cell["x0"] + left_cell["x1"]) / 2
            high = (right_cell["x0"] + right_cell["x1"]) / 2
            fallback = (left_cell["x1"] + right_cell["x0"]) / 2

            if not occupied:
                boundaries.append(fallback)
                continue

            # Free gaps inside (low, high).
            gaps = []
            cursor = low

            for x0, x1 in occupied:
                if x1 <= cursor:
                    continue
                if x0 >= high:
                    break
                if x0 > cursor:
                    gaps.append((cursor, x0))
                cursor = max(cursor, x1)

            if cursor < high:
                gaps.append((cursor, high))

            # A gap touching the label centers is only half a gutter.
            inner = [g for g in gaps if g[0] > low and g[1] < high] or gaps

            if inner:
                gap = max(inner, key=lambda g: g[1] - g[0])
                boundaries.append((gap[0] + gap[1]) / 2)
            else:
                boundaries.append(fallback)

        return boundaries

    def rows_from_words(self, words: list[dict]) -> list[dict[str, Any]]:

        lines = self._lines(words)

        header = self._find_word_header(lines)

        if header is not None:
            index, cells, layout = header
            start = index + 1

            boundaries = self._column_boundaries(cells, lines[start:])

            columns = [
                (
                    boundaries[position - 1] if position > 0 else float("-inf"),
                    boundaries[position] if position < len(boundaries) else float("inf"),
                )
                for position in range(len(cells))
            ]

            self.word_columns = columns
            self.word_layout = layout

        elif self.word_columns is not None:
            start = 0
            columns, layout = self.word_columns, self.word_layout

        else:
            return []

        result = []

        for line in lines[start:]:

            cells = [[] for _ in columns]

            for word in line:
                center = (word["x0"] + word["x1"]) / 2
                for position, (left, right) in enumerate(columns):
                    if left <= center < right:
                        cells[position].append(word["text"])
                        break

            texts = [" ".join(cell) for cell in cells]

            if is_summary_row(texts):
                if result:
                    break
                continue

            values, extra = row_values(texts, layout)

            # Borderless: text lines can line up with the columns by
            # chance, so demand a tire size or all business values.
            if len(values) < 3:
                continue

            built = build_cells(values, extra, layout.hints, self.resolver)

            if built is None:
                continue

            if not (
                built["size"]
                or (
                    built["quantity"] is not None
                    and built["unit_price"] is not None
                    and built["amount"] is not None
                )
            ):
                continue

            result.append(built)

        return keep_product_rows(result)


# =============================================================
# Tables
# =============================================================

def table_value(cells: dict[str, Any], header: str) -> Any:
    """
    Output value of a column. Load/speed is shown as two columns,
    split from the detected rating (106/104R -> 106/104 | R).
    """

    if header in ("load_index", "speed_rating"):
        load_index, speed_rating = split_load_speed(cells.get("load_speed_rating"))
        return load_index if header == "load_index" else speed_rating

    # Brand as written in the brand list (LANDSAIL -> Landsail when the
    # list says so), also when it comes from a Brand column.
    if header == "brand":
        return canonical_brand(cells.get("brand"))

    if header == "size":
        return format_size(cells.get("size"))

    return cells.get(header)


def rows_to_table(
    rows: list[dict[str, Any]],
    table_id: str,
    page: int | None,
    method: str,
    headers: list[str] = CANONICAL_HEADERS,
) -> Table:

    if not any(row.get("size") for row in rows):
        headers = GENERAL_HEADERS

    return Table(
        table_id=table_id,
        page=page,
        headers=headers,
        rows=[[table_value(row, header) for header in headers] for row in rows],
        extraction_method=method,
    )


def table_score(table: Table | None) -> tuple[int, int, int]:
    """
    (tire rows, complete rows, filled key fields).

    Tire rows (a tire size plus quantity or amount) are compared first:
    on a tire invoice a table with sizes always beats one without.
    Then complete rows (a product plus quantity or amount), so a
    strategy cannot win by filling cells with guesses; equal tables are
    decided by the caller's preference order.
    """

    if table is None:
        return (0, 0, 0)

    def column(name):
        return table.headers.index(name) if name in table.headers else None

    product = [column("size"), column("description")]
    business = [column("quantity"), column("amount")]

    def filled(row, index):
        return index is not None and index < len(row) and row[index] not in (None, "")

    complete = sum(
        1
        for row in table.rows
        if any(filled(row, i) for i in product)
        and any(filled(row, i) for i in business)
    )

    tire_rows = sum(
        1
        for row in table.rows
        if filled(row, column("size"))
        and any(filled(row, i) for i in business)
    )

    return (tire_rows, complete, _filled_fields(table))


def _filled_fields(table: Table) -> int:

    key_fields = [
        "size",
        "pattern",
        "brand",
        "load_index",
        "speed_rating",
        "quantity",
        "unit_price",
        "amount",
    ]

    indexes = [
        table.headers.index(name)
        for name in key_fields
        if name in table.headers
    ]

    return sum(
        1
        for row in table.rows
        for index in indexes
        if index < len(row) and row[index] not in (None, "")
    )


def raw_table(
    rows: list[list[Any]],
    table_id: str,
    page: int | None,
) -> Table | None:
    """
    The table exactly as found. First row with two or more values
    is the header.
    """

    cleaned = [
        [clean_text(cell) for cell in row]
        for row in rows
        if any(clean_text(cell) for cell in row)
    ]

    header_index = next(
        (
            index
            for index, row in enumerate(cleaned)
            if sum(1 for cell in row if cell) >= 2
        ),
        None,
    )

    if header_index is None or header_index + 1 >= len(cleaned):
        return None

    headers = cleaned[header_index]

    return Table(
        table_id=table_id,
        page=page,
        headers=[cell or f"column_{i + 1}" for i, cell in enumerate(headers)],
        rows=cleaned[header_index + 1:],
        extraction_method="raw",
    )
