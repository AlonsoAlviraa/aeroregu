from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_kernel.canonical import inputs_hash

from evidence_eval.numbers import format_quantum, scale_decimals

SOURCE_TEXT = "Note block for the screening illustration."


def clean_artifact(method_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    ran = run_method(method_id, inputs)
    outputs = ran["outputs"]
    return {
        "method_id": method_id,
        "method_version": ran["method_version"],
        "inputs": copy.deepcopy(inputs),
        "stated_outputs": copy.deepcopy(outputs),
        "inputs_hash": inputs_hash(inputs),
        "source_text": SOURCE_TEXT,
        "quotation": {
            "text": SOURCE_TEXT,
            "span_start": "0",
            "span_end": str(len(SOURCE_TEXT)),
        },
        "coverage_status": "calc",
        "coverage_evidence_hash": inputs_hash(outputs),
    }


def inject(fault_id: str, artifact: dict[str, Any], index: int) -> dict[str, Any]:
    mutated = copy.deepcopy(artifact)
    if fault_id == "unit_scale":
        return _unit_scale(mutated)
    if fault_id == "arithmetic":
        return _arithmetic(mutated)
    if fault_id == "wrong_input":
        return _wrong_input(mutated)
    if fault_id == "sign":
        return _sign(mutated)
    if fault_id == "stale_revision":
        mutated["method_version"] = mutated["method_version"].replace("@1.0.0", "@0.9.0")
        return mutated
    if fault_id == "false_coverage":
        mutated["coverage_evidence_hash"] = "0" * 64
        return mutated
    if fault_id == "broken_hash":
        mutated["inputs_hash"] = "0" * 64
        return mutated
    if fault_id == "bad_span":
        mutated["quotation"] = {
            "text": "not a slice of the source",
            "span_start": "0",
            "span_end": "5",
        }
        return mutated
    if fault_id == "outside_validity":
        return _outside(mutated, index)
    if fault_id == "missing_input":
        return _missing(mutated)
    if fault_id == "bad_citation":
        mutated["requirement_ids"] = ["VTOL.2210"]
        mutated["citation_requirement_id"] = "VTOL.9999"
        return mutated
    if fault_id == "contradictory_requirements":
        mutated["requirement_claims"] = [
            {"id": "VTOL.2210", "status": "calc"},
            {"id": "VTOL.2210", "status": "gap"},
        ]
        return mutated
    if fault_id == "unit_mismatch":
        field = "shear_force_n" if mutated["method_id"] == "bolt_screen" else "mass_kg"
        mutated["inputs"] = dict(mutated["inputs"])
        mutated["inputs"]["_input_units"] = {field: "meter"}
        return mutated
    raise KeyError(fault_id)


def _drop_coverage(artifact: dict[str, Any]) -> None:
    artifact.pop("coverage_status", None)
    artifact.pop("coverage_evidence_hash", None)


def _retarget_hash(artifact: dict[str, Any]) -> None:
    artifact["inputs_hash"] = inputs_hash(artifact["inputs"])


def _unit_scale(artifact: dict[str, Any]) -> dict[str, Any]:
    stated = artifact["stated_outputs"]
    field = "shear_force_n" if artifact["method_id"] == "bolt_screen" else "mass_kg"
    value = Decimal(artifact["inputs"][field])
    artifact["inputs"][field] = format_quantum(value * Decimal("1000"))
    _retarget_hash(artifact)
    artifact["stated_outputs"] = stated
    _drop_coverage(artifact)
    return artifact


def _arithmetic(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact["stated_outputs"] = scale_decimals(artifact["stated_outputs"], Decimal("2"))
    return artifact


def _wrong_input(artifact: dict[str, Any]) -> dict[str, Any]:
    inputs = copy.deepcopy(artifact["inputs"])
    if artifact["method_id"] == "bolt_screen":
        inputs["shear_force_n"] = inputs["tensile_force_n"]
    else:
        inputs["mass_kg"] = inputs["gravity_m_s2"]
    artifact["stated_outputs"] = run_method(artifact["method_id"], inputs)["outputs"]
    _refresh_coverage(artifact)
    return artifact


def _sign(artifact: dict[str, Any]) -> dict[str, Any]:
    inputs = copy.deepcopy(artifact["inputs"])
    field = "load_factor" if "load_factor" in inputs else "tensile_force_n"
    inputs[field] = format_quantum(-Decimal(inputs[field]))
    artifact["stated_outputs"] = run_method(artifact["method_id"], inputs)["outputs"]
    _refresh_coverage(artifact)
    return artifact


def _outside(artifact: dict[str, Any], index: int) -> dict[str, Any]:
    if artifact["method_id"] == "bolt_screen":
        artifact["inputs"]["area_mm2"] = "-1.000"
    else:
        artifact["inputs"]["mass_kg"] = "6000.000" if index % 2 == 0 else "0.500"
    artifact["stated_outputs"] = {"trap_ratio": "1.000"}
    _retarget_hash(artifact)
    _drop_coverage(artifact)
    return artifact


def _missing(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact["method_id"] == "bolt_screen":
        artifact["inputs"].pop("area_mm2", None)
    else:
        artifact["inputs"].pop("mass_kg", None)
    artifact["stated_outputs"] = {"trap_ratio": "1.000"}
    _retarget_hash(artifact)
    _drop_coverage(artifact)
    return artifact


def _refresh_coverage(artifact: dict[str, Any]) -> None:
    try:
        outputs = run_method(artifact["method_id"], artifact["inputs"])["outputs"]
    except AbstainError:
        _drop_coverage(artifact)
        return
    artifact["coverage_status"] = "calc"
    artifact["coverage_evidence_hash"] = inputs_hash(outputs)
