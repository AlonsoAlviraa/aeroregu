import re
from decimal import ROUND_HALF_EVEN, Decimal

from evidence_calc.errors import AbstainError

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


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
    if not isinstance(text, str):
        raise TypeError("physical quantities must be decimal strings")
    return Decimal(text)


def format_quantum(value: Decimal, quantum: Decimal) -> str:
    return format(quantize(value, quantum), "f")
