from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence_calc.allowables import lookup_allowable
from evidence_calc.bolt_screen import run_bolt_screen
from evidence_calc.errors import AbstainError
from evidence_calc.hover_power_screen import run_hover_power_screen
from evidence_calc.intervals import evaluate_method_intervals
from evidence_calc.plugins import (
    list_plugin_cards,
    load_plugin_card,
    register_plugin_card,
    run_declarative_card,
)
from evidence_calc.quotation_costing import (
    run_aerospace_multiyear_cashflow_learning,
    run_aerospace_quotation_costing,
    run_engineering_workpackage_quote,
    run_rotorcraft_archetype_quote,
    run_rotorcraft_historical_calibration,
)
from evidence_calc.rigid_body_point_mass import run_rigid_body_point_mass
from evidence_calc.rotorcraft_airframe_stress import ROTORCRAFT_AIRFRAME_CARD_RUNNERS
from evidence_calc.rotorcraft_stress import ROTORCRAFT_STRESS_CARD_RUNNERS
from evidence_calc.rotorcraft_stress_ext import ROTORCRAFT_STRESS_EXT_CARD_RUNNERS
from evidence_calc.rotorcraft_systems_stress import ROTORCRAFT_SYSTEMS_CARD_RUNNERS
from evidence_calc.stress_manual import STRESS_MANUAL_CARD_RUNNERS
from evidence_calc.stress_manual_ext import STRESS_MANUAL_EXT_CARD_RUNNERS
from evidence_calc.structural_sizing import (
    run_column_plate_buckling,
    run_composite_failure_criteria,
    run_margin_of_safety,
    run_palmgren_miner_fatigue,
)
from evidence_calc.units import check_declared_units, convert_inputs_to_card_units

_RUNNERS = {
    "rigid_body_point_mass": run_rigid_body_point_mass,
    "bolt_screen": run_bolt_screen,
    "hover_power_screen": run_hover_power_screen,
    "margin_of_safety": run_margin_of_safety,
    "column_plate_buckling": run_column_plate_buckling,
    "palmgren_miner_fatigue": run_palmgren_miner_fatigue,
    "composite_failure_criteria": run_composite_failure_criteria,
    "aerospace_quotation_costing": run_aerospace_quotation_costing,
    "aerospace_multiyear_cashflow_learning": run_aerospace_multiyear_cashflow_learning,
    "engineering_workpackage_quote": run_engineering_workpackage_quote,
    "rotorcraft_archetype_quote": run_rotorcraft_archetype_quote,
    "rotorcraft_historical_calibration": run_rotorcraft_historical_calibration,
    **STRESS_MANUAL_CARD_RUNNERS,
    **ROTORCRAFT_STRESS_CARD_RUNNERS,
    **ROTORCRAFT_STRESS_EXT_CARD_RUNNERS,
    **ROTORCRAFT_SYSTEMS_CARD_RUNNERS,
    **ROTORCRAFT_AIRFRAME_CARD_RUNNERS,
    **STRESS_MANUAL_EXT_CARD_RUNNERS,
}
_CARDS: dict[str, dict[str, Any]] = {}

# Canonical grouping metadata mapping overlapping specialized cards to primary entry points.
CARD_CONSOLIDATION_MAP: dict[str, str] = {
    "tsai_wu_ply_failure": "composite_failure_criteria",
    "hashin_composite_modes": "composite_failure_criteria",
    "rainflow_spectrum_damage": "palmgren_miner_fatigue",
    "walker_mean_stress_crack_growth": "nasgro_paris_crack_growth",
    "johnson_euler_column": "column_plate_buckling",
    "needham_crippling_section": "column_plate_buckling",
    "aerospace_quotation_costing": "rotorcraft_archetype_quote",
    "engineering_workpackage_quote": "rotorcraft_archetype_quote",
}


def cards_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "cards"


def list_method_ids(*, include_plugins: bool = True) -> list[str]:
    """Return sorted built-in and declarative plugin method IDs."""
    ids = [p.stem for p in sorted(cards_dir().glob("*.json"))]
    if include_plugins:
        for plugin in list_plugin_cards():
            mid = str(plugin["method_id"])
            if mid not in ids:
                ids.append(mid)
    return sorted(ids)


