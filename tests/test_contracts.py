import json
from pathlib import Path

import pytest
from evidence_kernel.paths import repo_root
from evidence_kernel.schema import SchemaError, validate_instance


def test_every_schema_loads() -> None:
    folder = repo_root() / "schemas"
    names = sorted(path.name for path in folder.glob("*.json"))
    assert "envelope.schema.json" in names
    assert "agent_turn.schema.json" in names
    assert "criterion_card.schema.json" in names
    for name in names:
        validate_instance(name, _minimal(name))


def test_abstain_envelope_omits_result() -> None:
    good = {
        "sources": [
            {
                "source_id": "s",
                "uri": "https://aeroregu.local/s",
                "content_hash": "assumption",
                "label": "ASSUMPTION",
            }
        ],
        "method_version": "demo@1.0.0",
        "inputs_hash": "a" * 64,
        "confidence": "abstain",
        "abstain": {"reason": "missing_input", "escalate_to": "human_engineer"},
    }
    validate_instance("envelope.schema.json", good)
    bad = dict(good)
    bad["result"] = {"value": "1.000"}
    with pytest.raises(SchemaError):
        validate_instance("envelope.schema.json", bad)


def test_verified_citation_requires_a_hash() -> None:
    with pytest.raises(SchemaError):
        validate_instance(
            "citation.schema.json",
            {
                "source_id": "easa",
                "uri": "https://www.easa.europa.eu/en/downloads/139945/en",
                "content_hash": "not-a-hash",
                "label": "VERIFIED",
            },
        )


def test_criterion_card_requires_an_author() -> None:
    with pytest.raises(SchemaError):
        validate_instance(
            "criterion_card.schema.json",
            {
                "card_id": "c1",
                "requirement_ids": ["REQ-1"],
                "applicability": "synthetic illustration",
                "label": "ASSUMPTION",
                "statement": "A human author is required.",
            },
        )


def test_openapi_lists_health_and_calc() -> None:
    text = (repo_root() / "schemas" / "openapi.yaml").read_text(encoding="utf-8")
    assert "/health:" in text
    assert "/calc/run:" in text
    assert "/ledger/append:" in text
    assert "/coverage/gaps:" in text
    assert "/supervisor/run:" in text


def test_later_product_packages_are_not_built() -> None:
    root = repo_root()
    assert not (root / "packages" / "connectors").exists()
    assert not (root / "packages" / "domain" / "criteria").exists()
    assert not (root / "tools" / "pack").exists()


def _minimal(name: str) -> dict:
    if name == "citation.schema.json":
        return {
            "source_id": "s",
            "uri": "https://aeroregu.local/s",
            "content_hash": "assumption",
            "label": "ASSUMPTION",
        }
    if name == "envelope.schema.json":
        return {
            "sources": [_minimal("citation.schema.json")],
            "method_version": "demo@1.0.0",
            "inputs_hash": "b" * 64,
            "confidence": "deterministic",
            "result": {"status": "ok"},
            "abstain": None,
        }
    if name == "provenance.schema.json":
        return {
            "origin": "synthetic",
            "author": "aeroregu",
            "generator_version": "0.1.0",
            "seed": 20261103,
            "statement": "Invented.",
        }
    if name == "requirement.schema.json":
        return {
            "id": "VTOL.2200",
            "title": None,
            "title_label": "NOT_VERIFIED",
            "source_url": "https://www.easa.europa.eu/en/downloads/139945/en",
            "source_file_hash": "",
            "source_file_hash_label": "NOT_VERIFIED",
            "computable": True,
        }
    if name == "calc_input.schema.json":
        return {"mass_kg": "800.000", "unit_operative": [True, True, True, True]}
    if name == "calc_result.schema.json":
        return {
            "method_id": "bolt_screen",
            "method_version": "bolt_screen@1.0.0",
            "outputs": {"interaction_ratio": "0.200"},
        }
    if name == "ledger_event.schema.json":
        return {
            "event_type": "abstain",
            "tenant_id": "demo",
            "actor_id": "author",
            "created_at": "2026-11-03T18:00:00Z",
            "payload": {"reason": "missing_input"},
            "envelope": {
                "sources": [_minimal("citation.schema.json")],
                "method_version": "demo@1.0.0",
                "inputs_hash": "c" * 64,
                "confidence": "abstain",
                "abstain": {"reason": "missing_input", "escalate_to": "human_engineer"},
            },
        }
    if name == "coverage_cell.schema.json":
        return {
            "cell_id": "cell-1",
            "axes": {"mass_kg": "800.000"},
            "inputs_hash": "d" * 64,
            "status": "gap",
        }
    if name == "benchmark_case.schema.json":
        return {
            "case_id": "dev-note-clean-00",
            "artifact_kind": "note",
            "faults": [],
            "expected": "clean",
            "artifact": {"method_id": "bolt_screen"},
            "provenance": _minimal("provenance.schema.json"),
        }
    if name == "agent_turn.schema.json":
        return {
            "agent_id": "reader",
            "prompt_hash": "e" * 64,
            "input_event_hashes": [],
            "envelope": _minimal("envelope.schema.json"),
        }
    if name == "criterion_card.schema.json":
        return {
            "card_id": "card-1",
            "author_actor": "expert",
            "requirement_ids": ["VTOL.2210"],
            "applicability": "synthetic illustration only",
            "label": "ASSUMPTION",
            "statement": "This card is schema-only in the MVP.",
        }
    raise AssertionError(name)


def test_schema_files_are_json() -> None:
    for path in (repo_root() / "schemas").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
        assert path.stat().st_size > 20
        assert Path(path).suffix == ".json"
