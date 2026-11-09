"""Compare pint's interval factor with NIST SP 811 Appendix B.8.

The fetch is the public NIST page, saved under data/external and not committed.
Boldface marking of exact factors was not preserved, so a row agrees when pint
is within half of the last printed digit. Offset units such as degree Celsius
are not scored: pint refuses to subtract them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from evidence_calc.units import conversion_interval

from evidence_eval.external_public import file_sha256

NIST_B8_SHA256 = "3276ec9d294c99d084b338c3440a606c6d4cbeac9239bf5e98ad0605b7668e0c"
_ROW = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([0-9. ]+) \| E([+-][0-9]+) \|", re.M)
_TRAIL = re.compile(r"(?:\(([^)]+)\)|\[([^\]]+)\])\s*$")


def _symbol(cell: str) -> str | None:
    match = _TRAIL.search(cell.strip())
    if match is None:
        return None
    raw = (match.group(1) or match.group(2)).replace("·", "*").replace("⋅", "*")
    raw = raw.replace(" ", "")
    return raw or None


def _published(mantissa: str, exponent: str) -> tuple[Decimal, Decimal]:
    digits = mantissa.replace(" ", "")
    places = len(digits.split(".")[1]) if "." in digits else 0
    power = Decimal(10) ** int(exponent)
    value = Decimal(digits) * power
    tolerance = (Decimal(5) * Decimal(10) ** (-(places + 1))) * power
    return value, tolerance


def score_nist_b8(path: Path, *, check_pin: bool = True) -> dict[str, Any]:
    if check_pin and file_sha256(path) != NIST_B8_SHA256:
        raise ValueError("NIST B.8 file hash does not match the pin")
    text = path.read_text(encoding="utf-8")
    groups: dict[tuple[str, str], list[tuple[Decimal, Decimal]]] = defaultdict(list)
    no_symbol = 0
    for left, right, mantissa, exponent in _ROW.findall(text):
        pair = (_symbol(left), _symbol(right))
        if pair[0] is None or pair[1] is None:
            no_symbol += 1
            continue
        groups[pair].append(_published(mantissa, exponent))
    agree = other = disagree = incompatible = unknown = 0
    disagree_pairs: list[str] = []
    disagree_detail: list[dict[str, object]] = []
    for (left, right), rows in groups.items():
        got = conversion_interval(left, right)
        if got is None:
            unknown += len(rows)
            continue
        if got == "incompatible":
            incompatible += len(rows)
            continue
        hits = [abs(got - published) <= tolerance for published, tolerance in rows]
        if any(hits):
            agree += sum(1 for hit in hits if hit)
            other += sum(1 for hit in hits if not hit)
            continue
        disagree += len(rows)
        pair_name = f"{left}>{right}"
        disagree_pairs.append(pair_name)
        disagree_detail.append(
            {
                "pair": pair_name,
                "pint": str(got),
                "published": [str(published) for published, _tolerance in rows],
            }
        )
    return {
        "source": "https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8",
        "retrieved": "2026-11-09",
        "rows": len(_ROW.findall(text)),
        "no_trailing_symbol": no_symbol,
        "agree": agree,
        "other_definition": other,
        "disagree": disagree,
        "incompatible": incompatible,
        "symbol_unknown": unknown,
        "disagree_pairs": sorted(set(disagree_pairs)),
        "disagree_detail": sorted(disagree_detail, key=lambda item: str(item["pair"])),
        "sha256": NIST_B8_SHA256,
        "label": "ESTIMATE",
        "note": (
            "US government table. Exact-factor boldface was not in the text fetch, "
            "so agreement is half the last printed digit. other_definition means pint "
            "matches a different row that uses the same two symbols."
        ),
    }
