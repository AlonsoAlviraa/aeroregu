from __future__ import annotations

import re
from typing import Any

SCIENTIFIC_TOKEN = re.compile(r"(?<![A-Za-z0-9_.])[-−]?\d+(?:[.,]\d+)?[eE][+-]?\d+(?![A-Za-z0-9_])")
DECIMAL_TOKEN = re.compile(r"(?:[-−]?\d+\.\d+)|(?<![\d.,])[-−]?\d+,\d+(?![\d.,])")
FRACTION_TOKEN = re.compile(r"(?<![A-Za-z0-9_./:-])[-−]?\d+/\d+(?![A-Za-z0-9_./:-])")
INTEGER_TOKEN = re.compile(r"(?<![\d.,])[-−]?\d+(?![\d.,])")
UNICODE_MINUS_TOKEN = re.compile(r"−\d+(?:\.\d+)?")
HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
_INDEX_KEYS = frozenset({"span_start", "span_end"})
_UNIT_KEYS = frozenset({"unit", "unit_text"})
_GATE_PROBABILITY = re.compile(r"^(?:0\.\d{3}|1\.000)$")
_ISO_OR_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLAUSE_REF_RE = re.compile(r"\b(?:FAR|CS|AMC)\s+\d{2,3}\.\d{1,4}(?:\([a-z0-9]+\))*")


def collect_decimals(value: Any) -> set[str]:
    found: set[str] = set()
    _walk(value, found)
    return found


def _walk(value: Any, found: set[str]) -> None:
    if isinstance(value, str):
        if DECIMAL_TOKEN.fullmatch(value):
            found.add(value.replace("−", "-"))
        else:
            found.update(tok.replace("−", "-") for tok in DECIMAL_TOKEN.findall(value))
        return
    if isinstance(value, list):
        for item in value:
            _walk(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, found)


def stray_physical_numbers(value: Any, allowed: set[str]) -> list[str]:
    """Return physical numbers in an agent JSON value that are not exact calc copies."""

    stray: list[str] = []
    _stray(value, allowed, stray, None)
    return stray


def only_new_physical_tokens_are_integers(candidate: Any, baseline: Any) -> bool:
    """True when every new physical token is an integer the baseline did not emit.

    A new decimal is a different claim. An empty delta is not this case.
    """

    allowed = set(stray_physical_numbers(baseline, set()))
    novel = stray_physical_numbers(candidate, allowed)
    if not novel:
        return False
    return all(INTEGER_TOKEN.fullmatch(token) for token in novel)


def _stray(value: Any, allowed: set[str], stray: list[str], key: str | None) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, float) or isinstance(value, int):
        stray.append(str(value))
        return
    if isinstance(value, str):
        if HEX_HASH.fullmatch(value):
            return
        _stray_text(value, allowed, stray, key)
        return
    if isinstance(value, list):
        for item in value:
            _stray(item, allowed, stray, None)
    elif isinstance(value, dict):
        for item_key, item in value.items():
            next_key = item_key if isinstance(item_key, str) else None
            _stray(item, allowed, stray, next_key)


def _canonical_num_token(token: str) -> str:
    return token.replace("−", "-").replace(",", ".")


def _collect_matches(
    value: str,
    pattern: re.Pattern[str],
    allowed: set[str],
    stray: list[str],
    consumed: list[tuple[int, int]],
    *,
    skip_exponent: bool = False,
) -> None:
    for match in pattern.finditer(value):
        s_idx, e_idx = match.span()
        if any(not (e_idx <= cs or s_idx >= ce) for cs, ce in consumed):
            continue
        if _glued(value, s_idx):
            continue
        if skip_exponent and _unit_exponent(value, s_idx):
            continue
        raw_tok = match.group()
        norm_tok = _canonical_num_token(raw_tok)
        if raw_tok not in allowed and norm_tok not in allowed:
            stray.append(raw_tok)
        consumed.append((s_idx, e_idx))


def _stray_text(value: str, allowed: set[str], stray: list[str], key: str | None) -> None:
    if key == "gate_probability" and _GATE_PROBABILITY.fullmatch(value):
        return
    if SCIENTIFIC_TOKEN.fullmatch(value):
        if value not in allowed and _canonical_num_token(value) not in allowed:
            stray.append(value)
        return
    if DECIMAL_TOKEN.fullmatch(value):
        if value not in allowed and _canonical_num_token(value) not in allowed:
            stray.append(value)
        return
    if FRACTION_TOKEN.fullmatch(value):
        if value not in allowed and _canonical_num_token(value) not in allowed:
            stray.append(value)
        return
    if INTEGER_TOKEN.fullmatch(value):
        if key not in _INDEX_KEYS and key not in _UNIT_KEYS:
            norm = _canonical_num_token(value)
            if value not in allowed and norm not in allowed:
                stray.append(value)
        return

    consumed: list[tuple[int, int]] = [m.span() for m in _CLAUSE_REF_RE.finditer(value)]
    _collect_matches(value, SCIENTIFIC_TOKEN, allowed, stray, consumed)
    _collect_matches(value, DECIMAL_TOKEN, allowed, stray, consumed)
    _collect_matches(value, FRACTION_TOKEN, allowed, stray, consumed)
    if key in _INDEX_KEYS or key in _UNIT_KEYS:
        return
    _collect_matches(value, INTEGER_TOKEN, allowed, stray, consumed, skip_exponent=True)


def _glued(value: str, start: int) -> bool:
    """True when the token is the tail of an identifier, not a measurement."""
    if start <= 0:
        return False
    previous = value[start - 1]
    return previous.isalpha() or previous in "-."


def _unit_exponent(value: str, start: int) -> bool:
    prefix = value[max(0, start - 3) : start]
    return prefix.endswith("** ") or prefix.endswith("**") or prefix.endswith("^")
