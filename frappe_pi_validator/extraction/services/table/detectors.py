from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Detection:
    value: str
    start: int
    end: int


# ---------------------------------------------------------
# Tire size
# ---------------------------------------------------------
#
# Supports:
#
# 185/60R15
# 185/60R15PR
# 235/45ZR17PR
# 195R15C-8PR
# 7.50R16-14PR
#
# Also supports:
#
# TH185/60R15PR
# TH195R15C-8PR
# TH7.50R16-14PR
#
# And P-metric / LT, truck and bias forms:
#
# P225/70R15
# 7.50R16LT
# 315/80R22.5, 11R22.5, 12.00R20
# 31X10.50R15
# 7.50-16
#
# The optional final construction letter is consumed only
# when it is NOT followed by R.
#
# This is important for:
#
# 185/60R15PR
#
# where P belongs to PR, not to the tire size.
# ---------------------------------------------------------

TIRE_SIZE_PATTERN = re.compile(
    r"""
    (?<![A-Z0-9])
    (?:
        TH(?P<th_size>
            \d{3}/\d{2}Z?R\d{2}
            (?:[A-Z](?!R))?
            |
            \d{3}R\d{2}
            (?:[A-Z](?!R))?
            |
            \d\.\d{2}R\d{2}
            (?:[A-Z](?!R))?
        )
        |
        (?P<size>
            # P-metric / light-truck prefix: P225/70R15, LT265/75R16
            (?:P|LT)?
            (?:
                \d{2}X\d{1,2}\.\d{2}Z?R\d{2}      # 31X10.50R15
                |
                \d{3}/\d{2}(?:\.\d)?Z?R\d{2}(?:\.5)?   # 205/55R16, 315/80R22.5
                |
                \d{3}R\d{2}(?:\.5)?                # 185R14C, 385R22.5
                |
                \d{1,2}\.\d{2}R\d{2}(?:\.5)?     # 7.50R16, 12.00R20
                |
                \d{2}R\d{2}(?:\.5)?                # 11R22.5, 12R22.5
                |
                \d{1,2}\.\d{2}-\d{2}(?:\.5)?     # 7.50-16 (bias)
            )
            # Suffix: 195R15C, 7.50R16LT
            (?:LT|[A-Z](?!R))?
        )
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_tire_size(text: str) -> Detection | None:
    match = TIRE_SIZE_PATTERN.search(text)

    if not match:
        return None

    if match.group("th_size"):
        size = match.group("th_size")
        start = match.start("th_size")
    else:
        size = match.group("size")
        start = match.start("size")

    return Detection(
        value=size,
        start=start,
        end=start + len(size),
    )

def contains_tire_size(text: str) -> bool:
    return detect_tire_size(text) is not None


# ---------------------------------------------------------
# Load / speed rating
# ---------------------------------------------------------
#
# Supports standard forms:
#
# 84H
# 86T
# 97W
# 97W XL
# 94WXL
# 106/104R
# 123/119L
#
# Also supports Landsail/OCR forms:
#
# 114/XL_V
# 110/XL_V
# 106/XL_W
# 113/XL_V
# 115_V
# 113_H
# 109/107_T
# 82_H
#
# The Landsail forms are preserved exactly as detected.
# ---------------------------------------------------------

LOAD_SPEED_PATTERN = re.compile(
    r"""
    ^
    (?:
        # Standard single load/speed:
        # 84H
        # 86T
        # 97W
        # 94WXL
        \d{2,3}[A-Z](?:\s*XL)?

        |

        # Standard dual load/speed:
        # 106/104R
        # 123/119L
        \d{2,3}/\d{2,3}[A-Z](?:\s*XL)?

        |

        # Landsail / OCR notation:
        # 114/XL_V
        # 110/XL_V
        # 106/XL_W
        # 113/XL_V
        \d{2,3}/XL_[A-Z]

        |

        # Landsail single-index notation:
        # 115_V
        # 113_H
        # 82_H
        \d{2,3}_[A-Z]

        |

        # Landsail dual-index notation:
        # 109/107_T
        \d{2,3}/\d{2,3}_[A-Z]
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_load_speed(text: str) -> Detection | None:
    value = text.strip()

    match = LOAD_SPEED_PATTERN.fullmatch(value)

    if not match:
        return None

    # Keep the original notation.
    #
    # For standard forms this preserves the old behavior:
    #
    #   103WXL -> 103W
    #
    # For Landsail forms:
    #
    #   114/XL_V -> 114/XL_V
    #   113_H   -> 113_H
    #   109/107_T -> 109/107_T
    #
    # This is intentional because the underscore notation
    # is part of the source document's product specification.

    if re.fullmatch(
        r"\d{2,3}[A-Z](?:\s*XL)?",
        value,
        re.IGNORECASE,
    ):
        detected = re.sub(
            r"\s*XL$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
    else:
        detected = value

    return Detection(
        value=detected,
        start=0,
        end=len(value),
    )


# ---------------------------------------------------------
# PR
# ---------------------------------------------------------
#
# Supports:
#
# 8PR
# 8 PR
# 8 P.R.
# PR8
# PR 8
# -8PR
#
# IMPORTANT:
#
# It intentionally does NOT match the "15PR" in:
#
# 185/60R15PR
#
# because that is part of the tire-size expression.
#
# The compact parser handles bare "PR" after the size
# separately and interprets it as the default PR.
# ---------------------------------------------------------

PR_PATTERN = re.compile(
    r"""
    (?:
        (?<![A-Z0-9])
        (?P<number>\d+)
        \s*P\.?\s*R\.?
        |
        (?<![A-Z0-9])
        P\.?\s*R\.?\s*
        (?P<number_reverse>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_pr(text: str) -> Detection | None:
    match = PR_PATTERN.search(text)

    if not match:
        return None

    number = (
        match.group("number")
        or match.group("number_reverse")
    )

    return Detection(
        value=f"{number}PR",
        start=match.start(),
        end=match.end(),
    )


# ---------------------------------------------------------
# Quantity
# ---------------------------------------------------------

QUANTITY_PATTERN = re.compile(
    r"""
    ^
    (?P<quantity>[\d,]+)
    \s*
    (?P<unit>PCS?|EA|SETS?|UNIT[S]?)\.?
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_quantity(text: str) -> Detection | None:
    value = text.strip()

    match = QUANTITY_PATTERN.fullmatch(value)

    if not match:
        return None

    quantity = match.group("quantity").replace(",", "")
    unit = match.group("unit").upper()

    return Detection(
        value=f"{quantity} {unit}",
        start=0,
        end=len(value),
    )


# ---------------------------------------------------------
# Sidewall
# ---------------------------------------------------------

SIDEWALL_VALUES = {
    "BS",
    "RW",
    "RWL",
    "BSW",
    "WSW",
    "OWL",
    "WR",
    "WW",
}


def detect_sidewall(text: str) -> Detection | None:
    value = text.strip().upper()

    if value in SIDEWALL_VALUES:
        return Detection(
            value=value,
            start=0,
            end=len(value),
        )

    return None


# ---------------------------------------------------------
# Amount
# ---------------------------------------------------------

AMOUNT_PATTERN = re.compile(
    r"""
    ^
    (?P<currency>[A-Z$€£¥]+)?
    \s*
    (?P<amount>[\d,]+(?:\.\d+)?)
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_amount(text: str) -> Detection | None:
    value = text.strip()

    match = AMOUNT_PATTERN.fullmatch(value)

    if not match:
        return None

    currency = (
        match.group("currency") or ""
    ).strip()

    amount = match.group("amount")

    result = (
        f"{currency}{amount}"
        if currency
        else amount
    )

    return Detection(
        value=result,
        start=0,
        end=len(value),
    )


# ---------------------------------------------------------
# Number
# ---------------------------------------------------------

NUMBER_PATTERN = re.compile(
    r"^[\d,]+(?:\.\d+)?$"
)


def detect_number(text: str) -> Detection | None:
    value = text.strip()

    if not NUMBER_PATTERN.fullmatch(value):
        return None

    return Detection(
        value=value,
        start=0,
        end=len(value),
    )


# ---------------------------------------------------------
# Tire row
# ---------------------------------------------------------

def is_tire_row(text: str) -> bool:
    return contains_tire_size(text)