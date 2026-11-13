from __future__ import annotations

import pytest
from evidence_kernel.formal import SMTSolverProofEngine, compute_proof_hash


def test_structural_margin_safe_unsat() -> None:
    engine = SMTSolverProofEngine()
    bounds = {
        "area_mm2": ("100.000", "120.000"),
        "shear_force_n": ("1000.000", "2000.000"),
        "tensile_force_n": ("2000.000", "3000.000"),
    }
    allowables = {
        "shear_allowable_mpa": ("150.000"),
        "tensile_allowable_mpa": ("250.000"),
    }
    result = engine.prove_structural_margin(bounds, allowables, safety_factor="1.500")

    assert result.proved is True
    assert result.status == "PROVED_UNSAT"
    assert result.counterexample is None
    assert len(result.proof_hash) == 64
    assert result.solver_stats["check"] == "unsat"


def test_structural_margin_counterexample_sat() -> None:
    engine = SMTSolverProofEngine()
    bounds = {
        "area_mm2": ("50.000", "60.000"),
        "shear_force_n": ("5000.000", "8000.000"),
        "tensile_force_n": ("7000.000", "10000.000"),
    }
    allowables = {
        "shear_allowable_mpa": ("50.000"),
        "tensile_allowable_mpa": ("60.000"),
    }
    result = engine.prove_structural_margin(bounds, allowables, safety_factor="1.500")

    assert result.proved is False
    assert result.status == "COUNTEREXAMPLE_FOUND"
    assert result.counterexample is not None
    assert "area_mm2" in result.counterexample
    assert "shear_force_n" in result.counterexample
    assert "tensile_force_n" in result.counterexample
    assert result.solver_stats["check"] == "sat"


def test_station_equilibrium_safe_unsat() -> None:
    engine = SMTSolverProofEngine()
    bounds = {
        "mass_kg": ("800.000", "1200.000"),
        "load_factor": ("-1.000", "2.500"),
        "cg_x_m": ("-0.200", "0.200"),
    }
    stations = ["-1.000", "-0.300", "0.300", "1.000"]
    # 3 active stations * 15000 N = 45000 N capacity.
    # Max required force: 1200 * 9.807 * 2.5 = 29421 N
    result = engine.prove_station_equilibrium(
        bounds=bounds,
        stations=stations,
        max_station_force_n="15000.000",
        gravity_m_s2="9.807",
        active_stations_min=3,
    )

    assert result.proved is True
    assert result.status == "PROVED_UNSAT"
    assert result.counterexample is None
    assert len(result.proof_hash) == 64


def test_station_equilibrium_counterexample_sat() -> None:
    engine = SMTSolverProofEngine()
    bounds = {
        "mass_kg": ("800.000", "1200.000"),
        "load_factor": ("1.000", "2.500"),
        "cg_x_m": ("-0.200", "0.200"),
    }
    stations = ["-1.000", "-0.300", "0.300", "1.000"]
    # 3 active stations * 5000 N = 15000 N capacity. Max load 29421 N will exceed it!
    result = engine.prove_station_equilibrium(
        bounds=bounds,
        stations=stations,
        max_station_force_n="5000.000",
        gravity_m_s2="9.807",
        active_stations_min=3,
    )

    assert result.proved is False
    assert result.status == "COUNTEREXAMPLE_FOUND"
    assert result.counterexample is not None
    assert "mass_kg" in result.counterexample
    assert "load_factor" in result.counterexample


def test_proof_hash_deterministic() -> None:
    assumptions = {"a": "1", "b": "2"}
    h1 = compute_proof_hash("prop", "PROVED_UNSAT", assumptions, "assert_query", None)
    h2 = compute_proof_hash("prop", "PROVED_UNSAT", assumptions, "assert_query", None)
    assert h1 == h2
    assert len(h1) == 64


def test_unsorted_stations_and_invalid_bounds_rejected() -> None:
    engine = SMTSolverProofEngine()
    bounds = {
        "mass_kg": ("800.000", "1200.000"),
        "load_factor": ("-1.000", "2.500"),
        "cg_x_m": ("-0.200", "0.200"),
    }
    res_unsorted = engine.prove_station_equilibrium(
        bounds=bounds,
        stations=["0.300", "1.000", "-1.000", "-0.300"],
        max_station_force_n="15000.000",
    )
    assert res_unsorted.proved is True

    with pytest.raises(ValueError):
        engine.prove_station_equilibrium(
            bounds=bounds, stations=[], max_station_force_n="15000.000"
        )

    with pytest.raises(ValueError):
        engine.prove_station_equilibrium(
            bounds={**bounds, "mass_kg": ("1200.000", "800.000")},
            stations=["-1.000", "1.000"],
            max_station_force_n="15000.000",
        )

    with pytest.raises(ValueError):
        engine.prove_structural_margin(
            bounds={
                "area_mm2": ("0.000", "10.000"),
                "shear_force_n": ("10.000", "20.000"),
                "tensile_force_n": ("10.000", "20.000"),
            },
            allowables={"shear_allowable_mpa": "150.000", "tensile_allowable_mpa": "250.000"},
        )


def test_hover_power_envelope_unsat_and_counterexample() -> None:
    engine = SMTSolverProofEngine()
    safe = engine.prove_hover_power_envelope(
        thrust_bounds_n=("2000.000", "9800.000"),
        disk_area_m2="10.000",
        air_density_kg_m3="1.225",
        figure_of_merit="0.700",
        max_power_available_kw="350.000",
    )
    assert safe.proved is True
    assert safe.status == "PROVED_UNSAT"
    assert safe.counterexample is None

    exceeded = engine.prove_hover_power_envelope(
        thrust_bounds_n=("2000.000", "15000.000"),
        disk_area_m2="10.000",
        air_density_kg_m3="1.225",
        figure_of_merit="0.700",
        max_power_available_kw="350.000",
    )
    assert exceeded.proved is False
    assert exceeded.status == "COUNTEREXAMPLE_FOUND"
    assert exceeded.counterexample is not None
    assert "thrust_n" in exceeded.counterexample

    with pytest.raises(ValueError):
        engine.prove_hover_power_envelope(
            thrust_bounds_n=("5000.000", "2000.000"),
            disk_area_m2="10.000",
        )
