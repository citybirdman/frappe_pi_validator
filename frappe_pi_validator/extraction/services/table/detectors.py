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
# Every standard tire size system:
#
#   Metric (ISO)     205/55R16  205/55 R16  225/40ZR18  205/55VR16
#                    P215/65R15  LT265/75R16  ST205/75R15  T125/70D17
#                    195/65B15 (bias belted)  315/80R22.5  215/75R17.5
#                    IF710/70R42  VF600/70R30  420/85R34 (agricultural)
#   Motorcycle       120/70ZR17  90/90-21  80/100-21  130/70-12  MT90-16
#   Alpha-numeric    185R14C  155R12C  165SR13  185HR14  205R16
#   Numeric (bias)   7.50R16  7.50-16  12.00R20  11.00-20  6.00-9  3.00-18
#   Agricultural     18.4-38  14.9-24  23.5R25  16.9R28  30.5L-32
#   Truck            11R22.5  12R22.5  9.5R17.5  10-16.5 (skid steer)
#   Flotation        31X10.50R15LT  33X12.50R20  35x12.5R17  28x9-15  18x7-8
#   Millimetric TRX  220/55VR390
#   Slash rim        205/55/16
#
# Suffixes kept with the size: C (commercial), LT (light truck).
# A "TH" source prefix is not part of the size (TH185/60R15PR).
#
# Every match is range-checked (width, aspect ratio, rim), so dates,
# prices, phone numbers and codes are not taken as sizes.
# ---------------------------------------------------------

_RIM = r"\d{1,2}(?:\.\d)?"            # 8, 16, 22.5, 17.5, 15.3
_SUFFIX = r"(?:LT|C(?![A-Z]))?"        # 195R14C, 7.50R16LT

