"""
Tire brands.

KNOWN_BRANDS are matched first, whole-word and case-insensitive
(Achilles, ACHILLES), and shown as written in the list. In Frappe the
list is replaced by the site's Brand records (set_known_brands).
Brands not listed are still found by the resolver's single-word rule
(an upper-case word in its own column), so new suppliers keep working.

Brand names that are also ordinary words (General, Radar, Atlas,
Fortune, Torque ...) are left out on purpose: they would be matched
inside descriptions by mistake. Add names here as new suppliers appear.
"""

from __future__ import annotations

import re

KNOWN_BRANDS = [
    # Multi-word names first, so they win over their single words.
    "BF GOODRICH", "DOUBLE COIN", "GT RADIAL", "LING LONG", "ROYAL BLACK",
    "ACCELERA", "ACHILLES", "AEOLUS", "AMBERSTONE", "ANNAITE", "ANTARES",
    "APLUS", "APOLLO", "ARIVO", "ARMSTRONG", "AUFINE", "AUSTONE",
    "AUTOGREEN", "AVON", "BARUM", "BFGOODRICH", "BLACKLION", "BOTO",
    "BRIDGESTONE", "CEAT", "CHAOYANG", "COMPASAL", "CONTINENTAL", "COOPER",
    "DAYTON", "DEBICA", "DEESTONE", "DELINTE", "DOUBLECOIN", "DOUBLESTAR",
    "DUNLOP", "DURATURN", "DYNAMO", "ECOVISION", "EVERGREEN", "FALKEN",
    "FIREMAX", "FIRESTONE", "FRIEZZA", "FULDA", "GISLAVED", "GITI",
    "GLEDE", "GOFORM", "GOODRIDE", "GOODTRIP", "GOODYEAR", "GREMAX",
    "GRENLANDER", "GTRADIAL", "HABILEAD", "HAIDA", "HANKOOK", "HEADWAY",
    "HIFLY", "HILO", "INVOVIC", "JINYU", "JOYROAD", "KAPSEN", "KELLY",
    "KENDA", "KINFOREST", "KINGRUN", "KLEBER", "KORMORAN", "KUMHO",
    "LAKESEA", "LANDSAIL", "LASSA", "LAUFENN", "LEAO", "LINGLONG",
    "LONGMARCH", "MARSHAL", "MASTERCRAFT", "MATADOR", "MAXTREK", "MAXXIS",
    "MAZZINI", "MICHELIN", "MILESTAR", "MINERVA", "NANKANG", "NEOLIN",
    "NEXEN", "NITTO", "NOKIAN", "OVATION", "PETLAS", "PIRELLI", "RIKEN",
    "ROADKING", "ROADONE", "ROADSTONE", "ROADWING", "ROADX", "ROTALLA",
    "ROYALBLACK", "SAILUN", "SAMSON", "SAVA", "SEIBERLING", "SEMPERIT",
    "SENTURY", "SUMITOMO", "SUNFULL", "SUPERIA", "TECHKING", "THREE-A",
    "TIGAR", "TOYO", "TRACMAX", "TRIANGLE", "UNIROYAL", "VREDESTEIN",
    "WANLI", "WESTLAKE", "WINDFORCE", "WINRUN", "YOKOHAMA", "ZEETEX",
    "ZETA",
]

# Words used in tread / product names; never a brand.
NOT_BRANDS = {
    "ALL", "SEASON", "SEASONS", "SPORT", "SPORTS", "CITY", "PLUS", "ECO",
    "TOURING", "WINTER", "SUMMER", "ENDURO", "CLASSIC", "TRAILER",
    "DRIVE", "STEER", "CARGO", "VAN", "RADIAL", "TRUCK", "HIGHWAY",
    "TERRAIN", "MUD", "ROAD", "EXTRA", "LOAD", "TUBELESS", "DESERT",
    "HAWK", "COMFORT", "PREMIUM", "ULTRA", "SUPER", "SPEED", "GRIP",
    "POWER", "MAX", "PRO", "TOUR", "LIGHT", "HEAVY", "DUTY", "SNOW",
    "RAIN", "WET", "DRY", "TRAIL", "RIB", "LUG", "TRACTION", "UHP",
}

# Brand list in use. Replaced by set_known_brands(), e.g. with the
# Brand records of a Frappe / ERPNext site.
_active_brands: list[str] = list(KNOWN_BRANDS)
_regex_cache: dict[tuple, re.Pattern] = {}


def set_known_brands(names) -> None:
    """
    Use this brand list instead of KNOWN_BRANDS (as written, e.g. the
    Brand records of a Frappe site). An empty list keeps KNOWN_BRANDS.
    """

    global _active_brands

    cleaned = [" ".join(str(name).split()) for name in (names or []) if str(name or "").strip()]
    _active_brands = cleaned or list(KNOWN_BRANDS)


def known_brands() -> list[str]:
    return list(_active_brands)


def _key(name: str) -> str:
    """Double Star, DOUBLESTAR, Double-Star -> DOUBLESTAR."""

    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _name_regex(name: str) -> str:
    """Letters of the name, spaces / hyphens between them optional."""

    letters = [re.escape(ch) for ch in re.sub(r"[\s\-]", "", name)]

    return r"[\s\-]?".join(letters)


def _brand_regex() -> re.Pattern:
    key = tuple(_active_brands)

    if key not in _regex_cache:
        # Longest names first: "Double Coin" wins over "Double".
        names = sorted(set(_active_brands), key=len, reverse=True)
        _regex_cache.clear()
        _regex_cache[key] = re.compile(
            r"(?<![A-Z0-9-])("
            + "|".join(_name_regex(name) for name in names)
            + r")(?![A-Z0-9-])",
            re.IGNORECASE,
        )

    return _regex_cache[key]


def find_known_brand(text: str) -> tuple[str, int, int] | None:
    """(brand as written in the brand list, start, end) of the first known brand."""

    if not _active_brands:
        return None

    match = _brand_regex().search(text or "")

    if not match:
        return None

    found = _key(match.group(1))
    canonical = next(
        (name for name in _active_brands if _key(name) == found),
        " ".join(match.group(1).upper().split()),
    )

    return canonical, match.start(1), match.end(1)


def canonical_brand(value):
    """Known brand as written in the brand list (Achilles, ACHILLES -> list form)."""

    if value in (None, ""):
        return value

    text = " ".join(str(value).split())
    found = find_known_brand(text)

    if found and found[1] == 0 and found[2] == len(text):
        return found[0]

    return value


def is_not_brand(word: str) -> bool:
    return str(word).upper() in NOT_BRANDS
