from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import as_decimal, format_quantum, quantize, reject_ambiguous


def run_bolt_screen(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    required = list(card["required"])
    for key in required:
        if not isinstance(inputs, dict) or key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")
    quantum = Decimal(card["quantum"])
    limits = card["limits"]
    area = _limited(inputs["area_mm2"], limits["area_mm2"], allow_zero_special=True)
    if area == 0:
        raise AbstainError("area_zero")
    shear = _limited(inputs["shear_force_n"], limits["shear_force_n"])
    tensile = _limited(inputs["tensile_force_n"], limits["tensile_force_n"])
    shear_allow = _limited(inputs["shear_allowable_mpa"], limits["shear_allowable_mpa"])
    tensile_allow = _limited(inputs["tensile_allowable_mpa"], limits["tensile_allowable_mpa"])
    if shear_allow <= 0 or tensile_allow <= 0:
        raise AbstainError("outside_validity")
    shear_stress = quantize(shear / area, quantum)
    tensile_stress = quantize(tensile / area, quantum)
    shear_ratio = quantize(shear_stress / shear_allow, quantum)
    tensile_ratio = quantize(tensile_stress / tensile_allow, quantum)
    interaction = quantize(
        (shear_ratio * shear_ratio + tensile_ratio * tensile_ratio).sqrt(), quantum
    )
    outputs = {
        "shear_stress_mpa": format_quantum(shear_stress, quantum),
        "tensile_stress_mpa": format_quantum(tensile_stress, quantum),
        "shear_ratio": format_quantum(shear_ratio, quantum),
        "tensile_ratio": format_quantum(tensile_ratio, quantum),
        "interaction_ratio": format_quantum(interaction, quantum),
    }
    return {
        "method_id": card["method_id"],
        "method_version": card["method_version"],
        "outputs": outputs,
        "sources": card["sources"],
        "card_title": card["title"],
        "label": card["label"],
    }


def _limited(text: str, limit: dict[str, str], allow_zero_special: bool = False) -> Decimal:
    reject_ambiguous(text)
    if not isinstance(text, str):
        raise AbstainError("outside_validity")
    value = as_decimal(text)
    if allow_zero_special and value == 0:
        return value
    if "min" in limit and value < Decimal(limit["min"]):
        raise AbstainError("outside_validity")
    if "min_exclusive" in limit and value <= Decimal(limit["min_exclusive"]):
        raise AbstainError("outside_validity")
    if "max" in limit and value > Decimal(limit["max"]):
        raise AbstainError("outside_validity")
    return value