TIRE_SIZE_PATTERN = re.compile(
    rf"""
    (?<![A-Z0-9./-])
    (?:TH)?                                    # source prefix, not part of the size
    (?P<size>
        # Flotation: 31X10.50R15, 28x9-15, 18x7-8
        (?P<flo_od>\d{{2}})\s?X\s?(?P<flo_w>\d{{1,2}}(?:\.\d{{1,2}})?)
        (?:\s?[RDB]\s?|-){_RIM}
        |
        # Millimetric (TRX): 220/55VR390
        (?P<trx_w>\d{{3}})/(?P<trx_a>\d{{2}})\s?[VHZ]?R\s?(?P<trx_rim>\d{{3}})
        |
        # Metric: 205/55R16, 205/55 ZR 16, P215/65R15, 90/90-21, 195/65B15
        (?:P|LT|ST|T|IF|VF)?
        (?P<met_w>\d{{2,3}})\s?/\s?(?P<met_a>\d{{2,3}})
        (?:\s?[ZVHWY]?\s?[RDB]\s?|-)(?P<met_rim>{_RIM})
        |
        # Slash rim: 205/55/16
        (?P<sl_w>\d{{3}})/(?P<sl_a>\d{{2}})/(?P<sl_rim>\d{{2}})
        |
        # Numeric / agricultural: 7.50R16, 7.50-16, 12.00R20, 18.4-38, 30.5L-32
        (?:LT)?(?P<num_w>\d{{1,2}}\.\d{{1,2}})(?:\s?[RDB]\s?|L?-)(?P<num_rim>{_RIM})
        |
        # Skid steer: 10-16.5, 12-16.5, 14-17.5
        (?P<sk_w>\d{{2}})-(?P<sk_rim>\d{{2}}\.5)
        |
        # Truck, integer width: 11R22.5, 12R22.5, 12R20
        (?P<int_w>\d{{2}})R(?P<int_rim>\d{{2}}(?:\.5)?)
        |
        # Alpha-numeric: 185R14C, 165SR13, 185HR14, 205R16
        (?P<al_w>\d{{3}})[SHTVZ]?R(?P<al_rim>\d{{2}})
        |
        # Motorcycle alpha: MT90-16, MU85B16
        M[A-Z](?P<mo_a>\d{{2}})[-B](?P<mo_rim>\d{{2}})
    )
    {_SUFFIX}
    (?![\d.])
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _in(value, low, high) -> bool:
    return value is not None and low <= float(value) <= high


def _valid_size(match: re.Match) -> bool:
    """Width / aspect ratio / rim within real tire ranges."""

    g = match.groupdict()

    if g["flo_od"]:
        return _in(g["flo_od"], 10, 66) and _in(g["flo_w"], 3, 25)

    if g["trx_w"]:
        return _in(g["trx_w"], 140, 280) and _in(g["trx_a"], 40, 80) and _in(g["trx_rim"], 340, 460)

    if g["met_w"]:
        width = float(g["met_w"])
        return (
            _in(width, 60, 900)
            and _in(g["met_a"], 25, 110)
            and _in(g["met_rim"], 8, 54)
            # passenger / truck widths end in 0 or 5 (205, 315); motorcycle 2-digit widths vary
            and (width < 100 or width % 5 == 0)
        )

    if g["sl_w"]:
        return _in(g["sl_w"], 125, 355) and _in(g["sl_a"], 25, 95) and _in(g["sl_rim"], 12, 24) \
            and float(g["sl_w"]) % 5 == 0 and float(g["sl_a"]) % 5 == 0

    if g["num_w"]:
        # Two decimals (7.50-16, 3.50-4): rims from 4". One decimal is
        # agricultural (18.4-38, 23.5R25): wide tires on big rims.
        if len(g["num_w"].split(".")[1]) == 1:
            return _in(g["num_w"], 5, 45) and _in(g["num_rim"], 8, 54)
        return _in(g["num_w"], 2.5, 45) and _in(g["num_rim"], 4, 54)

    if g["sk_w"]:
        return _in(g["sk_w"], 8, 16)

    if g["int_w"]:
        return _in(g["int_w"], 8, 16) and _in(g["int_rim"], 15, 24.5)

    if g["al_w"]:
        return _in(g["al_w"], 125, 235) and float(g["al_w"]) % 5 == 0 and _in(g["al_rim"], 10, 16)

    if g["mo_a"]:
        return _in(g["mo_a"], 60, 100) and _in(g["mo_rim"], 10, 23)

    return False


def _normalize_size(text: str) -> str:
    """205/55 r 16 -> 205/55R16, 31x10.50r15lt -> 31X10.50R15LT."""

    return re.sub(r"\s+", "", text).upper()


def detect_tire_size(text: str) -> Detection | None:
    position = 0

    while True:
        match = TIRE_SIZE_PATTERN.search(text, position)

        if not match:
            return None

        if _valid_size(match):
            # Span of the size as written (callers mask/split by it);
            # value in compact standard form.
            end = match.end()
            return Detection(
                value=_normalize_size(text[match.start("size"):end]),
                start=match.start("size"),
                end=end,
            )

        position = match.start() + 1


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

# Load / speed formula (ISO 4000 / ETRTO service description):
#
#     LI [ / LI2 ] SS          91V, 106/104R, 156/150L, 98(Y)
#
#     LI   load index 0-279 (max load per tire)
#     LI2  dual-fitment load index, lower than LI
#     SS   speed symbol: A1-A8 (agricultural / industrial), B-H, J-N,
#          P-W, Y, Z or (Y); A, I, O, X alone are never speed symbols

SPEED_SYMBOL = r"(?:A[1-8]|[B-HJ-NP-WYZ]|\(Y\))"

MAX_LOAD_INDEX = 279

LOAD_SPEED_PATTERN = re.compile(
    rf"""
    ^
    (?:
        # Standard single load/speed:
        # 84H
        # 86T
        # 97W
        # 94WXL
        # 98(Y)
        (?P<li>\d{{2,3}}){SPEED_SYMBOL}(?:\s*XL)?

        |

        # Standard dual load/speed:
        # 106/104R
        # 123/119L
        (?P<dual_li>\d{{2,3}})/(?P<dual_li2>\d{{2,3}}){SPEED_SYMBOL}(?:\s*XL)?

        |

        # Landsail / OCR notation:
        # 114/XL_V
        # 110/XL_V
        # 106/XL_W
        # 113/XL_V
        (?P<xl_li>\d{{2,3}})/XL_{SPEED_SYMBOL}

        |

        # Landsail single-index notation:
        # 115_V
        # 113_H
        # 82_H
        (?P<us_li>\d{{2,3}})_{SPEED_SYMBOL}

        |

        # Landsail dual-index notation:
        # 109/107_T
        (?P<us_dual_li>\d{{2,3}})/(?P<us_dual_li2>\d{{2,3}})_{SPEED_SYMBOL}
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _valid_load_indexes(match: re.Match) -> bool:
    """LI within 0-279; in a dual rating the second index is lower."""

    single = next(
        (
            match.group(name)
            for name in ("li", "xl_li", "us_li")
            if match.group(name)
        ),
        None,
    )

    if single is not None:
        return int(single) <= MAX_LOAD_INDEX

    first = match.group("dual_li") or match.group("us_dual_li")
    second = match.group("dual_li2") or match.group("us_dual_li2")

    return int(first) <= MAX_LOAD_INDEX and int(second) < int(first)


def split_load_speed(value) -> tuple[str | None, str | None]:
    """
    Load/speed rating -> (load index, speed rating):

        91V       -> ("91", "V")
        106/104R  -> ("106/104", "R")
        114/XL_V  -> ("114", "V")      Landsail notation
        109/107_T -> ("109/107", "T")
        98(Y)     -> ("98", "(Y)")
        146A8     -> ("146", "A8")
        V         -> (None, "V")       speed rating only
    """

    if value in (None, ""):
        return None, None

    text = re.sub(r"\s*XL$", "", str(value).strip(), flags=re.IGNORECASE).upper()

    if re.fullmatch(SPEED_SYMBOL, text, re.IGNORECASE):
        return None, text

    match = re.fullmatch(
        rf"(?P<li>\d{{2,3}}(?:/\d{{2,3}})?)(?:/XL_|_)?(?P<ss>{SPEED_SYMBOL})",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None, None

    return match.group("li"), match.group("ss").upper()


def detect_speed_symbol(text) -> Detection | None:
    """
    Speed symbol written alone (no load index): V, H, (Y).

    Only meaningful where the position says it is a load/speed
    value (its own column); a letter inside free text is not.
    """

    if text is None:
        return None

    value = str(text).strip().upper()

    if not re.fullmatch(SPEED_SYMBOL, value, re.IGNORECASE):
        return None

    return Detection(value=value, start=0, end=len(value))


def combine_load_speed(load_index, speed_symbol) -> str | None:
    """
    Load index and speed symbol written apart:

        91 | V        -> 91V
        106/104 | R   -> 106/104R

    Returns the joined value only when it fits the formula.
    """

    if load_index is None or speed_symbol is None:
        return None

    load_index = str(load_index).strip()
    speed_symbol = str(speed_symbol).strip().upper()

    if isinstance(load_index, str) and load_index.endswith(".0"):
        load_index = load_index[:-2]

    if not re.fullmatch(r"\d{2,3}(?:/\d{2,3})?", load_index):
        return None

    if not re.fullmatch(SPEED_SYMBOL, speed_symbol, re.IGNORECASE):
        return None

    detection = detect_load_speed(load_index + speed_symbol)

    return detection.value if detection else None


def detect_load_speed(text: str) -> Detection | None:
    value = text.strip()

    match = LOAD_SPEED_PATTERN.fullmatch(value)

    if not match or not _valid_load_indexes(match):
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
        rf"\d{{2,3}}{SPEED_SYMBOL}(?:\s*XL)?",
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