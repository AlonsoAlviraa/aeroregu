from pathlib import Path

import pytest
from evidence_coverage.grid import calc_inputs_for, default_axes, generate_cells, plus_five_percent
from evidence_coverage.status import StatusError, gap_report, invalidate_mass_shift, set_cell_status
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.ledger import Ledger

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
