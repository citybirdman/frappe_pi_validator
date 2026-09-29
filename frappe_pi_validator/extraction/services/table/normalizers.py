from __future__ import annotations

import re
from typing import Any


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_pr(value: str | None) -> str | None:
    """
    8PR, 8 P.R., PR8, 04PR -> 8PR / 4PR.

    A valid ply rating is a multiple of 2: 2PR, 4PR, 6PR, 8PR, 10PR ...
    No PR in the document, or an odd / zero number (5PR, 9PR, 0PR)
    -> None.
    """

    if not value:
        return None

    text = normalize_text(value)

    match = re.search(
        r"""
        (?:
            (?P<number>\d+)\s*P\.?\s*R\.?
            |
            P\.?\s*R\.?\s*(?P<number_reverse>\d+)
        )
        """,
        text,
        re.IGNORECASE | re.VERBOSE,
    )

    if not match:
        return None

    number = int(match.group("number") or match.group("number_reverse"))

    # Multiple of 2: 2, 4, 6, 8, 10 ...
    if number < 2 or number % 2:
        return None

    return f"{number}PR"


def normalize_quantity(value: str | None) -> int | None:
    if not value:
        return None

    match = re.search(r"[\d,]+", value)

    if not match:
        return None

    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def normalize_number(value: str | None) -> float | None:
    if value is None:
        return None

    text = normalize_text(value)

    if not text:
        return None

    text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def normalize_currency(value: str | None) -> str | None:
    """Currency as ISO code: USD, US$, $ -> USD; EUR / GBP likewise."""

    if not value:
        return None

    text = normalize_text(value).upper()

    if text.startswith(("US$", "USD", "$")):
        return "USD"

    if text.startswith("€"):
        return "EUR"

    if text.startswith("£"):
        return "GBP"

    return text


def split_currency_amount(value: str) -> tuple[str | None, float | None]:
    text = normalize_text(value)

    match = re.match(
        r"^(US\$|USD|\$|EUR|€|GBP|£)?\s*([\d,]+(?:\.\d+)?)$",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None, None

    currency = normalize_currency(match.group(1))
    amount = normalize_number(match.group(2))

    return currency, amount


def normalize_load_speed(value: str | None) -> str | None:
    """
    XL (reinforced) is not part of the load/speed rating:

        97W XL -> 97W
        112HXL -> 112H
        114/XL_V -> 114/XL_V   (Landsail notation, kept)
    """

    if not value:
        return None

    text = normalize_text(value)

    text = re.sub(
        r"\s*XL$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.upper()


def normalize_unit(value: str | None) -> str | None:
    if not value:
        return None

    text = normalize_text(value).upper().rstrip(".")

    mapping = {
        "PC": "PCS",
        "PCS": "PCS",
        "EA": "EA",
        "SET": "SET",
        "SETS": "SETS",
        "UNIT": "UNIT",
        "UNITS": "UNITS",
    }

    return mapping.get(text, text)
