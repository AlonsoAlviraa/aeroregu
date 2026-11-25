"""Safe AST Decimal & Arb engine for user-defined declarative calculation cards."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from flint import arb, ctx

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum, parse_limited_decimal, quantize
from evidence_calc.units import _unit, check_expression_dimensional_homogeneity

_CARD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_VAR_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESERVED_BUILTIN_IDS = frozenset(
    {
        "rigid_body_point_mass",
        "bolt_screen",
        "hover_power_screen",
        "margin_of_safety",
        "column_plate_buckling",
        "palmgren_miner_fatigue",
        "composite_failure_criteria",
        "nasgro_paris_crack_growth",
        "goodman_haigh_mean_stress",
        "neuber_notch_plasticity",
        "net_section_yielding_fracture",
        "rainflow_spectrum_damage",
        "tsai_wu_ply_failure",
        "hashin_composite_modes",
        "puck_interfiber_fracture",
        "open_hole_tension_oht",
        "open_hole_compression_ohc",
        "compression_after_impact_cai",
        "huth_fastener_flexibility",
        "bearing_bypass_interaction",
        "eccentric_bolt_group_cg",
        "lug_axial_transverse_interaction",
        "bolt_preload_thermal_relaxation",
        "fastener_pull_through_composite",
        "adhesive_single_lap_volkersen",
        "johnson_euler_column",
        "needham_crippling_section",
        "shear_web_diagonal_tension",
        "curved_panel_compression_shear",
        "inter_rivet_buckling",
        "thin_walled_bredt_batho_torsion",
        "sandwich_core_shear_wrinkling",
        "aerospace_quotation_costing",
        "aerospace_multiyear_cashflow_learning",
        "engineering_workpackage_quote",
        "rotorcraft_archetype_quote",
        "rotorcraft_historical_calibration",
        "clt_laminate_abd_stiffness",
        "rotor_blade_centrifugal_bending",
        "ground_resonance_coleman_screen",
        "cs29_crashworthiness_561_562_load",
        "multirow_bolt_load_distribution",
        "larc04_composite_failure",
        "cs29_bird_strike_penetration_screen",
        "campbell_rotor_harmonic_clearance",
        "tailboom_boxbeam_combined_stress",
        "statistical_ab_basis_tolerance_bound",
        "bolt_prying_combined_tension_shear",
        "goland_reissner_adhesive_peel_shear",
        "orthotropic_composite_plate_buckling",
        "skin_stringer_crippling_interaction",
        "walker_mean_stress_crack_growth",
    }
)


def _reserved_builtin_ids() -> frozenset[str]:
    """Return union of pinned built-in IDs and built-in JSON card filenames."""
    cards_root = Path(__file__).resolve().parents[2] / "cards"
    disk_ids = {p.stem for p in cards_root.glob("*.json")} if cards_root.is_dir() else set()
    return _RESERVED_BUILTIN_IDS | frozenset(disk_ids)


_PI_DEC = Decimal("3.141592653589793238462643383279502884197")
_MAX_AST_DEPTH = 24
_MAX_EXPONENT = Decimal("20")
_BALL_DPS = 50


def plugin_cards_dir(custom_dir: Path | None = None) -> Path:
    """Resolve user declarative plugin cards directory under EVIDENCE_HOME or local home."""
    if custom_dir is not None:
        return Path(custom_dir)
    env_home = os.environ.get("EVIDENCE_HOME", "").strip()
    if env_home:
        return Path(env_home) / "plugins" / "cards"
    return Path(__file__).resolve().parents[4] / ".evidence_home" / "plugins" / "cards"


def card_sha256(card: dict[str, Any]) -> str:
    """Compute canonical SHA-256 provenance digest for a declarative card."""
    normalized = json.dumps(card, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _check_ast_node(node: ast.AST, depth: int = 0) -> None:
    if depth > _MAX_AST_DEPTH:
        raise AbstainError("invalid_plugin_formula")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.Compare,
        ast.IfExp,
        ast.BoolOp,
    )
    if not isinstance(node, allowed_nodes):
        raise AbstainError("invalid_plugin_formula")
    if isinstance(node, ast.Expression):
        _check_ast_node(node.body, depth + 1)
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, str)):
            raise AbstainError("invalid_plugin_formula")
        try:
            Decimal(str(node.value))
        except Exception as exc:
            raise AbstainError("invalid_plugin_formula") from exc
        return
    if isinstance(node, ast.Name):
        if not _VAR_NAME_RE.fullmatch(node.id):
            raise AbstainError("invalid_plugin_formula")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise AbstainError("invalid_plugin_formula")
        _check_ast_node(node.operand, depth + 1)
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            raise AbstainError("invalid_plugin_formula")
        _check_ast_node(node.left, depth + 1)
        _check_ast_node(node.right, depth + 1)
        return
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise AbstainError("invalid_plugin_formula")
        for val in node.values:
            _check_ast_node(val, depth + 1)
        return
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise AbstainError("invalid_plugin_formula")
        if not isinstance(node.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
            raise AbstainError("invalid_plugin_formula")
        _check_ast_node(node.left, depth + 1)
        _check_ast_node(node.comparators[0], depth + 1)
        return
    if isinstance(node, ast.IfExp):
        _check_ast_node(node.test, depth + 1)
        _check_ast_node(node.body, depth + 1)
        _check_ast_node(node.orelse, depth + 1)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise AbstainError("invalid_plugin_formula")
        if node.func.id not in {"sqrt", "abs", "min", "max", "pow"}:
            raise AbstainError("invalid_plugin_formula")
        if node.func.id in {"sqrt", "abs"} and len(node.args) != 1:
            raise AbstainError("invalid_plugin_formula")
        if node.func.id == "pow" and len(node.args) != 2:
            raise AbstainError("invalid_plugin_formula")
        if node.func.id in {"min", "max"} and len(node.args) < 2:
            raise AbstainError("invalid_plugin_formula")
        for arg in node.args:
            _check_ast_node(arg, depth + 1)


def _rewrite_decimal_literals(expr: str) -> str:
    """Validate expression AST without raw binary constants."""
    token_pattern = re.compile(r"(?<![A-Za-z0-9_\x27\x22])\d+\.\d+(?![A-Za-z0-9_\x27\x22])")
    return token_pattern.sub(lambda m: repr(m.group(0)), expr)


def parse_safe_expression(expr: str) -> ast.Expression:
    """Parse and validate a mathematical expression for declarative plugin cards."""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > 512:
        raise AbstainError("invalid_plugin_formula")
    sanitized = _rewrite_decimal_literals(expr.strip())
    try:
        tree = ast.parse(sanitized, mode="eval")
    except SyntaxError as exc:
        raise AbstainError("invalid_plugin_formula") from exc
    _check_ast_node(tree)
    return tree


def _eval_decimal_ast(node: ast.AST, env: dict[str, Decimal]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_decimal_ast(node.body, env)
    if isinstance(node, ast.Constant):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return _PI_DEC
        if node.id not in env:
            raise AbstainError("unknown_plugin_symbol")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval_decimal_ast(node.operand, env)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        left = _eval_decimal_ast(node.left, env)
        right = _eval_decimal_ast(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise AbstainError("division_by_zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > _MAX_EXPONENT:
                raise AbstainError("outside_validity")
            if left == 0 and right < 0:
                raise AbstainError("division_by_zero")
            if left < 0 and right != int(right):
                raise AbstainError("outside_validity")
            return left**right
    if isinstance(node, ast.Compare):
        left = _eval_decimal_ast(node.left, env)
        right = _eval_decimal_ast(node.comparators[0], env)
        op = node.ops[0]
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Eq):
            return left == right
        return left != right
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(bool(_eval_decimal_ast(v, env)) for v in node.values)
        return any(bool(_eval_decimal_ast(v, env)) for v in node.values)
    if isinstance(node, ast.IfExp):
        cond = bool(_eval_decimal_ast(node.test, env))
        return _eval_decimal_ast(node.body if cond else node.orelse, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id
        vals = [_eval_decimal_ast(a, env) for a in node.args]
        if fn == "sqrt":
            if vals[0] < 0:
                raise AbstainError("outside_validity")
            return vals[0].sqrt()
        if fn == "abs":
            return vals[0].copy_abs()
        if fn == "min":
            return min(vals)
        if fn == "max":
            return max(vals)
        if fn == "pow":
            base, exp = vals
            if abs(exp) > _MAX_EXPONENT or (base == 0 and exp < 0):
                raise AbstainError("outside_validity")
            return base**exp
    raise AbstainError("invalid_plugin_formula")


def _eval_arb_ast(node: ast.AST, env: dict[str, arb], dec_env: dict[str, Decimal]) -> arb:
    ctx.dps = _BALL_DPS
    if isinstance(node, ast.Expression):
        return _eval_arb_ast(node.body, env, dec_env)
    if isinstance(node, ast.Constant):
        return _arb_from_decimal_text_local(str(node.value))
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return arb.pi()
        if node.id not in env:
            raise AbstainError("unknown_plugin_symbol")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        op_val = _eval_arb_ast(node.operand, env, dec_env)
        return op_val if isinstance(node.op, ast.UAdd) else -op_val
    if isinstance(node, ast.BinOp):
        left = _eval_arb_ast(node.left, env, dec_env)
        right = _eval_arb_ast(node.right, env, dec_env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.IfExp):
        cond = bool(_eval_decimal_ast(node.test, dec_env))
        return _eval_arb_ast(node.body if cond else node.orelse, env, dec_env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id
        vals = [_eval_arb_ast(a, env, dec_env) for a in node.args]
        dec_vals = [_eval_decimal_ast(a, dec_env) for a in node.args]
        if fn == "sqrt":
            return vals[0].sqrt()
        if fn == "abs":
            return abs(vals[0])
        if fn == "min":
            best_idx = min(range(len(dec_vals)), key=lambda i: dec_vals[i])
            return vals[best_idx]
        if fn == "max":
            best_idx = max(range(len(dec_vals)), key=lambda i: dec_vals[i])
            return vals[best_idx]
        if fn == "pow":
            return vals[0] ** vals[1]
    raise AbstainError("invalid_plugin_formula")


def _arb_from_decimal_text_local(text: str) -> arb:
    from fractions import Fraction

    from flint import fmpq

    ctx.dps = _BALL_DPS
    frac = Fraction(text)
    if frac.denominator == 1:
        return arb(int(frac.numerator))
    return arb(fmpq(int(frac.numerator), int(frac.denominator)))


def validate_plugin_card(
    card: dict[str, Any], *, allow_overwrite_builtin: bool = False
) -> dict[str, Any]:
    """Validate and normalize a declarative calculation method card."""
    if not isinstance(card, dict):
        raise AbstainError("invalid_plugin_card")
    method_id = str(card.get("method_id") or "").strip()
    if not _CARD_ID_RE.fullmatch(method_id):
        raise AbstainError("invalid_plugin_card")
    if not allow_overwrite_builtin and method_id in _reserved_builtin_ids():
        raise AbstainError("builtin_method_protected")

    title = str(card.get("title") or "").strip()
    if not title or len(title) > 180:
        raise AbstainError("invalid_plugin_card")

    quantum_raw = str(card.get("quantum") or "0.001").strip()
    try:
        q = Decimal(quantum_raw)
    except Exception as exc:
        raise AbstainError("invalid_plugin_card") from exc
    if q <= 0 or q > Decimal("1"):
        raise AbstainError("invalid_plugin_card")

    required = card.get("required")
    if not isinstance(required, list) or not required:
        raise AbstainError("invalid_plugin_card")
    clean_required: list[str] = []
    for req in required:
        key = str(req).strip()
        if not _VAR_NAME_RE.fullmatch(key) or key == "pi" or key in clean_required:
            raise AbstainError("invalid_plugin_card")
        clean_required.append(key)

    limits = card.get("limits")
    if not isinstance(limits, dict):
        raise AbstainError("invalid_plugin_card")
    clean_limits: dict[str, dict[str, str]] = {}
    for key in clean_required:
        spec = limits.get(key)
        if not isinstance(spec, dict) or not any(
            bound in spec for bound in ("min", "min_exclusive", "max", "max_exclusive")
        ):
            raise AbstainError("invalid_plugin_card")
        clean_spec: dict[str, str] = {}
        for bound_key in ("min", "min_exclusive", "max", "max_exclusive"):
            if bound_key in spec:
                try:
                    Decimal(str(spec[bound_key]))
                except Exception as exc:
                    raise AbstainError("invalid_plugin_card") from exc
                clean_spec[bound_key] = str(spec[bound_key])
        clean_limits[key] = clean_spec

    input_units = card.get("input_units") or {k: "dimensionless" for k in clean_required}
    if not isinstance(input_units, dict):
        raise AbstainError("invalid_plugin_card")
    clean_units: dict[str, str] = {}
    for key in clean_required:
        u_name = str(input_units.get(key) or "dimensionless").strip()
        try:
            _unit(u_name)
        except Exception as exc:
            raise AbstainError("invalid_plugin_unit") from exc
        clean_units[key] = u_name

    formulas = card.get("formulas")
    if not isinstance(formulas, list) or not formulas:
        raise AbstainError("invalid_plugin_formula")
    has_explicit_units = bool(card.get("input_units")) or any(
        isinstance(s, dict) and s.get("unit") for s in formulas
    )
    dim_env: dict[str, Any] = dict(clean_units)
    known_symbols = set(clean_required) | {"pi"}
    clean_formulas: list[dict[str, str]] = []
    output_names: set[str] = set()
    for step in formulas:
        if not isinstance(step, dict):
            raise AbstainError("invalid_plugin_formula")
        out_name = str(step.get("output") or "").strip()
        expr = str(step.get("expr") or "").strip()
        if (
            not _VAR_NAME_RE.fullmatch(out_name)
            or out_name in known_symbols
            or out_name in output_names
        ):
            raise AbstainError("invalid_plugin_formula")
        tree = parse_safe_expression(expr)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in known_symbols:
                # Permit referencing previously defined formula outputs in order
                if node.id not in output_names:
                    raise AbstainError("unknown_plugin_symbol")
        clean_step: dict[str, str] = {"output": out_name, "expr": expr}
        if step.get("unit"):
            clean_step["unit"] = str(step["unit"]).strip()
        if has_explicit_units:
            inferred_dims = check_expression_dimensional_homogeneity(
                expr,
                dim_env,
                expected_output_unit=clean_step.get("unit"),
            )
            dim_env[out_name] = inferred_dims
        output_names.add(out_name)
        clean_formulas.append(clean_step)

    method_version = str(card.get("method_version") or f"{method_id}@1.0.0").strip()
    label = str(card.get("label") or "PLUGIN_USER_CARD").strip()
    note = str(card.get("note") or "User-defined declarative plugin method card.").strip()
    src_hash = hashlib.sha256(f"plugin:{method_id}:{method_version}".encode()).hexdigest()
    sources = card.get("sources") or [
        {
            "source_id": f"plugin-{method_id}",
            "uri": f"https://aeroregu.local/plugins/{method_id}",
            "content_hash": src_hash,
            "label": "VERIFIED",
        }
    ]
    normalized: dict[str, Any] = {
        "method_id": method_id,
        "method_version": method_version,
        "title": title,
        "label": label,
        "equation": "; ".join(f"{s['output']} = {s['expr']}" for s in clean_formulas) + ".",
        "note": note,
        "quantum": quantum_raw,
        "not_a_certification_method": bool(card.get("not_a_certification_method", True)),
        "plugin": True,
        "input_units": clean_units,
        "required": clean_required,
        "limits": clean_limits,
        "formulas": clean_formulas,
        "sources": sources,
    }
    if card.get("aliases") and isinstance(card["aliases"], dict):
        normalized["aliases"] = dict(card["aliases"])
    normalized["card_sha256"] = card_sha256(normalized)
    return normalized


def register_plugin_card(
    card: dict[str, Any],
    *,
    plugins_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate and persist a declarative user calculation card."""
    normalized = validate_plugin_card(card)
    target_dir = plugin_cards_dir(plugins_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{normalized['method_id']}.json"
    target_path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return normalized


def delete_plugin_card(method_id: str, *, plugins_dir: Path | None = None) -> bool:
    """Remove a declarative plugin card by method_id."""
    if not _CARD_ID_RE.fullmatch(method_id) or method_id in _reserved_builtin_ids():
        return False
    target = plugin_cards_dir(plugins_dir) / f"{method_id}.json"
    if target.is_file():
        target.unlink()
        return True
    return False


def list_plugin_cards(*, plugins_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load all valid declarative plugin cards from disk."""
    target_dir = plugin_cards_dir(plugins_dir)
    if not target_dir.is_dir():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(target_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cards.append(validate_plugin_card(raw))
        except Exception:
            continue
    return cards


def load_plugin_card(method_id: str, *, plugins_dir: Path | None = None) -> dict[str, Any] | None:
    """Load a single declarative plugin card if registered on disk."""
    if not _CARD_ID_RE.fullmatch(method_id):
        return None
    path = plugin_cards_dir(plugins_dir) / f"{method_id}.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    card = validate_plugin_card(raw)
    if card.get("method_id") != method_id:
        return None
    return card


def run_declarative_card(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Execute a declarative plugin card using bounded Decimal AST evaluation."""
    required = list(card["required"])
    for key in required:
        if not isinstance(inputs, dict) or key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")

    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]
    dec_env: dict[str, Decimal] = {}
    for key in required:
        dec_env[key] = parse_limited_decimal(inputs[key], limits[key])

    outputs: dict[str, str] = {}
    for step in card["formulas"]:
        out_name = str(step["output"])
        tree = parse_safe_expression(str(step["expr"]))
        raw_val = _eval_decimal_ast(tree, dec_env)
        if not isinstance(raw_val, Decimal):
            raise AbstainError("invalid_plugin_formula")
        dec_val = quantize(raw_val, quantum)
        dec_env[out_name] = raw_val
        outputs[out_name] = format_quantum(dec_val, quantum)

    return {
        "method_id": card["method_id"],
        "method_version": card["method_version"],
        "outputs": outputs,
        "sources": card["sources"],
        "card_title": card["title"],
        "label": card["label"],
        "plugin": True,
        "card_sha256": card.get("card_sha256") or card_sha256(card),
    }


def evaluate_declarative_intervals(
    card: dict[str, Any],
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
    drift_entry_fn: Any,
) -> dict[str, dict[str, Any]]:
    """Evaluate declarative plugin formulas without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    limits = card["limits"]
    dec_env: dict[str, Decimal] = {
        key: parse_limited_decimal(inputs[key], limits[key]) for key in card["required"]
    }
    arb_env: dict[str, arb] = {
        key: _arb_from_decimal_text_local(str(inputs[key])) for key in card["required"]
    }
    intervals: dict[str, dict[str, Any]] = {}
    for step in card["formulas"]:
        out_name = str(step["output"])
        tree = parse_safe_expression(str(step["expr"]))
        dec_val = _eval_decimal_ast(tree, dec_env)
        arb_val = _eval_arb_ast(tree, arb_env, dec_env)
        dec_env[out_name] = dec_val
        arb_env[out_name] = arb_val
        if out_name in staged_outputs:
            intervals[out_name] = drift_entry_fn(arb_val, str(staged_outputs[out_name]))
    return intervals
