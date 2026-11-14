from pathlib import Path

import pytest
from evidence_coverage.dossier import (
    active_calc_records,
    build_enterprise_dossier,
    export_oscal_sar,
    export_strictdoc,
)
from evidence_coverage.grid import calc_inputs_for, default_axes, generate_cells, plus_five_percent
from evidence_coverage.status import StatusError, gap_report, invalidate_mass_shift, set_cell_status
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

USED_CELL_COUNT = 3 * 3 * 3 * 5


def test_default_grid_keeps_mass_cg_load_factor_and_failed_unit() -> None:
    axes = default_axes()
    assert list(axes) == ["mass_kg", "cg_x_m", "load_factor", "failed_unit"]
    assert axes["mass_kg"] == ["800.000", "900.000", "1200.000"]
    assert axes["cg_x_m"] == ["-0.200", "0.000", "0.200"]
    assert axes["load_factor"] == ["1.000", "-1.000", "2.500"]
    assert axes["failed_unit"] == ["none", "0", "1", "2", "3"]
    cells = generate_cells()
    assert len(cells) == USED_CELL_COUNT
    assert len({cell.cell_id for cell in cells}) == USED_CELL_COUNT
    assert "altitude_m" not in calc_inputs_for(cells[0])


def test_missing_cell_is_a_gap(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    report = gap_report(ledger.events())
    assert report["gap_count"] == str(USED_CELL_COUNT)
    assert report["calc_count"] == "0"
    assert len(report["gaps"]) == USED_CELL_COUNT


def test_calc_status_and_mass_shift(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    cell = generate_cells()[0]
    set_cell_status(
        ledger,
        cell=cell,
        status="calc",
        actor_id="reviewer",
        actor_role="human",
        created_at="2026-11-03T18:00:00Z",
        evidence_event_hash="a" * 64,
    )
    report = gap_report(ledger.events())
    assert report["calc_count"] == "1"
    assert report["gap_count"] == str(USED_CELL_COUNT - 1)
    inputs = calc_inputs_for(cell)
    invalidate_mass_shift(
        ledger,
        [{"cell_id": cell.cell_id, "inputs": inputs, "inputs_hash": inputs_hash(inputs)}],
        actor_id="author",
        created_at="2026-11-03T18:01:00Z",
    )
    assert gap_report(ledger.events())["calc_count"] == "0"
    assert plus_five_percent("800.000") == "840.000"
    shifted = dict(inputs)
    shifted["mass_kg"] = "840.000"
    assert inputs_hash(shifted) != inputs_hash(inputs)


def test_not_in_envelope_requires_a_human(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    cell = generate_cells()[1]
    with pytest.raises(StatusError):
        set_cell_status(
            ledger,
            cell=cell,
            status="not_in_envelope",
            actor_id="envelope_critic",
            actor_role="agent",
            created_at="2026-11-03T18:00:00Z",
        )
    set_cell_status(
        ledger,
        cell=cell,
        status="not_in_envelope",
        actor_id="reviewer",
        actor_role="human",
        created_at="2026-11-03T18:00:00Z",
    )
    report = gap_report(ledger.events())
    assert cell.cell_id in report["not_in_envelope"]
    assert cell.cell_id not in report["gaps"]


def test_enterprise_dossier_lineage_and_delta_reverification(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "dossier.sqlite3", "demo")
    cell = generate_cells()[0]
    ev_hash = set_cell_status(
        ledger,
        cell=cell,
        status="calc",
        actor_id="author",
        actor_role="human",
        created_at="2026-11-03T18:00:00Z",
        evidence_event_hash="a" * 64,
    )
    signoff_env = make_envelope(
        sources=[project_source("reviewer", "https://aeroregu.local/reviewer", "ASSUMPTION")],
        method_version="human_signoff@1.0.0",
        inputs={"target_event_hash": ev_hash},
        confidence="quoted",
        result={"statement": "reviewed this event"},
    )
    signoff_hash = record(
        ledger,
        {
            "event_type": "human_signoff",
            "tenant_id": "demo",
            "actor_id": "reviewer",
            "created_at": "2026-11-03T18:01:00Z",
            "payload": {
                "actor_id": "reviewer",
                "statement": "reviewed this event",
                "target_event_hash": ev_hash,
            },
            "envelope": signoff_env,
        },
    )

    dossier_before = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    assert len(dossier_before["dossier_hash"]) == 64
    assert dossier_before["delta_reverification_manifest"]["requires_reverification"] is False
    assert dossier_before["human_signoffs"][0]["status"] == "active"

    records = active_calc_records(ledger.events())
    assert len(records) == 1
    invalidate_mass_shift(
        ledger,
        records,
        actor_id="author",
        created_at="2026-11-03T18:02:00Z",
    )

    dossier_after = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    assert dossier_after["dossier_hash"] != dossier_before["dossier_hash"]
    manifest = dossier_after["delta_reverification_manifest"]
    assert manifest["requires_reverification"] is True
    assert manifest["stale_cells_requiring_rerun"] == [cell.cell_id]
    assert manifest["stale_signoffs"] == [signoff_hash]
    assert dossier_after["human_signoffs"][0]["status"] == "superseded_by_invalidation"


def test_export_strictdoc_and_oscal_sar(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "export.sqlite3", "demo")
    cell = generate_cells()[0]
    set_cell_status(
        ledger,
        cell=cell,
        status="calc",
        actor_id="author",
        actor_role="human",
        created_at="2026-11-03T18:00:00Z",
        evidence_event_hash="e" * 64,
    )
    dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())

    sdoc_text = export_strictdoc(dossier)
    assert "[DOCUMENT]" in sdoc_text
    assert "TITLE: Airworthiness & Evidence Traceability Matrix" in sdoc_text
    assert "REQ_PREFIX: REQ-AERO-" in sdoc_text
    assert "UID: CELL-" in sdoc_text
    assert "STATUS: Validated" in sdoc_text
    assert "CS-27.301" in sdoc_text

    oscal_data = export_oscal_sar(dossier)
    sar = oscal_data["assessment-results"]
    assert sar["metadata"]["oscal-version"] == "1.1.2"
    assert sar["metadata"]["title"] == "AeroRegu Airworthiness Assessment Results (SAR)"
    res = sar["results"][0]
    assert res["props"][0]["name"] == "dossier_hash"
    assert res["props"][0]["value"] == dossier["dossier_hash"]
    assert res["findings"][0]["target"]["status"]["state"] == "satisfied"
    assert len(res["observations"]) == len(dossier["cell_lineage"]) + 1

    records = active_calc_records(ledger.events())
    invalidate_mass_shift(
        ledger,
        records,
        actor_id="author",
        created_at="2026-11-03T18:02:00Z",
    )
    stale_dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    stale_sdoc = export_strictdoc(stale_dossier)
    assert "STATUS: Stale" in stale_sdoc

    stale_oscal = export_oscal_sar(stale_dossier)
    stale_res = stale_oscal["assessment-results"]["results"][0]
    assert stale_res["findings"][0]["target"]["status"]["state"] == "not-satisfied"
    assert export_strictdoc(dossier) == sdoc_text
    assert export_oscal_sar(dossier) == oscal_data


def test_list_cells_sweep_and_recorded_requirements_in_dossier(tmp_path: Path) -> None:
    from evidence_coverage.status import list_cells_with_status, run_coverage_sweep

    ledger = Ledger(tmp_path / "sweep.sqlite3", "demo")
    ledger.ensure_actor("author", "human", "author-local")
    subset = generate_cells()[:4]

    initial = list_cells_with_status(ledger.events(), cells=subset)
    assert len(initial) == 4
    assert all(row["status"] == "gap" for row in initial)

    sweep = run_coverage_sweep(
        ledger,
        actor_id="author",
        created_at="2026-11-12T12:00:00Z",
        target_status="gap",
        limit=2,
        cells=subset,
    )
    assert sweep["processed_count"] == "2"
    assert len(sweep["cell_ids"]) == 2

    calc_only = list_cells_with_status(ledger.events(), status_filter="calc", cells=subset)
    assert len(calc_only) == 2

    req_env = make_envelope(
        sources=[project_source("doc-1", "https://aeroregu.local/doc", "ASSUMPTION")],
        method_version="ingest@1.0.0",
        inputs={"span_start": 0, "span_end": 18},
        confidence="deterministic",
        result={"id": "VTOL.2210", "title_label": "VERIFIED"},
    )
    record(
        ledger,
        {
            "event_type": "requirement_recorded",
            "tenant_id": "demo",
            "actor_id": "author",
            "created_at": "2026-11-12T12:01:00Z",
            "payload": {
                "id": "VTOL.2210",
                "title": "Design loads",
                "title_label": "VERIFIED",
                "span_start": 0,
                "span_end": 18,
                "source_hash": "a" * 64,
            },
            "envelope": req_env,
        },
    )
    dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    assert len(dossier["recorded_requirements"]) == 1
    assert dossier["recorded_requirements"][0]["id"] == "VTOL.2210"
    sdoc = export_strictdoc(dossier)
    assert "Ingested Document Requirement Spans" in sdoc
    assert "INGEST-001-VTOL.2210" in sdoc


def test_export_strictdoc_sanitizes_injection_and_newlines(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "sanitize.sqlite3", "demo")
    cell = generate_cells()[0]
    ev_hash = set_cell_status(
        ledger,
        cell=cell,
        status="calc",
        actor_id="author",
        actor_role="human",
        created_at="2026-11-03T18:00:00Z",
        evidence_event_hash="e" * 64,
    )

    # Injected signoff with directives and newlines
    signoff_env = make_envelope(
        sources=[project_source("reviewer", "https://aeroregu.local/reviewer", "ASSUMPTION")],
        method_version="human_signoff@1.0.0",
        inputs={"target_event_hash": ev_hash},
        confidence="quoted",
        result={"statement": "ok"},
    )
    record(
        ledger,
        {
            "event_type": "human_signoff",
            "tenant_id": "demo",
            "actor_id": "reviewer\nINJECTED_HEADER: True",
            "created_at": "2026-11-03T18:01:00Z",
            "payload": {
                "actor_id": "reviewer\nINJECTED_HEADER: True",
                "statement": "reviewed this event",
                "target_event_hash": ev_hash,
            },
            "envelope": signoff_env,
        },
    )

    # Injected requirement with directive tags and control newlines
    req_env = make_envelope(
        sources=[project_source("doc-1", "https://aeroregu.local/doc", "ASSUMPTION")],
        method_version="ingest@1.0.0",
        inputs={"span_start": 0, "span_end": 20},
        confidence="deterministic",
        result={"id": "VTOL.2299", "title_label": "VERIFIED"},
    )
    record(
        ledger,
        {
            "event_type": "requirement_recorded",
            "tenant_id": "demo",
            "actor_id": "author",
            "created_at": "2026-11-03T18:02:00Z",
            "payload": {
                "id": "VTOL.2299\nTITLE: InjectedTitle",
                "title": "Design limits",
                "title_label": "VERIFIED",
                "span_start": 0,
                "span_end": 20,
                "quotation": (
                    "Text [SECTION]\nTITLE: Malicious Section\n[/SECTION] and "
                    "[REQUIREMENT]\nUID: FORGED-01\n[/REQUIREMENT] and [RELATIONS]"
                ),
                "source_hash": "b" * 64,
            },
            "envelope": req_env,
        },
    )

    dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    sdoc = export_strictdoc(dossier)

    # Directives in untrusted values must be escaped
    assert "\\[REQUIREMENT\\]" in sdoc
    assert "\\[/REQUIREMENT\\]" in sdoc
    assert "\\[SECTION\\]" in sdoc
    assert "\\[/SECTION\\]" in sdoc
    assert "\\[RELATIONS\\]" in sdoc

    # No unescaped forged requirement from the payload
    assert "[REQUIREMENT]\nUID: FORGED-01" not in sdoc

    # Check that headers do not have uncollapsed newlines
    for line in sdoc.splitlines():
        if line.startswith(("UID:", "TITLE:", "COMMENT:")):
            assert "\n" not in line
            assert "\r" not in line
