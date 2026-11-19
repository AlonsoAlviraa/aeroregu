from __future__ import annotations

import hashlib
from pathlib import Path

from evidence_coverage.grid import generate_cells
from evidence_coverage.nafems_audit import (
    audit_bdf_vs_report_properties,
    audit_regulatory_subcase_coverage,
    audit_rotor_harmonic_separation,
    build_nafems_manifest,
    diff_bdf_revisions_and_invalidate,
)
from evidence_coverage.status import list_cells_with_status, set_cell_status
from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06
from evidence_kernel.ledger import Ledger

BDF_REV_A = b"""$ UNITS: MM_T_N_MPA
SOL 101
CEND
SUBCASE 1
  LABEL = LIMIT MANEUVER 2.5G
  LOAD = 101
SUBCASE 2
  LABEL = ULTIMATE HARD LANDING
  LOAD = 102
BEGIN BULK
GRID    1       0       0.0     0.0     0.0
PSHELL  100     1       3.0
PSHELL  101     1       4.5
MAT1    1       71000.  27000.  0.33
FORCE   101     1       0       5000.   0.0     0.0     1.0
CONM2   50      1       0       950.0   0.0     0.0     0.0
ENDDATA
"""

BDF_REV_B = b"""$ UNITS: MM_T_N_MPA
SOL 101
CEND
SUBCASE 1
  LABEL = LIMIT MANEUVER 2.5G
  LOAD = 101
SUBCASE 2
  LABEL = ULTIMATE HARD LANDING
  LOAD = 102
SUBCASE 3
  LABEL = CRASH 20G FORWARD
  LOAD = 103
BEGIN BULK
GRID    1       0       0.0     0.0     0.0
PSHELL  100     1       2.5
PSHELL  101     1       4.5
MAT1    1       71000.  27000.  0.33
FORCE   101     1       0       5000.   0.0     0.0     1.0
CONM2   50      1       0       980.0   0.0     0.0     0.0
ENDDATA
"""

BDF_NO_UNITS = b"""BEGIN BULK
PSHELL  100     1       2.5
ENDDATA
"""

F06_MODAL_VIOLATION = b"""1    NASTRAN SOL 103 NORMAL MODES
                                              R E A L   E I G E N V A L U E S
   MODE    EXTRACTION      EIGENVALUE           RADIANS             CYCLES
    NO.       ORDER
        1         1        3.947842E+03        6.283185E+01        2.050000E+01
        2         2        1.579137E+04        1.256637E+02        3.500000E+01
                     M O D A L   E F F E C T I V E   M A S S   F R A C T I O N
   MODE    FREQ(HZ)     T1            T2            T3
        1  20.50000    0.010         0.005         0.002
        2  35.00000    0.550         0.100         0.050
"""


def test_nafems_manifest_requires_unit_system_when_strict() -> None:
    bdf_h = hashlib.sha256(BDF_NO_UNITS).hexdigest()
    bdf_no_u = parse_nastran_bdf(BDF_NO_UNITS, bdf_h)
    strict = build_nafems_manifest(bdf_parsed=bdf_no_u, bdf_hash=bdf_h, require_unit_system=True)
    assert strict["abstain"] is True
    assert strict["abstain_reason"] == "bdf_unit_system_unspecified"
    assert strict["nafems_sanity_checks"]["all_passed"] is False


def test_nafems_manifest_and_structured_table_drift_detection() -> None:
    bdf_h = hashlib.sha256(BDF_REV_B).hexdigest()
    bdf = parse_nastran_bdf(BDF_REV_B, bdf_h)
    manifest = build_nafems_manifest(
        bdf_parsed=bdf,
        bdf_hash=bdf_h,
        report_hash="abc123",
        require_unit_system=True,
    )
    assert manifest["abstain"] is False
    assert manifest["unit_system"] == "MM_T_N_MPA"
    assert manifest["schema"] == "nafems_vv_manifest@1.0.0"
    assert manifest["model_summary"]["pshell_count"] == 2
    assert manifest["model_summary"]["subcase_count"] == 3
    assert len(manifest["manifest_sha256"]) == 64

    # Structured PDF table_rows block (PID 100: 3.0 vs 2.5 mm; PID 101: 4.5 mm match)
    drift = audit_bdf_vs_report_properties(
        bdf_parsed=bdf,
        report_blocks=[
            {
                "block_kind": "table",
                "page_no": 4,
                "bbox": [40.0, 120.0, 520.0, 220.0],
                "text": "PID | Panel | Thickness (mm) | MS_min",
                "table_rows": [
                    ["PID", "Panel", "Thickness (mm)", "MS_min"],
                    ["100", "Tailboom Skin", "3.0", "0.18"],
                    ["101", "MGB Frame", "4.5", "0.42"],
                ],
            }
        ],
    )
    assert drift["consistent"] is False
    assert drift["checked_property_count"] == 2
    assert drift["discrepancy_count"] == 1
    disc = drift["discrepancies"][0]
    assert disc["category"] == "property_thickness_drift"
    assert disc["pid"] == "100"
    assert disc["delta_mm"] == "0.5"
    assert disc["provenance"]["source"] == "table_rows"
    assert disc["provenance"]["page_no"] == 4


