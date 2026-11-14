import re
from decimal import ROUND_HALF_EVEN, Decimal

from evidence_calc.errors import AbstainError

_NUMBER = re.compile(r"(?<![A-Za-z_])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")


def quantize(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def reject_ambiguous(value: object) -> None:
    """A scalar field with two candidates is not a number to compute."""
    if isinstance(value, (list, tuple, set)):
        raise AbstainError("ambiguous_input")
    if isinstance(value, str) and len(_NUMBER.findall(value)) > 1:
        raise AbstainError("ambiguous_input")


def as_decimal(text: str) -> Decimal:
    if not isinstance(text, str):
        raise TypeError("physical quantities must be decimal strings")
    return Decimal(text)


def format_quantum(value: Decimal, quantum: Decimal) -> str:
    return format(quantize(value, quantum), "f")


def parse_limited_decimal(
    text: object,
    limit: dict[str, str],
    allow_zero_special: bool = False,
) -> Decimal:
    """Validate an unambiguous decimal string against card bounds."""
    reject_ambiguous(text)
    if not isinstance(text, str):
        raise AbstainError("outside_validity")
    try:
        value = as_decimal(text)
    except Exception as exc:
        raise AbstainError("outside_validity") from exc
    if not value.is_finite():
        raise AbstainError("outside_validity")
    if allow_zero_special and value == 0:
        return value
    if "min" in limit and value < Decimal(limit["min"]):
        raise AbstainError("outside_validity")
    if "min_exclusive" in limit and value <= Decimal(limit["min_exclusive"]):
        raise AbstainError("outside_validity")
    if "max" in limit and value > Decimal(limit["max"]):
        raise AbstainError("outside_validity")
    if "max_exclusive" in limit and value >= Decimal(limit["max_exclusive"]):
        raise AbstainError("outside_validity")
    return value
