"""Naive baseline: trust the stated number. Abstain only when a required input is missing.

This module must not call the calculation registry. A recall above zero on a
deterministic fault means the baseline stopped being naive.
"""

from __future__ import annotations

from typing import Any

from evidence_calc.registry import load_card


def naive_assess(artifact: dict[str, Any]) -> dict[str, Any]:
    method_id = str(artifact.get("method_id") or "")
    inputs = artifact.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
    required: list[str] = []
    if method_id:
        card = load_card(method_id)
        required = list(card.get("required") or card.get("inputs") or [])
    missing = any(key not in inputs or inputs[key] in (None, "") for key in required)
    if missing or not method_id:
        return {"verdict": "abstain", "envelope": {"confidence": "abstain"}}
    return {"verdict": "clean", "envelope": {"confidence": "draft"}}
