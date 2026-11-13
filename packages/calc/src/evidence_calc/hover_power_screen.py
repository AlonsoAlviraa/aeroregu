from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum, parse_limited_decimal, quantize


def run_hover_power_screen(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Compute actuator-disk hover screening outputs using deterministic Decimal math."""
    required = list(card["required"])
    for key in required:
        if not isinstance(inputs, dict) or key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")

    quantum = Decimal(card["quantum"])
    limits = card["limits"]

    disk_area = parse_limited_decimal(
        inputs["disk_area_m2"], limits["disk_area_m2"], allow_zero_special=True
    )
    if disk_area == 0:
        raise AbstainError("area_zero")

    thrust = parse_limited_decimal(inputs["thrust_n"], limits["thrust_n"])
    density = parse_limited_decimal(inputs["air_density_kg_m3"], limits["air_density_kg_m3"])
    figure_of_merit = parse_limited_decimal(inputs["figure_of_merit"], limits["figure_of_merit"])
    power_available = parse_limited_decimal(
        inputs["power_available_kw"], limits["power_available_kw"]
    )

    disk_loading = quantize(thrust / disk_area, quantum)
    induced_velocity = quantize((thrust / (Decimal("2") * density * disk_area)).sqrt(), quantum)
    ideal_power = quantize((thrust * induced_velocity) / Decimal("1000"), quantum)
    shaft_power = quantize(ideal_power / figure_of_merit, quantum)
    power_margin = quantize((power_available - shaft_power) / power_available, quantum)

    outputs = {
        "disk_loading_pa": format_quantum(disk_loading, quantum),
        "induced_velocity_m_s": format_quantum(induced_velocity, quantum),
        "ideal_power_kw": format_quantum(ideal_power, quantum),
        "shaft_power_kw": format_quantum(shaft_power, quantum),
        "power_margin_ratio": format_quantum(power_margin, quantum),
    }
    return {
        "method_id": card["method_id"],
        "method_version": card["method_version"],
        "outputs": outputs,
        "sources": card["sources"],
        "card_title": card["title"],
        "label": card["label"],
    }
