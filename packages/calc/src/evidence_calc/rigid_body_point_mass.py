from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import as_decimal, format_quantum, quantize, reject_ambiguous


def run_rigid_body_point_mass(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    required = list(card["inputs"])
    _require(inputs, required)
    quantum = Decimal(card["quantum"])
    limits = card["inputs"]
    mass = _bounded(inputs["mass_kg"], limits["mass_kg"])
    gravity = _bounded(inputs["gravity_m_s2"], limits["gravity_m_s2"])
    load_factor = _bounded(inputs["load_factor"], limits["load_factor"])
    cg_x = _bounded(inputs["cg_x_m"], limits["cg_x_m"])
    unit_x = _unit_positions(inputs["unit_x_m"], limits["unit_x_m"])
    operative = _operative(inputs["unit_operative"])
    required_force = quantize(mass * gravity * load_factor, quantum)
    weight = quantize(mass * gravity, quantum)
    forces = _share(required_force, operative, quantum)
    residual = required_force - sum(forces, Decimal("0"))
    if residual.copy_abs() > quantum:
        raise AbstainError("balance_failed")
    moment = Decimal("0")
    for force, position in zip(forces, unit_x, strict=True):
        moment += force * (position - cg_x)
    outputs = {
        "weight_n": format_quantum(weight, quantum),
        "required_vertical_force_n": format_quantum(required_force, quantum),
        "unit_force_n": [format_quantum(force, quantum) for force in forces],
        "vertical_residual_n": format_quantum(residual, quantum),
        "moment_about_cg_n_m": format_quantum(moment, quantum),
    }
    return _wrapped(card, outputs)


def _require(inputs: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if not isinstance(inputs, dict) or key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")


def _bounded(text: str, limit: dict[str, str]) -> Decimal:
    reject_ambiguous(text)
    if not isinstance(text, str):
        raise AbstainError("outside_validity")
    value = as_decimal(text)
    low = Decimal(limit["min"])
    high = Decimal(limit["max"])
    if value < low or value > high:
        raise AbstainError("outside_validity")
    return value


def _unit_positions(values: Any, limit: dict[str, str]) -> list[Decimal]:
    if not isinstance(values, list) or len(values) != int(limit["count"]):
        raise AbstainError("outside_validity")
    parsed: list[Decimal] = []
    for item in values:
        parsed.append(_bounded(item, limit))
    return parsed


def _operative(values: Any) -> list[bool]:
    if not isinstance(values, list) or len(values) != 4:
        raise AbstainError("outside_validity")
    flags: list[bool] = []
    for item in values:
        if not isinstance(item, bool):
            raise AbstainError("outside_validity")
        flags.append(item)
    active = sum(1 for flag in flags if flag)
    if active == 0 or active < 3:
        raise AbstainError("outside_validity")
    return flags


def _share(total: Decimal, operative: list[bool], quantum: Decimal) -> list[Decimal]:
    active = sum(1 for flag in operative if flag)
    share = quantize(total / Decimal(active), quantum)
    assigned = Decimal("0")
    remaining = active
    forces: list[Decimal] = []
    for flag in operative:
        if not flag:
            forces.append(quantize(Decimal("0"), quantum))
            continue
        remaining -= 1
        if remaining == 0:
            forces.append(quantize(total - assigned, quantum))
        else:
            forces.append(share)
            assigned += share
    return forces


def _wrapped(card: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "method_id": card["method_id"],
        "method_version": card["method_version"],
        "outputs": outputs,
        "sources": card["sources"],
        "card_title": card["title"],
        "label": card["label"],
    }
