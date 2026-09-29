from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from frappe_pi_validator.extraction.services.table.detectors import (
    combine_load_speed,
    detect_load_speed,
    detect_pr,
    detect_sidewall,
    detect_tire_size,
)


@dataclass
class FieldMatch:
    value: str
    confidence: float
    start: int
    end: int
    reason: str


@dataclass
class TireProductFields:
    size: Optional[str] = None
    pr: Optional[str] = None
    pattern: Optional[str] = None
    load_speed_rating: Optional[str] = None
    brand: Optional[str] = None
    sidewall: Optional[str] = None

    size_match: Optional[FieldMatch] = None
    pr_match: Optional[FieldMatch] = None
    pattern_match: Optional[FieldMatch] = None
    load_speed_match: Optional[FieldMatch] = None
    brand_match: Optional[FieldMatch] = None
    sidewall_match: Optional[FieldMatch] = None


class TireProductResolver:
    """
    Semantic resolver for tire product descriptions.

    The resolver does not depend on field position.

    Known fields are identified first:

        - tire size
        - PR
        - load/speed
        - sidewall
        - construction markers
        - brand

    Pattern does NOT have a fixed grammar.

    Instead, after all strongly recognizable fields have been
    removed, the remaining meaningful product token is treated
    as the pattern.

    Example:

        175/70R14 84T VI-786 OVATION

        size        = 175/70R14
        load/speed  = 84T
        brand       = OVATION
        pattern     = VI-786

    Another example:

        185R14C 8PR 102/100R V-02 OVATION

        size        = 185R14C
        PR          = 8PR
        load/speed  = 102/100R
        brand       = OVATION
        pattern     = V-02

    Brand assumptions:

        - single word
        - alphabetic characters only
        - at least 4 characters
        - uppercase
    """

    # =============================================================
    # Construction markers
    # =============================================================

    CONSTRUCTION_MARKERS = {
        "TL",
        "T/L",
        "TT",
        "TUBELESS",
        "TUBE",
        "XL",
        "REINFORCED",
        "RF",
        "RUNFLAT",
        "RUN-FLAT",
    }

    # =============================================================
    # Tire prefixes
    # =============================================================

    PREFIXES = {
        "TH",
        "T",
        "TYRE",
        "TIRE",
    }

    # =============================================================
    # Structural words
    # =============================================================

    IGNORED_WORDS = {
        "PR",
        "P",
        "R",
        "ZR",
        "RADIAL",
        "BIAS",
        "PLY",
    }

    # =============================================================
    # Brand stop patterns
    # =============================================================

    BRAND_STOP_PATTERNS = [
        re.compile(
            r"^[A-Z]{1,6}&[A-Z]{1,12}$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^[A-Z]{2,12}/[A-Z]{2,12}$",
            re.IGNORECASE,
        ),
    ]

    # =============================================================
    # Bracket / parenthesis
    # =============================================================

    BRACKET_RE = re.compile(
        r"""
        (?P<open>[\[\(])
        (?P<value>[^\[\]\(\)]+)
        (?P<close>[\]\)])
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # =============================================================
    # Common tire prefix
    # =============================================================

    PREFIX_RE = re.compile(
        r"^(?:TH|T)(?=\d|\.)",
        re.IGNORECASE,
    )

    # =============================================================
    # Main resolver
    # =============================================================

    def resolve(
        self,
        text: str,
    ) -> TireProductFields:

        normalized = self._normalize(text)

        if not normalized:
            return TireProductFields()

        working = normalized

        result = TireProductFields()

        # ---------------------------------------------------------
        # 1. Tire size
        # ---------------------------------------------------------

        size_detection = detect_tire_size(
            working
        )

        if size_detection:

            result.size = size_detection.value

            result.size_match = FieldMatch(
                value=size_detection.value,
                confidence=1.0,
                start=size_detection.start,
                end=size_detection.end,
                reason="tire-size grammar",
            )

            working = self._mask_span(
                working,
                size_detection.start,
                size_detection.end,
            )

        # ---------------------------------------------------------
        # 2. Remove source/product prefix such as TH
        # ---------------------------------------------------------

        working = self.PREFIX_RE.sub(
            "",
            working,
            count=1,
        )

        # ---------------------------------------------------------
        # 3. PR
        # ---------------------------------------------------------

        pr_detection = self._detect_pr_with_context(
            working
        )

        if pr_detection:

            result.pr = pr_detection.value

            result.pr_match = FieldMatch(
                value=pr_detection.value,
                confidence=1.0,
                start=pr_detection.start,
                end=pr_detection.end,
                reason=pr_detection.reason,
            )

            working = self._mask_span(
                working,
                pr_detection.start,
                pr_detection.end,
            )

        # ---------------------------------------------------------
        # 4. Bracket / parenthesis groups
        # ---------------------------------------------------------

        bracket_candidates = (
            self._extract_bracket_candidates(
                working
            )
        )

        # ---------------------------------------------------------
        # 4a. Load/speed inside brackets
        # ---------------------------------------------------------

        for candidate in bracket_candidates:

            value = candidate["value"]

            load_speed = detect_load_speed(
                value
            )

            if (
                load_speed
                and result.load_speed_rating is None
            ):

                result.load_speed_rating = (
                    load_speed.value
                )

                result.load_speed_match = FieldMatch(
                    value=load_speed.value,
                    confidence=1.0,
                    start=candidate["start"],
                    end=candidate["end"],
                    reason=(
                        "load/speed inside "
                        "bracket group"
                    ),
                )

                working = self._mask_span(
                    working,
                    candidate["start"],
                    candidate["end"],
                )

        # ---------------------------------------------------------
        # 5. Load/speed outside brackets
        # ---------------------------------------------------------

        if result.load_speed_rating is None:

            load_speed_match = (
                self._find_load_speed(
                    working
                )
            )

            if load_speed_match:

                result.load_speed_rating = (
                    load_speed_match.value
                )

                result.load_speed_match = (
                    load_speed_match
                )

                working = self._mask_span(
                    working,
                    load_speed_match.start,
                    load_speed_match.end,
                )

        # ---------------------------------------------------------
        # 6. Sidewall
        # ---------------------------------------------------------

        sidewall_match = self._find_sidewall(
            working
        )

        if sidewall_match:

            result.sidewall = (
                sidewall_match.value
            )

            result.sidewall_match = (
                sidewall_match
            )

            working = self._mask_span(
                working,
                sidewall_match.start,
                sidewall_match.end,
            )

        # ---------------------------------------------------------
        # 7. Remove construction markers
        # ---------------------------------------------------------

        working = (
            self._remove_construction_markers(
                working
            )
        )

        # ---------------------------------------------------------
        # 8. Remove structural leftovers
        # ---------------------------------------------------------

        working = (
            self._remove_structural_tokens(
                working
            )
        )

        # ---------------------------------------------------------
        # 9. Resolve BRAND
        #
        # Brand has a stronger rule than pattern:
        #
        #   - exactly one word
        #   - alphabetic only
        #   - >= 4 characters
        #   - uppercase
        #
        # Examples:
        #
        #   OVATION
        #   ECOVISION
        #   GOODRIDE
        #
        # These are brands.
        #
        # Examples that are NOT brands:
        #
        #   VI
        #   V
        #   V-02
        #   VI-786
        #   CR960A
        # ---------------------------------------------------------

        brand_match = self._find_brand(
            working
        )

        if brand_match:

            result.brand = brand_match.value

            result.brand_match = brand_match

            working = self._mask_span(
                working,
                brand_match.start,
                brand_match.end,
            )

        # ---------------------------------------------------------
        # 10. Resolve PATTERN
        #
        # There is intentionally NO fixed pattern regex.
        #
        # Whatever meaningful product token remains after:
        #
        #   size
        #   PR
        #   load/speed
        #   sidewall
        #   construction
        #   brand
        #
        # is treated as the pattern.
        # ---------------------------------------------------------

        pattern_match = self._find_remaining_pattern(
            working
        )

        if pattern_match:

            result.pattern = (
                pattern_match.value
            )

            result.pattern_match = (
                pattern_match
            )

            # -----------------------------------------------------
            # 10a. Full bracketed pattern
            #
            # A bracket group is one field, so a multi-word pattern
            # is kept whole:
            #
            #   [SU318 H/T] -> SU318 H/T   (not SU318)
            # -----------------------------------------------------

            for candidate in bracket_candidates:

                value = candidate["value"]

                if (
                    pattern_match.value in value.split()
                    and not detect_load_speed(value)
                ):
                    result.pattern = value
                    break

        return result

    # =============================================================
    # Normalization
    # =============================================================

    @staticmethod
    def _normalize(
        text: str,
    ) -> str:

        value = str(text or "")

        value = value.replace(
            "\u00a0",
            " ",
        )

        value = value.replace(
            "–",
            "-",
        )

        value = value.replace(
            "—",
            "-",
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    # =============================================================
    # PR
    # =============================================================

    @staticmethod
    def _detect_pr_with_context(
        text: str,
    ):
        """
        Detect PR in forms such as:

            PR
            8PR
            14PR
            -8PR
            -14PR
            8 P.R.
            P.R. 8

        A bare PR is interpreted as 4PR according to the
        current tire data source convention.
        """

        explicit = re.search(
            r"""
            (?:
                (?P<number>\d{1,2})
                \s*[-]?\s*
                P\.?\s*R\.?
            )
            |
            (?:
                P\.?\s*R\.?
                \s*
                (?P<reverse>\d{1,2})
            )
            """,
            text,
            re.IGNORECASE | re.VERBOSE,
        )

        if explicit:

            number = (
                explicit.group("number")
                or explicit.group("reverse")
            )

            return _PRDetection(
                value=f"{number}PR",
                start=explicit.start(),
                end=explicit.end(),
                reason="explicit PR notation",
            )

        bare = re.search(
            r"(?<![A-Z0-9])P\.?\s*R\.?(?![A-Z0-9])",
            text,
            re.IGNORECASE,
        )

        if bare:

            return _PRDetection(
                value="4PR",
                start=bare.start(),
                end=bare.end(),
                reason=(
                    "bare PR marker, "
                    "default 4PR"
                ),
            )

        return None

    # =============================================================
    # Brackets
    # =============================================================

    @classmethod
    def _extract_bracket_candidates(
        cls,
        text: str,
    ):

        candidates = []

        for match in cls.BRACKET_RE.finditer(
            text
        ):

            candidates.append(
                {
                    "value": match.group(
                        "value"
                    ).strip(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )

        return candidates

    # =============================================================
    # Load / Speed
    # =============================================================

    
    
    @staticmethod
    def _find_load_speed(text: str) -> Optional[FieldMatch]:
        """
        Find load/speed ratings as complete whitespace-delimited tokens.

        Supports:
        - 84T
        - 91H
        - 103WXL
        - 106/104R
        - 114/XL_V
        - 110/XL_V
        - 106/XL_W
        - 115_V
        - 113_H
        - 109/107_T

        Brackets are token boundaries, so a rating glued to a
        pattern group is still found:

        - [G-127]84H      -> 84H
        - [SC328]102/100Q -> 102/100Q

        Load index and speed symbol written apart are joined when
        together they fit the load/speed formula:

        - 91 V            -> 91V
        - 106/104 R       -> 106/104R
        """
        # 98(Y): brackets are part of the speed symbol here.
        for token in re.finditer(r"(?<![\w/])\d{2,3}(?:/\d{2,3})?\(Y\)", text, re.IGNORECASE):
            detected = detect_load_speed(token.group(0))
            if detected:
                return FieldMatch(
                    value=detected.value,
                    confidence=0.98,
                    start=token.start(),
                    end=token.end(),
                    reason="tire load/speed grammar",
                )

        for token in re.finditer(r"[^\s\[\]\(\)]+", text):
            raw_value = token.group(0)
            value = raw_value.strip(" ,;:[]()")

            if not value:
                continue

            detected = detect_load_speed(value)
            if not detected:
                continue

            return FieldMatch(
                value=detected.value,
                confidence=0.98,
                start=token.start(),
                end=token.start() + len(value),
                reason="tire load/speed grammar",
            )

        tokens = list(re.finditer(r"\S+", text))

        for first, second in zip(tokens, tokens[1:]):

            joined = combine_load_speed(
                first.group(0).strip(",;:"),
                second.group(0).strip(",;:"),
            )

            if joined:
                return FieldMatch(
                    value=joined,
                    confidence=0.9,
                    start=first.start(),
                    end=second.end(),
                    reason="load index and speed symbol written apart",
                )

        return None

    # =============================================================
    # Sidewall
    # =============================================================

    @staticmethod
    def _find_sidewall(
        text: str,
    ) -> Optional[FieldMatch]:

        # Whole tokens only: "RW" in "RW-581" or "BS" in "BS-12"
        # is part of a pattern, not a sidewall marker.
        tokens = re.finditer(
            r"(?<![A-Z0-9\-/])[A-Z]{2,5}(?![A-Z0-9\-/])",
            text,
            re.IGNORECASE,
        )

        for token in tokens:

            value = token.group(0)

            detected = detect_sidewall(
                value
            )

            if detected:

                return FieldMatch(
                    value=detected.value,
                    confidence=1.0,
                    start=token.start(),
                    end=token.end(),
                    reason=(
                        "known tire sidewall "
                        "marker"
                    ),
                )

        return None

    # =============================================================
    # BRAND
    # =============================================================

    @classmethod
    def _find_brand(
        cls,
        text: str,
    ) -> Optional[FieldMatch]:

        for token in re.finditer(
            r"\S+",
            text,
        ):

            raw_value = token.group(0)

            value = raw_value.strip(
                " ,;:[]()"
            )

            if not value:
                continue

            # -----------------------------------------------------
            # Brand must be exactly one word.
            # -----------------------------------------------------

            if " " in value:
                continue

            # -----------------------------------------------------
            # Brand must contain alphabetic characters only.
            #
            # This is important:
            #
            #   OVATION  -> brand
            #   GOODRIDE -> brand
            #
            #   VI-786   -> NOT brand
            #   V-02     -> NOT brand
            #   CR960A   -> NOT brand
            # -----------------------------------------------------

            if not re.fullmatch(
                r"[A-Z]+",
                value,
                re.IGNORECASE,
            ):
                continue

            # -----------------------------------------------------
            # Minimum length.
            # -----------------------------------------------------

            if len(value) < 4:
                continue

            # -----------------------------------------------------
            # Brand must be uppercase.
            # -----------------------------------------------------

            if value != value.upper():
                continue

            upper = value.upper()

            # -----------------------------------------------------
            # Structural markers are never brands.
            # -----------------------------------------------------

            if upper in cls.CONSTRUCTION_MARKERS:
                continue

            if upper in cls.PREFIXES:
                continue

            if upper in cls.IGNORED_WORDS:
                continue

            # -----------------------------------------------------
            # Tire size is never brand.
            # -----------------------------------------------------

            if detect_tire_size(value):
                continue

            # -----------------------------------------------------
            # Load/speed is never brand.
            # -----------------------------------------------------

            if detect_load_speed(value):
                continue

            # -----------------------------------------------------
            # Sidewall is never brand.
            # -----------------------------------------------------

            if detect_sidewall(value):
                continue

            # -----------------------------------------------------
            # Explicit stop patterns.
            # -----------------------------------------------------

            if any(
                pattern.fullmatch(value)
                for pattern in cls.BRAND_STOP_PATTERNS
            ):
                continue

            return FieldMatch(
                value=value,
                confidence=cls._brand_confidence(
                    value
                ),
                start=token.start(),
                end=(
                    token.start()
                    + len(value)
                ),
                reason=(
                    "single uppercase "
                    "alphabetic brand word"
                ),
            )

        return None

    # =============================================================
    # Remaining Pattern
    # =============================================================

    @classmethod
    def _find_remaining_pattern(
        cls,
        text: str,
    ) -> Optional[FieldMatch]:

        """
        Pattern intentionally has no fixed grammar.

        After all known fields have been removed, look at the
        remaining product tokens.

        Reject obvious non-pattern leftovers:

            - empty values
            - numeric-only values
            - structural words
            - construction markers
            - tire sizes
            - load/speed values
            - sidewall markers

        The first remaining meaningful token is the pattern.

        Examples:

            VI-786
            VI-286HT
            V-02
            G-127
            SA07
            CR960A
            H188
            V-03

        All of these are valid because the parser does NOT
        depend on their shape.
        """

        candidates = []

        for token in re.finditer(
            r"\S+",
            text,
        ):

            raw_value = token.group(0)

            value = raw_value.strip(
                " ,;:[]()"
            )

            if not value:
                continue

            # -----------------------------------------------------
            # Punctuation-only leftovers are not pattern.
            #
            # Example: the "-" left from 185R14C-8PR after the
            # size and PR are removed.
            # -----------------------------------------------------

            if not re.search(r"[A-Za-z0-9]", value):
                continue

            upper = value.upper()

            # -----------------------------------------------------
            # Numeric-only is not pattern.
            # -----------------------------------------------------

            if re.fullmatch(
                r"[\d.,]+",
                value,
            ):
                continue

            # -----------------------------------------------------
            # Known structural words.
            # -----------------------------------------------------

            if upper in cls.IGNORED_WORDS:
                continue

            if upper in cls.CONSTRUCTION_MARKERS:
                continue

            if upper in cls.PREFIXES:
                continue

            # -----------------------------------------------------
            # Tire size.
            # -----------------------------------------------------

            if detect_tire_size(value):
                continue

            # -----------------------------------------------------
            # Load / speed.
            # -----------------------------------------------------

            if detect_load_speed(value):
                continue

            # -----------------------------------------------------
            # PR.
            # -----------------------------------------------------

            if detect_pr(value):
                continue

            # -----------------------------------------------------
            # Sidewall.
            # -----------------------------------------------------

            if detect_sidewall(value):
                continue

            # -----------------------------------------------------
            # Currency / numeric leftovers.
            # -----------------------------------------------------

            if re.fullmatch(
                r"""
                (?:
                    USD|US\$|\$|EUR|€|GBP|£|¥
                )?
                \s*
                [\d,]+(?:\.\d+)?
                """,
                value,
                re.IGNORECASE | re.VERBOSE,
            ):
                continue

            # -----------------------------------------------------
            # A meaningful product token remains.
            # -----------------------------------------------------

            candidates.append(
                FieldMatch(
                    value=value,
                    confidence=0.90,
                    start=token.start(),
                    end=(
                        token.start()
                        + len(value)
                    ),
                    reason=(
                        "remaining semantic "
                        "product token"
                    ),
                )
            )

        if not candidates:
            return None

        # ---------------------------------------------------------
        # Usually there should be exactly one pattern token.
        #
        # If OCR leaves multiple tokens, use the first meaningful
        # product token rather than inventing a pattern grammar.
        # ---------------------------------------------------------

        return candidates[0]

    # =============================================================
    # Construction
    # =============================================================

    @classmethod
    def _remove_construction_markers(
        cls,
        text: str,
    ) -> str:

        result = text

        for marker in sorted(
            cls.CONSTRUCTION_MARKERS,
            key=len,
            reverse=True,
        ):

            result = re.sub(
                rf"(?<![A-Z0-9])"
                rf"{re.escape(marker)}"
                rf"(?![A-Z0-9])",
                " ",
                result,
                flags=re.IGNORECASE,
            )

        return result

    # =============================================================
    # Structural leftovers
    # =============================================================

    @classmethod
    def _remove_structural_tokens(cls, text: str) -> str:
        result = text

        result = (
            result
            .replace("|", " ")
            .replace("[", " ")
            .replace("]", " ")
            .replace("(", " ")
            .replace(")", " ")
        )

        result = cls.PREFIX_RE.sub(" ", result, count=1)

        for token in cls.IGNORED_WORDS:
            result = re.sub(
                rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])",
                " ",
                result,
                flags=re.IGNORECASE,
            )

        # Remove only complete numeric tokens.
        #
        # IMPORTANT:
        # Do NOT remove digits embedded inside product codes.
        #
        # LS588  -> keep
        # LSV88  -> keep
        # LS388  -> keep
        # CR960A -> keep
        #
        # But:
        # 200    -> remove
        # 61.15  -> remove
        # 12230.00 -> remove
        tokens = result.split()

        tokens = [
            token
            for token in tokens
            if not re.fullmatch(r"[\d.,]+", token)
        ]

        return " ".join(tokens)

    # =============================================================
    # Brand confidence
    # =============================================================

    @staticmethod
    def _brand_confidence(
        brand: str,
    ) -> float:

        if not brand:
            return 0.0

        if (
            brand.isalpha()
            and brand.isupper()
            and len(brand) >= 4
        ):
            return 0.95

        return 0.75

    # =============================================================
    # Masking helpers
    # =============================================================

    @staticmethod
    def _mask_span(
        text: str,
        start: int,
        end: int,
    ) -> str:

        if start < 0 or end <= start:
            return text

        chars = list(text)

        for index in range(
            max(0, start),
            min(len(chars), end),
        ):
            chars[index] = " "

        return "".join(chars)

    @staticmethod
    def _is_masked(
        text: str,
        start: int,
        end: int,
    ) -> bool:

        if start < 0 or end <= start:
            return True

        fragment = text[start:end]

        return not fragment.strip()


@dataclass
class _PRDetection:
    value: str
    start: int
    end: int
    reason: str