def list_cards(*, include_plugins: bool = True) -> list[dict[str, Any]]:
    """Return all built-in and declarative plugin calculation cards with canonical aliases."""
    cards: list[dict[str, Any]] = []
    for method_id in list_method_ids(include_plugins=include_plugins):
        card = dict(load_card(method_id))
        if method_id in CARD_CONSOLIDATION_MAP:
            card["canonical_card_id"] = CARD_CONSOLIDATION_MAP[method_id]
        else:
            card.setdefault("canonical_card_id", method_id)
        cards.append(card)
    return cards


def load_card(method_id: str) -> dict[str, Any]:
    path = cards_dir() / f"{method_id}.json"
    if path.is_file():
        cached = _CARDS.get(method_id)
        if cached is not None:
            return cached
        card = json.loads(path.read_text(encoding="utf-8"))
        if card.get("method_id") != method_id:
            raise AbstainError("unknown_method")
        _CARDS[method_id] = card
        return card
    plugin_card = load_plugin_card(method_id)
    if plugin_card is not None:
        return plugin_card
    raise AbstainError("unknown_method")


def register_custom_card(
    card: dict[str, Any], *, plugins_dir: Path | None = None
) -> dict[str, Any]:
    """Validate and register a user declarative plugin card."""
    return register_plugin_card(card, plugins_dir=plugins_dir)


def run_method(
    method_id: str,
    inputs: dict[str, Any],
    *,
    normalize_units: bool = False,
    include_intervals: bool = False,
) -> dict[str, Any]:
    card = load_card(method_id)
    runner = _RUNNERS.get(method_id)
    if runner is None:
        if not (card.get("plugin") and card.get("formulas")):
            raise AbstainError("unknown_method")
        runner = run_declarative_card
    raw_inputs = dict(inputs)
    lookup_spec = raw_inputs.pop("material_lookup", None)
    allowable_provenance: dict[str, dict[str, Any]] = {}
    propagated_intervals: dict[str, tuple[str, str]] = {}
    if isinstance(lookup_spec, dict):
        # Support either {field_name: {material_id, ...}} or flat {target_field, material_id, ...}
        if "material_id" in lookup_spec:
            target = str(lookup_spec.get("target_field") or "allowable_mpa")
            specs: dict[str, dict[str, Any]] = {target: lookup_spec}
        else:
            specs = {str(k): v for k, v in lookup_spec.items() if isinstance(v, dict)}
        in_units = (
            dict(raw_inputs.get("_input_units") or {})
            if isinstance(raw_inputs.get("_input_units"), dict)
            else {}
        )
        for field_name, spec in specs.items():
            mat_res = lookup_allowable(
                str(spec["material_id"]),
                basis=str(spec.get("basis", "A")),
                property_name=str(spec.get("property_name", "fty_mpa")),
                thickness_mm=str(spec.get("thickness_mm", "10")),
                temp_c=str(spec.get("temp_c", "23")),
                environment=str(spec.get("environment", "RTD")),
                include_intervals=bool(spec.get("include_intervals", include_intervals)),
                temp_uncertainty_c=str(spec.get("temp_uncertainty_c", "0")),
                thickness_uncertainty_mm=str(spec.get("thickness_uncertainty_mm", "0")),
            )
            raw_inputs[field_name] = str(mat_res["allowable_value_mpa"])
            mat_iv = (mat_res.get("exact_intervals") or {}).get("allowable_value_mpa")
            if isinstance(mat_iv, dict) and "lower" in mat_iv and "upper" in mat_iv:
                propagated_intervals[field_name] = (str(mat_iv["lower"]), str(mat_iv["upper"]))
            if "_input_units" in raw_inputs:
                in_units.setdefault(field_name, "megapascal")
            allowable_provenance[field_name] = mat_res
        if "_input_units" in raw_inputs:
            raw_inputs["_input_units"] = in_units
    check_declared_units(raw_inputs, card)
    conversions: list[dict[str, str]] = []
    effective_inputs = raw_inputs
    if normalize_units:
        effective_inputs, conversions = convert_inputs_to_card_units(raw_inputs, card)
    numeric_inputs = {
        key: value for key, value in effective_inputs.items() if key != "_input_units"
    }
    outcome = runner(numeric_inputs, card)
    if allowable_provenance:
        outcome = {**outcome, "allowable_provenance": allowable_provenance}
    if include_intervals:
        intervals = evaluate_method_intervals(
            method_id,
            numeric_inputs,
            outcome["outputs"],
            card=card,
            input_intervals=propagated_intervals or None,
        )
        outcome = {**outcome, "exact_intervals": intervals}
    if normalize_units:
        outcome = {
            **outcome,
            "normalized_inputs": numeric_inputs,
            "unit_conversions": conversions,
        }
    return outcome
