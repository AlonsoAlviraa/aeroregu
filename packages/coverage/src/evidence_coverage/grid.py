from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import product
from typing import Any

from evidence_kernel.canonical import inputs_hash

QUANTUM = Decimal("0.001")


@dataclass(frozen=True)
class Cell:
    cell_id: str
    axes: dict[str, str]

    def inputs_hash(self, calc_inputs: dict[str, Any]) -> str:
        return inputs_hash(calc_inputs)


def default_axes() -> dict[str, list[str]]:
    """ASSUMPTION: three stations on mass, cg, and load factor, plus five unit states.

    Altitude is not an axis. rigid_body_point_mass does not use it.
    """

    return {
        "mass_kg": ["800.000", "900.000", "1200.000"],
        "cg_x_m": ["-0.200", "0.000", "0.200"],
        "load_factor": ["1.000", "-1.000", "2.500"],
        "failed_unit": ["none", "0", "1", "2", "3"],
    }


def generate_cells(axes: dict[str, list[str]] | None = None) -> list[Cell]:
    chosen = axes or default_axes()
    keys = ("mass_kg", "cg_x_m", "load_factor", "failed_unit")
    cells: list[Cell] = []
    values = [chosen[key] for key in keys]
    for combo in product(*values):
        point = dict(zip(keys, combo, strict=True))
        cell_id = (
            f"m{point['mass_kg']}-cg{point['cg_x_m']}"
            f"-lf{point['load_factor']}-u{point['failed_unit']}"
        )
        cells.append(Cell(cell_id, point))
    return cells


def calc_inputs_for(cell: Cell) -> dict[str, Any]:
    operative = [True, True, True, True]
    failed = cell.axes["failed_unit"]
    if failed != "none":
        operative[int(failed)] = False
    return {
        "mass_kg": cell.axes["mass_kg"],
        "gravity_m_s2": "9.810",
        "load_factor": cell.axes["load_factor"],
        "cg_x_m": cell.axes["cg_x_m"],
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": operative,
    }


def plus_five_percent(mass: str) -> str:
    shifted = (Decimal(mass) * Decimal("1.05")).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(shifted, "f")
