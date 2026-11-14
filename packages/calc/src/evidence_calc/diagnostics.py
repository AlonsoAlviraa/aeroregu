from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum
from evidence_calc.registry import load_card, run_method

_DECIMAL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_UNIT_SCALE_FACTORS = (
    Decimal("1000"),
    Decimal("0.001"),
    Decimal("100"),
    Decimal("0.01"),
    Decimal("10"),
    Decimal("0.1"),
    Decimal("1000000"),
    Decimal("0.000001"),
    Decimal("60"),
)


def classify_numeric_delta(
    method_id: str,
    inputs: dict[str, Any],
    stated: Any,
    recomputed: dict[str, Any],
) -> str:
    """Attribute a numeric discrepancy to its physical or arithmetic root cause."""
    if stated == recomputed:
        return "clean"
    try:
        card = load_card(method_id)
        quantum = Decimal(str(card.get("quantum", "0.001")))
    except AbstainError:
        quantum = Decimal("0.001")
    for factor in _UNIT_SCALE_FACTORS:
        if _matches_scaled_input(method_id, inputs, stated, factor, quantum):
            return "unit_scale"
    if _matches_sign(method_id, inputs, stated, quantum):
        return "sign"
    if _matches_replaced_field(method_id, inputs, stated):
        return "wrong_input"
    if stated == _scale_decimals(recomputed, Decimal("2"), quantum):
        return "arithmetic"
    return "unexplained"


def _matches_scaled_input(
    method_id: str,
    inputs: dict[str, Any],
    stated: Any,
    factor: Decimal,
    quantum: Decimal,
) -> bool:
    for field, value in _scalar_decimals(inputs):
        trial = dict(inputs)
        trial[field] = format_quantum(Decimal(value) * factor, quantum)
        if _same_outputs(method_id, trial, stated):
            return True
    return False


def _matches_sign(
    method_id: str,
    inputs: dict[str, Any],
    stated: Any,
    quantum: Decimal,
) -> bool:
    for field, value in _scalar_decimals(inputs):
        trial = dict(inputs)
        trial[field] = format_quantum(-Decimal(value), quantum)
        if _same_outputs(method_id, trial, stated):
            return True
    return False


def _matches_replaced_field(
    method_id: str,
    inputs: dict[str, Any],
    stated: Any,
) -> bool:
    scalars = _scalar_decimals(inputs)
    for field, _value in scalars:
        for other, other_value in scalars:
            if field == other or other_value == inputs[field]:
                continue
            trial = dict(inputs)
            trial[field] = other_value
            if _same_outputs(method_id, trial, stated):
                return True
    return False


def _same_outputs(method_id: str, inputs: dict[str, Any], stated: Any) -> bool:
    try:
        return run_method(method_id, inputs)["outputs"] == stated
    except AbstainError:
        return False


def _scalar_decimals(inputs: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for key, value in inputs.items():
        if isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
            found.append((key, value))
    return found


def _scale_decimals(value: Any, factor: Decimal, quantum: Decimal) -> Any:
    if isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
        return format_quantum(Decimal(value) * factor, quantum)
    if isinstance(value, list):
        return [_scale_decimals(item, factor, quantum) for item in value]
    if isinstance(value, dict):
        return {key: _scale_decimals(item, factor, quantum) for key, item in value.items()}
    return value
