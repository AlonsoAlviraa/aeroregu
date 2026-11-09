from __future__ import annotations

from typing import Any

from pint import UnitRegistry
from pint.errors import UndefinedUnitError

from evidence_calc.errors import AbstainError

_UREG = UnitRegistry()
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

    Two units minus one unit. Pint refuses that subtraction for offset
    units such as degree Celsius, and this function then returns None.
    The string incompatible means the dimensions differ.
    """
    from decimal import Decimal

    try:
        left_unit = _unit(left)
        right_unit = _unit(right)
        if not left_unit.is_compatible_with(right_unit):
            return "incompatible"
        magnitude = ((2 * left_unit) - (1 * left_unit)).to(right_unit).magnitude
    except Exception:
        return None
    return Decimal(str(magnitude))


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
    from decimal import Decimal

    left_name = _normalize_unit(left)
    right_name = _normalize_unit(right)
    try:
        left_unit = _unit(left_name)
        right_unit = _unit(right_name)
        if not left_unit.is_compatible_with(right_unit):
            return False
        magnitude = (1 * left_unit).to(right_unit).magnitude
        return Decimal(str(magnitude)) == Decimal(1)
    except (UndefinedUnitError, ValueError, TypeError):
        return False


def _normalize_unit(name: str) -> str:
    aliases = {
        "m/s2": "meter / second ** 2",
        "m/s^2": "meter / second ** 2",
        "1": "dimensionless",
    }
    return aliases.get(name, name)


def _unit(name: str):
    cached = _UNITS.get(name)
    if cached is None:
        cached = _UREG.Unit(name)
        _UNITS[name] = cached
    return cached
