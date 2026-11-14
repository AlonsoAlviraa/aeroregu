"""Deterministic Knowledgeware/CAD/FEM parameter bindings to verified calc cards."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import cards_dir, load_card, run_method
from evidence_calc.units import conversion_interval, units_compatible

_UNIT_TOKEN_ALIASES = {
    "n": "newton",
    "kn": "kilonewton",
    "dan": "decanewton",
    "lbf": "pound_force",
    "m": "meter",
    "mm": "millimeter",
    "cm": "centimeter",
    "in": "inch",
    "ft": "foot",
    "m2": "meter ** 2",
    "m^2": "meter ** 2",
    "mm2": "millimeter ** 2",
    "mm^2": "millimeter ** 2",
    "cm2": "centimeter ** 2",
    "in2": "inch ** 2",
    "ft2": "foot ** 2",
    "kg": "kilogram",
    "g": "gram",
    "lb": "pound",
    "lbm": "pound",
    "pa": "pascal",
    "kpa": "kilopascal",
    "mpa": "megapascal",
    "gpa": "gigapascal",
    "psi": "pound_force_per_square_inch",
    "kw": "kilowatt",
    "w": "watt",
    "hp": "horsepower",
    "kg/m3": "kilogram / meter ** 3",
    "kg/m^3": "kilogram / meter ** 3",
    "m/s2": "meter / second ** 2",
    "m/s^2": "meter / second ** 2",
    "1": "dimensionless",
    "-": "dimensionless",
    "nz": "dimensionless",
}

_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "hover_power_screen": {
        "thrust_n": (
            "thrust_n",
            "thrust_kn",
            "thrust",
            "rotor_thrust",
            "hover_thrust",
            "empuje",
            "resultant_force_n",
            "t_rotor",
        ),
        "disk_area_m2": (
            "disk_area_m2",
            "disk_area",
            "rotor_disk_area",
            "swept_area",
            "area_disco",
        ),
        "air_density_kg_m3": (
            "air_density_kg_m3",
            "air_density",
            "rho",
            "isa_density",
            "density",
        ),
        "figure_of_merit": (
            "figure_of_merit",
            "fm",
            "rotor_fm",
            "hover_fm",
        ),
        "power_available_kw": (
            "power_available_kw",
            "power_available",
            "p_avail",
            "max_power_kw",
            "shaft_power_limit",
        ),
    },
    "bolt_screen": {
        "shear_force_n": (
            "shear_force_n",
            "shear_force_kn",
            "shear_force",
            "shear_load",
            "cortante",
            "v_shear",
        ),
        "tensile_force_n": (
            "tensile_force_n",
            "tensile_force_kn",
            "tensile_force",
            "axial_force",
            "tension_force",
            "traccion",
        ),
        "area_mm2": (
            "area_mm2",
            "bolt_area",
            "fastener_area",
            "stress_area",
            "section_area",
            "cross_section_area",
        ),
        "shear_allowable_mpa": (
            "shear_allowable_mpa",
            "shear_allowable",
            "tau_allow",
            "fsu",
        ),
        "tensile_allowable_mpa": (
            "tensile_allowable_mpa",
            "tensile_allowable",
            "sigma_allow",
            "ftu",
        ),
    },
    "rigid_body_point_mass": {
        "mass_kg": (
            "mass_kg",
            "mass",
            "total_mass",
            "aircraft_mass",
            "mtow",
            "masa",
        ),
        "gravity_m_s2": ("gravity_m_s2", "gravity", "g_accel"),
        "load_factor": ("load_factor", "nz", "limit_load_factor", "maneuver_nz"),
        "cg_x_m": ("cg_x_m", "cg_x", "x_cg", "center_of_gravity_x", "cg_longitudinal"),
        "unit_x_m": ("unit_x_m", "station_x_m", "motor_x_m", "prop_x_m"),
        "unit_operative": ("unit_operative", "motors_operative", "active_units"),
    },
}

_DECLARED_OUTPUT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "hover_power_screen": {
        "disk_loading_pa": ("disk_loading_pa", "disk_loading", "dl"),
        "induced_velocity_m_s": ("induced_velocity_m_s", "induced_velocity", "vi"),
        "ideal_power_kw": ("ideal_power_kw", "ideal_power"),
        "shaft_power_kw": ("shaft_power_kw", "shaft_power", "out_shaft_power_kw"),
        "power_margin_ratio": ("power_margin_ratio", "power_margin", "out_power_margin_ratio"),
    },
    "bolt_screen": {
        "shear_stress_mpa": ("shear_stress_mpa", "shear_stress"),
        "tensile_stress_mpa": ("tensile_stress_mpa", "tensile_stress"),
        "shear_ratio": ("shear_ratio", "rs"),
        "tensile_ratio": ("tensile_ratio", "rt"),
        "interaction_ratio": ("interaction_ratio", "combined_ratio", "out_interaction_ratio"),
    },
    "rigid_body_point_mass": {
        "weight_n": ("weight_n", "weight"),
        "required_vertical_force_n": ("required_vertical_force_n", "required_force_n"),
        "unit_force_n": ("unit_force_n", "station_force_n"),
        "vertical_residual_n": ("vertical_residual_n", "residual_n"),
        "moment_about_cg_n_m": ("moment_about_cg_n_m", "moment_cg"),
    },
}


def _norm_ident(raw: str) -> str:
    leaf = raw.replace("/", "\\").split("\\")[-1].strip().lower()
    if leaf.startswith("aeroregu\\"):
        leaf = leaf[len("aeroregu\\") :]
    for ch in ("-", " ", "."):
        leaf = leaf.replace(ch, "_")
    while "__" in leaf:
        leaf = leaf.replace("__", "_")
    return leaf.strip("_")


def _norm_unit(raw_unit: str) -> str:
    cleaned = raw_unit.strip()
    if not cleaned:
        return ""
    return _UNIT_TOKEN_ALIASES.get(cleaned.lower(), cleaned)


def _match_field(norm_name: str, alias_map: dict[str, tuple[str, ...]]) -> str | None:
    for field, aliases in alias_map.items():
        if norm_name == field or norm_name in aliases:
            return field
    return None


def _value_as_card_repr(val: Any) -> Any:
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, bool):
                out.append(item)
            else:
                out.append(str(item))
        return out
    if isinstance(val, bool):
        return val
    return str(val)


def _decimal_equal(left: Any, right: Any) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        return left == right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return str(left) == str(right)


def bind_parameters_to_cards(
    parameters: list[dict[str, Any]],
    *,
    formulas: list[dict[str, Any]] | None = None,
    auto_run: bool = False,
) -> dict[str, Any]:
    """Deterministically bind Knowledgeware/CAD/FEM parameters to all verified calc cards."""
    method_ids = sorted(p.stem for p in cards_dir().glob("*.json"))
    cards_report: dict[str, Any] = {}
    ready_methods: list[str] = []

    for method_id in method_ids:
        card = load_card(method_id)
        alias_map = _FIELD_ALIASES.get(method_id, {})
        required_fields = list(card.get("required") or card.get("inputs", {}).keys())
        card_units = dict(card.get("input_units") or {})

        matched_inputs: dict[str, Any] = {}
        input_units: dict[str, str] = {}
        bindings: list[dict[str, Any]] = []
        unit_conflicts: list[dict[str, str]] = []
        ambiguous_conflicts: list[dict[str, Any]] = []

        for param in parameters:
            raw_name = str(param.get("name") or param.get("path") or "")
            if not raw_name:
                continue
            norm_name = _norm_ident(raw_name)
            field = _match_field(norm_name, alias_map)
            if field is None:
                continue

            raw_val = param.get("value")
            if raw_val in (None, ""):
                continue
            card_val = _value_as_card_repr(raw_val)
            raw_unit = str(param.get("unit") or "").strip()
            norm_u = _norm_unit(raw_unit)
            expected_u = card_units.get(field)

            if norm_u and expected_u:
                if not units_compatible(norm_u, expected_u):
                    unit_conflicts.append(
                        {
                            "card_field": field,
                            "source_path": str(param.get("path") or raw_name),
                            "given_unit": raw_unit,
                            "expected_unit": expected_u,
                        }
                    )
                    continue
                factor = conversion_interval(norm_u, expected_u)
                if not isinstance(factor, Decimal):
                    unit_conflicts.append(
                        {
                            "card_field": field,
                            "source_path": str(param.get("path") or raw_name),
                            "given_unit": raw_unit,
                            "expected_unit": expected_u,
                        }
                    )
                    continue

            if field in matched_inputs:
                existing_val = matched_inputs[field]
                if not _decimal_equal(existing_val, card_val):
                    ambiguous_conflicts.append(
                        {
                            "card_field": field,
                            "source_path": str(param.get("path") or raw_name),
                            "value": card_val,
                            "existing_value": existing_val,
                        }
                    )
                continue

            matched_inputs[field] = card_val
            if norm_u and expected_u:
                input_units[field] = norm_u
            bindings.append(
                {
                    "card_field": field,
                    "source_path": str(param.get("path") or raw_name),
                    "raw_value": card_val,
                    "raw_unit": raw_unit or (expected_u or ""),
                    "card_unit": expected_u or "",
                    "source_kind": str(param.get("source_kind") or "cad"),
                    "match_kind": "exact" if norm_name == field else "alias",
                }
            )

        if input_units:
            matched_inputs["_input_units"] = input_units

        # Map any Knowledgeware formulas/outputs matching card output variables
        declared_outputs: dict[str, Any] = {}
        out_aliases = _DECLARED_OUTPUT_ALIASES.get(method_id, {})
        for f in formulas or []:
            fname = _norm_ident(str(f.get("output_param") or f.get("name") or ""))
            out_field = _match_field(fname, out_aliases)
            if out_field and f.get("declared_value") not in (None, ""):
                declared_outputs[out_field] = _value_as_card_repr(f["declared_value"])
        for param in parameters:
            pname = _norm_ident(str(param.get("name") or ""))
            out_field = _match_field(pname, out_aliases)
            if out_field and param.get("value") not in (None, ""):
                declared_outputs.setdefault(out_field, _value_as_card_repr(param["value"]))

        missing_required = [req for req in required_fields if req not in matched_inputs]
        ready = (
            len(missing_required) == 0
            and len(unit_conflicts) == 0
            and len(ambiguous_conflicts) == 0
        )
        if ready:
            ready_methods.append(method_id)

        execution: dict[str, Any] | None = None
        if auto_run and ready:
            try:
                ran = run_method(
                    method_id,
                    matched_inputs,
                    normalize_units=bool(input_units),
                    include_intervals=True,
                )
                execution = {
                    "confidence": "deterministic",
                    "method_version": ran["method_version"],
                    "outputs": ran["outputs"],
                    "exact_intervals": ran.get("exact_intervals", {}),
                    "unit_conversions": ran.get("unit_conversions", []),
                }
            except AbstainError as exc:
                execution = {"confidence": "abstain", "abstain_reason": exc.reason}

        cards_report[method_id] = {
            "method_id": method_id,
            "method_version": card["method_version"],
            "matched_count": len(bindings),
            "required_count": len(required_fields),
            "ready_to_run": ready,
            "missing_required": missing_required,
            "unit_conflicts": unit_conflicts,
            "ambiguous_conflicts": ambiguous_conflicts,
            "bindings": bindings,
            "matched_inputs": matched_inputs,
            "declared_outputs": declared_outputs,
            "execution": execution,
        }

    return {
        "cards": cards_report,
        "ready_methods": ready_methods,
        "total_parameters_scanned": len(parameters),
    }
