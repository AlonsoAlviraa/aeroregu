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
