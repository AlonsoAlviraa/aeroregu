from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence_calc.bolt_screen import run_bolt_screen
from evidence_calc.errors import AbstainError
from evidence_calc.rigid_body_point_mass import run_rigid_body_point_mass
from evidence_calc.units import check_declared_units

_RUNNERS = {
    "rigid_body_point_mass": run_rigid_body_point_mass,
    "bolt_screen": run_bolt_screen,
}
_CARDS: dict[str, dict[str, Any]] = {}


def cards_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "cards"


def load_card(method_id: str) -> dict[str, Any]:
    cached = _CARDS.get(method_id)
    if cached is not None:
        return cached
    path = cards_dir() / f"{method_id}.json"
    if not path.is_file():
        raise AbstainError("unknown_method")
    card = json.loads(path.read_text(encoding="utf-8"))
    if card.get("method_id") != method_id:
        raise AbstainError("unknown_method")
    _CARDS[method_id] = card
    return card


def run_method(method_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    runner = _RUNNERS.get(method_id)
    if runner is None:
        raise AbstainError("unknown_method")
    card = load_card(method_id)
    check_declared_units(inputs, card)
    numeric_inputs = {key: value for key, value in inputs.items() if key != "_input_units"}
    return runner(numeric_inputs, card)
