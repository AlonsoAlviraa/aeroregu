from __future__ import annotations

from decimal import Decimal
from tokenize import TokenError
from typing import Any

from pint import UnitRegistry
from pint.errors import DimensionalityError, OffsetUnitCalculusError, UndefinedUnitError

from evidence_calc.errors import AbstainError

_UREG = UnitRegistry()
_DECIMAL_UREG = UnitRegistry(non_int_type=Decimal)
_UNITS: dict[str, Any] = {}


def check_declared_units(inputs: dict[str, Any], card: dict[str, Any]) -> None:
    overrides = inputs.get("_input_units")
    if not overrides:
        return
    spec = card.get("input_units")
    if not isinstance(spec, dict):
        raise AbstainError("unit_mismatch")
    if not isinstance(overrides, dict):
        raise AbstainError("unit_mismatch")
    for key, given_name in overrides.items():
        expected_name = spec.get(key)
        if expected_name is None:
            raise AbstainError("unit_mismatch")
        try:
            expected = _unit(str(expected_name))
            given = _unit(str(given_name))
        except (UndefinedUnitError, ValueError, TypeError) as exc:
            raise AbstainError("unit_mismatch") from exc
        if not given.is_compatible_with(expected):
            raise AbstainError("unit_mismatch")


def require_declared_units(inputs: dict[str, Any], card: dict[str, Any]) -> None:
    spec = card.get("input_units") or {}
    if not isinstance(spec, dict):
        raise AbstainError("unit_mismatch")
    overrides = inputs.get("_input_units")
    if not isinstance(overrides, dict):
        raise AbstainError("missing_input_units")
    for key in spec:
        given = overrides.get(key)
        if not isinstance(given, str) or not given.strip():
            raise AbstainError("missing_input_units")
    check_declared_units(inputs, card)


def units_compatible(left: str, right: str) -> bool:
    try:
        return bool(_unit(left).is_compatible_with(_unit(right)))
    except (UndefinedUnitError, ValueError, TypeError):
        return False


_PINT_BASE = {
    "[mass]": "M",
    "[length]": "L",
    "[time]": "T",
    "[current]": "I",
    "[temperature]": "Θ",
    "[substance]": "N",
    "[luminosity]": "J",
    "[angle]": "A",
}


def conversion_interval(left: str, right: str) -> Any:
    """Size of one left unit measured in right units.

    The magnitude is a Decimal. Any other magnitude is refused.
    Pint refuses the subtraction for offset units such as degree Celsius,
    and this function then returns None. The string incompatible means
    the dimensions differ.
    """
    try:
        left_unit = _decimal_quantity(left)
        right_unit = _decimal_quantity(right)
        if not left_unit.is_compatible_with(right_unit):
            return "incompatible"
        magnitude = ((2 * left_unit) - (1 * left_unit)).to(right_unit.units).magnitude
    except (
        UndefinedUnitError,
        DimensionalityError,
        OffsetUnitCalculusError,
        TokenError,
        ValueError,
        TypeError,
        ZeroDivisionError,
    ):
        return None
    if not isinstance(magnitude, Decimal):
        return None
    return magnitude


def dimension_exponents(name: str) -> dict[str, int] | None:
    """SI-letter exponents for a unit name.

    Returns an empty dict for a dimensionless unit. Returns None when the
    name is not in the registry or uses a base this table does not name.
    """
    try:
        dimensionality = _unit(name).dimensionality
    except (UndefinedUnitError, ValueError, TypeError):
        return None
    exponents: dict[str, int] = {}
    for key, exp in dimensionality.items():
        letter = _PINT_BASE.get(str(key))
        if letter is None:
            return None
        exponent = int(exp)
        if exponent != 0:
            exponents[letter] = exponent
    return exponents