def test_regulatory_subcase_completeness_catches_missing_crash_case() -> None:
    bdf_a = parse_nastran_bdf(BDF_REV_A, hashlib.sha256(BDF_REV_A).hexdigest())
    families = [
        {"family_id": "limit_maneuver", "regulation_ref": "CS 29.337", "keywords": ["maneuver"]},
        {"family_id": "hard_landing", "regulation_ref": "CS 29.473", "keywords": ["landing"]},
        {"family_id": "crash_20g", "regulation_ref": "CS 29.561", "keywords": ["crash", "20g"]},
    ]
    res_a = audit_regulatory_subcase_coverage(bdf_parsed=bdf_a, required_load_families=families)
    assert res_a["complete"] is False
    assert res_a["missing_count"] == 1
    assert res_a["missing"][0]["family_id"] == "crash_20g"

    bdf_b = parse_nastran_bdf(BDF_REV_B, hashlib.sha256(BDF_REV_B).hexdigest())
    res_b = audit_regulatory_subcase_coverage(bdf_parsed=bdf_b, required_load_families=families)
    assert res_b["complete"] is True
    assert res_b["covered_count"] == 3


def test_rotor_harmonic_separation_with_effective_mass_filter() -> None:
    f06 = parse_nastran_f06(F06_MODAL_VIOLATION, hashlib.sha256(F06_MODAL_VIOLATION).hexdigest())
    # Without effective mass filter, mode 1 (20.5 Hz) violates 4P (20.0 Hz)
    res_all = audit_rotor_harmonic_separation(
        f06_parsed=f06,
        rotor_rpm="300",
        blade_count=4,
        guard_band_pct="10.0",
    )
    assert res_all["clear"] is False
    assert res_all["violation_count"] == 1
    assert res_all["violations"][0]["harmonic"] == "4P"

    # With min_effective_mass_frac=0.05, spurious local mode 1 (0.010) is ignored
    res_filtered = audit_rotor_harmonic_separation(
        f06_parsed=f06,
        rotor_rpm="300",
        blade_count=4,
        guard_band_pct="10.0",
        min_effective_mass_frac="0.05",
    )
    assert res_filtered["clear"] is True
    assert res_filtered["ignored_local_modes"] == ["1"]


def test_bdf_revision_diff_invalidates_all_calc_cells_without_cap(tmp_path: Path) -> None:
    bdf_a = parse_nastran_bdf(BDF_REV_A, hashlib.sha256(BDF_REV_A).hexdigest())
    bdf_b = parse_nastran_bdf(BDF_REV_B, hashlib.sha256(BDF_REV_B).hexdigest())
    ledger = Ledger(tmp_path / "impact.sqlite3", "demo")

    # Seed 12 calculated cells (> old cap of 8) to ensure ALL are invalidated
    cells = generate_cells()[:12]
    for idx, cell in enumerate(cells):
        set_cell_status(
            ledger,
            cell=cell,
            status="calc",
            actor_id="author",
            actor_role="human",
            created_at=f"2026-11-19T10:00:{idx:02d}Z",
        )

    diff = diff_bdf_revisions_and_invalidate(rev_a_bdf=bdf_a, rev_b_bdf=bdf_b, ledger=ledger)
    assert diff["has_structural_impact"] is True
    assert diff["changed_pshells"] == [{"pid": "100", "rev_a_t": "3", "rev_b_t": "2.5"}]
    assert diff["added_subcases"] == ["3"]
    assert diff["mass_delta_kg"] == "30"
    assert len(diff["invalidated_cell_ids"]) == 12
    statuses = list_cells_with_status(ledger.events(), cells=cells)
    assert all(s["stale"] is True and int(s["invalidation_count"]) == 1 for s in statuses)
