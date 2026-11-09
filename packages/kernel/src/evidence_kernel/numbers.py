from __future__ import annotations

import re
from typing import Any

DECIMAL_TOKEN = re.compile(r"-?\d+\.\d+")
INTEGER_TOKEN = re.compile(r"(?<![\d.])-?\d+(?![\d.])")
HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
_INDEX_KEYS = frozenset({"span_start", "span_end"})
_UNIT_KEYS = frozenset({"unit", "unit_text"})


def collect_decimals(value: Any) -> set[str]:
    found: set[str] = set()
    _walk(value, found)
    return found


def _walk(value: Any, found: set[str]) -> None:
    if isinstance(value, str):
        if DECIMAL_TOKEN.fullmatch(value):
            found.add(value)
        else:
            found.update(DECIMAL_TOKEN.findall(value))
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


def _stray_text(value: str, allowed: set[str], stray: list[str], key: str | None) -> None:
    if DECIMAL_TOKEN.fullmatch(value):
        if value not in allowed:
            stray.append(value)
        return
    if INTEGER_TOKEN.fullmatch(value):
        if key not in _INDEX_KEYS and key not in _UNIT_KEYS and value not in allowed:
            stray.append(value)
        return
    for match in DECIMAL_TOKEN.finditer(value):
        token = match.group()
        if _glued(value, match.start()):
            continue
        if token not in allowed:
            stray.append(token)
    if key in _INDEX_KEYS or key in _UNIT_KEYS:
        return
    for match in INTEGER_TOKEN.finditer(value):
        token = match.group()
        if _glued(value, match.start()) or _unit_exponent(value, match.start()):
            continue
        if token not in allowed:
            stray.append(token)


def _glued(value: str, start: int) -> bool:
    """True when the token is the tail of an identifier, not a measurement."""
    if start <= 0:
        return False
    previous = value[start - 1]
    return previous.isalpha() or previous in "-."


def _unit_exponent(value: str, start: int) -> bool:
    prefix = value[max(0, start - 3) : start]
    return prefix.endswith("** ") or prefix.endswith("**") or prefix.endswith("^")