def extended_dimension_exponents(name: str) -> dict[str, int] | None:
    """SI-letter exponents supporting extended engineering/SI Unicode & symbolic tokens.

    Preserves the pinned ``dimension_exponents`` registry contract while resolving
    extended aerospace/electrical tokens (``kvar``, ``Jy``, ``arcmin``, ``arcsec``,
    ``kJ/mol``, ``mG``) and safe superscript/middot forms (``m²``, ``m³``, ``N·m``).
    """
    text = str(name).strip()
    extended_aliases = {
        "kvar": "kilovolt * ampere",
        "Jy": "watt / meter ** 2 / hertz",
        "arcmin": "arcminute",
        "arcsec": "arcsecond",
        "kJ/mol": "kilojoule / mole",
        "mG": "milligauss",
        "N·m": "newton * meter",
        "m²": "meter ** 2",
        "m³": "meter ** 3",
    }
    if text in extended_aliases:
        return dimension_exponents(extended_aliases[text])
    if not any(ch in text for ch in ("°", "⁻")) and any(ch in text for ch in ("²", "³", "·")):
        cleaned = text.replace("²", "**2").replace("³", "**3").replace("·", " * ").strip()
        return dimension_exponents(extended_aliases.get(cleaned, cleaned))
    return dimension_exponents(text)


def same_unit(left: str, right: str) -> bool:
    """True when the units match and the scale factor is one."""
    try:
        magnitude = conversion_interval(left, right)
    except (UndefinedUnitError, ValueError, TypeError):
        return False
    return isinstance(magnitude, Decimal) and magnitude == Decimal(1)


