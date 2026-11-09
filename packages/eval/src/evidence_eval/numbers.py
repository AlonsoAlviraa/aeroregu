from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

QUANTUM = Decimal("0.001")
DECIMAL = re.compile(r"^-?\d+\.\d+$")


def format_quantum(value: Decimal) -> str:
    return format(value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def scale_decimals(value: Any, factor: Decimal) -> Any:
    if isinstance(value, str) and DECIMAL.fullmatch(value):
        return format_quantum(Decimal(value) * factor)
    if isinstance(value, list):
        return [scale_decimals(item, factor) for item in value]
    if isinstance(value, dict):
        return {key: scale_decimals(item, factor) for key, item in value.items()}
    return value