def convert_inputs_to_card_units(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Convert declared _input_units fields into canonical card units using Decimal factors."""
    spec = card.get("input_units")
    overrides = inputs.get("_input_units")
    if not isinstance(overrides, dict) or not overrides:
        return dict(inputs), []
    if not isinstance(spec, dict):
        raise AbstainError("unit_mismatch")

    converted = dict(inputs)
    conversions: list[dict[str, str]] = []
    for key, raw_unit in overrides.items():
        expected_unit = spec.get(key)
        if expected_unit is None:
            raise AbstainError("unit_mismatch")
        given_unit = str(raw_unit)
        factor = conversion_interval(given_unit, str(expected_unit))
        if factor == "incompatible":
            raise AbstainError("unit_mismatch")
        if not isinstance(factor, Decimal):
            raise AbstainError("non_decimal_conversion")
        if key not in inputs or inputs[key] in (None, ""):
            continue
        raw_val = inputs[key]
        if not isinstance(raw_val, str):
            raise AbstainError("outside_validity")
        try:
            scaled = Decimal(raw_val) * factor
        except Exception as exc:
            raise AbstainError("outside_validity") from exc
        conv_str = format(scaled, "f")
        converted[key] = conv_str
        if factor != Decimal(1):
            conversions.append(
                {
                    "field": str(key),
                    "raw_value": raw_val,
                    "from_unit": given_unit,
                    "to_unit": str(expected_unit),
                    "factor": format(factor, "f"),
                    "converted_value": conv_str,
                }
            )
    return converted, conversions


def _normalize_unit(name: str) -> str:
    aliases = {
        "m/s2": "meter / second ** 2",
        "m/s^2": "meter / second ** 2",
        "m/s": "meter / second",
        "mps": "meter / second",
        "km/h": "kilometer / hour",
        "kph": "kilometer / hour",
        "km/hr": "kilometer / hour",
        "mph": "mile / hour",
        "ft/min": "foot / minute",
        "fpm": "foot / minute",
        "1": "dimensionless",
        "daN": "decanewton",
        "kN": "kilonewton",
        "N*m": "newton * meter",
        "N·m": "newton * meter",
        "N-m": "newton * meter",
        "ft*lbf": "foot * pound_force",
        "lbf*ft": "foot * pound_force",
        "MPa": "megapascal",
        "GPa": "gigapascal",
        "kPa": "kilopascal",
        "Pa": "pascal",
        "psi": "pound_force_per_square_inch",
        "lbf": "pound_force",
        "kgf": "kilogram_force",
        "lb": "pound",
        "lbs": "pound",
        "knot": "knot",
        "kt": "knot",
        "kts": "knot",
        "kn": "knot",
        "nmi": "nautical_mile",
        "NM": "nautical_mile",
        "g_force": "standard_gravity",
        "rpm": "revolution / minute",
        "deg": "degree",
        "rad": "radian",
        "ft": "foot",
        "in": "inch",
        "cm^2": "centimeter ** 2",
        "mm^2": "millimeter ** 2",
        "m^2": "meter ** 2",
        "in^2": "inch ** 2",
        "ft^2": "foot ** 2",
        "m^3": "meter ** 3",
        "L": "liter",
    }
    return aliases.get(name, name)


def _decimal_quantity(name: str):
    return _DECIMAL_UREG.Quantity(Decimal(1), _normalize_unit(name))


def _unit(name: str):
    normalized = _normalize_unit(name)
    cached = _UNITS.get(normalized)
    if cached is None:
        cached = _UREG.Unit(normalized)
        _UNITS[normalized] = cached
    return cached


def _clean_dims(dims: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in dims.items() if v != 0}


def _rewrite_dec_tokens_for_ast(expr: str) -> str:
    import re

    pat = re.compile(r"(?<![A-Za-z0-9_\x27\x22])\d+\.\d+(?![A-Za-z0-9_\x27\x22])")
    return pat.sub(lambda m: repr(m.group(0)), expr)


def _const_fraction_or_none(node: Any) -> Any:
    import ast
    from fractions import Fraction

    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, str))
        and not isinstance(node.value, bool)
    ):
        try:
            return Fraction(str(node.value))
        except Exception:
            return None
    if isinstance(node, ast.UnaryOp):
        inner = _const_fraction_or_none(node.operand)
        if inner is None:
            return None
        if isinstance(node.op, ast.UAdd):
            return inner
        if isinstance(node.op, ast.USub):
            return -inner
    if isinstance(node, ast.BinOp):
        lv = _const_fraction_or_none(node.left)
        rv = _const_fraction_or_none(node.right)
        if lv is None or rv is None:
            return None
        if isinstance(node.op, ast.Add):
            return lv + rv
        if isinstance(node.op, ast.Sub):
            return lv - rv
        if isinstance(node.op, ast.Mult):
            return lv * rv
        if isinstance(node.op, ast.Div) and rv != 0:
            return lv / rv
    return None


def _is_zero_const(node: Any) -> bool:
    val = _const_fraction_or_none(node)
    return val is not None and val == 0


def check_expression_dimensional_homogeneity(
    expr: str,
    symbol_units: dict[str, Any],
    expected_output_unit: str | None = None,
) -> dict[str, int]:
    """Verify static dimensional homogeneity over formula AST using SI exponent vectors.

    Raises AbstainError("dimensional_inhomogeneity") on incompatible additions/subtractions,
    non-dimensionless exponents or transcendental arguments, odd-exponent sqrt, or mismatch
    against expected_output_unit.
    """
    import ast

    sanitized = _rewrite_dec_tokens_for_ast(str(expr).strip())
    try:
        tree = ast.parse(sanitized, mode="eval")
    except SyntaxError as exc:
        raise AbstainError("invalid_plugin_formula") from exc

    resolved_dims: dict[str, dict[str, int]] = {"pi": {}}
    for sym, spec in symbol_units.items():
        if isinstance(spec, dict):
            resolved_dims[sym] = _clean_dims(dict(spec))
        else:
            unit_str = str(spec).strip() or "dimensionless"
            exps = dimension_exponents(unit_str)
            if exps is None:
                raise AbstainError("invalid_plugin_unit")
            resolved_dims[sym] = _clean_dims(exps)

    def _infer(node: ast.AST) -> dict[str, int]:
        if isinstance(node, ast.Expression):
            return _infer(node.body)
        if isinstance(node, ast.Constant):
            return {}
        if isinstance(node, ast.Name):
            if node.id not in resolved_dims:
                raise AbstainError("unknown_plugin_symbol")
            return dict(resolved_dims[node.id])
        if isinstance(node, ast.UnaryOp):
            return _infer(node.operand)
        if isinstance(node, ast.BoolOp):
            for val in node.values:
                _infer(val)
            return {}
        if isinstance(node, ast.Compare):
            ld = _infer(node.left)
            rd = _infer(node.comparators[0])
            if ld != rd and not (_is_zero_const(node.left) or _is_zero_const(node.comparators[0])):
                raise AbstainError("dimensional_inhomogeneity")
            return {}
        if isinstance(node, ast.IfExp):
            _infer(node.test)
            bd = _infer(node.body)
            od = _infer(node.orelse)
            if bd != od and not (_is_zero_const(node.body) or _is_zero_const(node.orelse)):
                raise AbstainError("dimensional_inhomogeneity")
            return od if _is_zero_const(node.body) else bd
        if isinstance(node, ast.BinOp):
            ld = _infer(node.left)
            rd = _infer(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if ld != rd:
                    raise AbstainError("dimensional_inhomogeneity")
                return ld
            if isinstance(node.op, ast.Mult):
                out = dict(ld)
                for k, v in rd.items():
                    out[k] = out.get(k, 0) + v
                return _clean_dims(out)
            if isinstance(node.op, ast.Div):
                out = dict(ld)
                for k, v in rd.items():
                    out[k] = out.get(k, 0) - v
                return _clean_dims(out)
            if isinstance(node.op, ast.Pow):
                if rd:
                    raise AbstainError("dimensional_inhomogeneity")
                if not ld:
                    return {}
                exp_frac = _const_fraction_or_none(node.right)
                if exp_frac is None:
                    raise AbstainError("dimensional_inhomogeneity")
                out: dict[str, int] = {}
                for k, v in ld.items():
                    scaled = v * exp_frac
                    if scaled.denominator != 1:
                        raise AbstainError("dimensional_inhomogeneity")
                    out[k] = int(scaled)
                return _clean_dims(out)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn_name = node.func.id
            arg_dims = [_infer(a) for a in node.args]
            if fn_name == "abs" and len(arg_dims) == 1:
                return arg_dims[0]
            if fn_name in {"min", "max"} and arg_dims:
                non_zero = [
                    d for a, d in zip(node.args, arg_dims, strict=False) if not _is_zero_const(a)
                ]
                ref = non_zero[0] if non_zero else arg_dims[0]
                if any(d != ref for d in non_zero):
                    raise AbstainError("dimensional_inhomogeneity")
                return ref
            if fn_name == "sqrt" and len(arg_dims) == 1:
                out = {}
                for k, v in arg_dims[0].items():
                    if v % 2 != 0:
                        raise AbstainError("dimensional_inhomogeneity")
                    out[k] = v // 2
                return _clean_dims(out)
            if fn_name == "pow" and len(arg_dims) == 2:
                ld, rd = arg_dims
                if rd:
                    raise AbstainError("dimensional_inhomogeneity")
                if not ld:
                    return {}
                exp_frac = _const_fraction_or_none(node.args[1])
                if exp_frac is None:
                    raise AbstainError("dimensional_inhomogeneity")
                out = {}
                for k, v in ld.items():
                    scaled = v * exp_frac
                    if scaled.denominator != 1:
                        raise AbstainError("dimensional_inhomogeneity")
                    out[k] = int(scaled)
                return _clean_dims(out)
            if fn_name in {"sin", "cos", "tan", "exp", "log", "ln"} and len(arg_dims) == 1:
                if arg_dims[0]:
                    raise AbstainError("dimensional_inhomogeneity")
                return {}
        raise AbstainError("dimensional_inhomogeneity")

    inferred = _clean_dims(_infer(tree))
    if expected_output_unit:
        expected_dims = dimension_exponents(str(expected_output_unit).strip())
        if expected_dims is None:
            raise AbstainError("invalid_plugin_unit")
        if inferred != _clean_dims(expected_dims):
            raise AbstainError("dimensional_inhomogeneity")
    return inferred
