from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from evidence_calc.cad_bindings import bind_parameters_to_cards
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import delete_plugin_card, register_plugin_card
from evidence_calc.registry import list_cards, list_method_ids, load_card, run_method


def test_margin_of_safety_cs27_625_and_intervals() -> None:
    res = run_method(
        "margin_of_safety",
        {
            "applied_load_n": "10000.000",
            "allowable_load_n": "25000.000",
            "reserve_factor": "1.500",
            "fitting_factor": "1.150",
        },
        include_intervals=True,
    )
    out = res["outputs"]
    assert out["design_load_required_n"] == "17250.000"
    assert Decimal(out["margin_of_safety"]) > Decimal("0.440")
    assert Decimal(out["reserve_factor_achieved"]) > Decimal("2.170")
    assert "margin_of_safety" in res["exact_intervals"]
    # CS-27.625 enforces fitting_factor >= 1.150
    with pytest.raises(AbstainError, match="outside_validity"):
        run_method(
            "margin_of_safety",
            {
                "applied_load_n": "10000.000",
                "allowable_load_n": "25000.000",
                "reserve_factor": "1.500",
                "fitting_factor": "1.100",
            },
        )


def test_column_plate_buckling_euler_and_johnson_regimes() -> None:
    # Slender column -> Euler regime (large L=2500mm, small I)
    slender = run_method(
        "column_plate_buckling",
        {
            "applied_compression_n": "20000",
            "column_length_mm": "2500",
            "end_fixity_k": "1.000",
            "area_mm2": "800",
            "inertia_mm4": "180000",
            "youngs_modulus_mpa": "72000",
            "yield_strength_mpa": "420",
            "poissons_ratio": "0.330",
            "plate_width_b_mm": "40",
            "plate_thickness_t_mm": "4",
            "plate_buckling_coeff_kc": "4.000",
            "crippling_cutoff_mpa": "380",
        },
        include_intervals=True,
    )
    assert slender["diagnostics"]["column_regime"] == "euler"
    assert Decimal(slender["outputs"]["slenderness_ratio"]) > Decimal(
        slender["outputs"]["transition_slenderness"]
    )
    assert "buckling_ms" in slender["exact_intervals"]

    # Stocky strut -> Johnson parabolic transition capped by local plate/crippling
    stocky = run_method(
        "column_plate_buckling",
        {
            "applied_compression_n": "120000",
            "column_length_mm": "350",
            "end_fixity_k": "0.800",
            "area_mm2": "900",
            "inertia_mm4": "450000",
            "youngs_modulus_mpa": "72000",
            "yield_strength_mpa": "420",
            "poissons_ratio": "0.330",
            "plate_width_b_mm": "45",
            "plate_thickness_t_mm": "3",
            "plate_buckling_coeff_kc": "4.000",
            "crippling_cutoff_mpa": "360",
        },
    )
    assert stocky["diagnostics"]["column_regime"] == "johnson"


def test_palmgren_miner_cumulative_fatigue() -> None:
    res = run_method(
        "palmgren_miner_fatigue",
        {
            "cycles_applied": ["10000", "5000", "2000"],
            "cycles_to_failure": ["1000000", "250000", "50000"],
            "scatter_factor": "3.000",
            "damage_limit": "1.000",
        },
        include_intervals=True,
    )
    # raw = 0.01 + 0.02 + 0.04 = 0.07; factored = 0.21; life_factor = 1/0.21 = 4.7619
    assert res["outputs"]["cumulative_damage_raw"] == "0.0700"
    assert res["outputs"]["factored_damage"] == "0.2100"
    assert Decimal(res["outputs"]["fatigue_ms"]) > Decimal("3.7000")
    assert "fatigue_ms" in res["exact_intervals"]


def test_composite_failure_criteria_tsai_wu_and_hashin_compression() -> None:
    # Pure transverse compression half-strength -> exact Hashin RF = 2.000, MS = 1.000
    comp = run_method(
        "composite_failure_criteria",
        {
            "sigma_1_mpa": "0",
            "sigma_2_mpa": "-100",
            "tau_12_mpa": "0",
            "xt_mpa": "1500",
            "xc_mpa": "1200",
            "yt_mpa": "60",
            "yc_mpa": "200",
            "s12_mpa": "50",
            "f12_star": "-0.500",
        },
        include_intervals=True,
    )
    assert comp["diagnostics"]["hashin_governing_mode"] == "matrix_compression"
    assert comp["outputs"]["hashin_reserve_factor"] == "2.000"
    assert comp["outputs"]["hashin_ms"] == "1.000"
    assert comp["outputs"]["tsai_wu_reserve_factor"] == "2.000"
    assert "hashin_ms" in comp["exact_intervals"]

    # Tension + shear fiber dominated
    tens = run_method(
        "composite_failure_criteria",
        {
            "sigma_1_mpa": "750",
            "sigma_2_mpa": "25",
            "tau_12_mpa": "30",
            "xt_mpa": "1500",
            "xc_mpa": "1200",
            "yt_mpa": "60",
            "yc_mpa": "200",
            "s12_mpa": "80",
            "f12_star": "-0.500",
        },
    )
    assert tens["diagnostics"]["hashin_governing_mode"] == "fiber_tension"
    assert Decimal(tens["outputs"]["tsai_wu_ms"]) > Decimal("0")


def test_declarative_plugin_cards_sandboxed_and_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "evidence_home"))
    card = register_plugin_card(
        {
            "method_id": "lug_bearing_check",
            "title": "Aircraft Lug Bearing Stress Plugin Card",
            "quantum": "0.001",
            "input_units": {
                "applied_load_n": "newton",
                "bearing_area_mm2": "millimeter ** 2",
                "fbr_mpa": "megapascal",
            },
            "required": ["applied_load_n", "bearing_area_mm2", "fbr_mpa"],
            "limits": {
                "applied_load_n": {"min_exclusive": "0", "max": "1000000"},
                "bearing_area_mm2": {"min_exclusive": "0", "max": "50000"},
                "fbr_mpa": {"min_exclusive": "0", "max": "2000"},
            },
            "formulas": [
                {"output": "bearing_stress_mpa", "expr": "applied_load_n / bearing_area_mm2"},
                {"output": "bearing_ms", "expr": "(fbr_mpa / bearing_stress_mpa) - 1"},
            ],
        }
    )
    assert card["plugin"] is True
    assert len(card["card_sha256"]) == 64
    assert "lug_bearing_check" in list_method_ids()
    assert any(c["method_id"] == "lug_bearing_check" for c in list_cards())
    loaded = load_card("lug_bearing_check")
    assert loaded["method_id"] == "lug_bearing_check"

    res = run_method(
        "lug_bearing_check",
        {
            "applied_load_n": "20",
            "bearing_area_mm2": "100",
            "fbr_mpa": "500",
            "_input_units": {
                "applied_load_n": "kilonewton",
                "bearing_area_mm2": "millimeter ** 2",
                "fbr_mpa": "megapascal",
            },
        },
        normalize_units=True,
        include_intervals=True,
    )
    # 20 kN = 20000 N -> stress = 200.000 MPa -> MS = 500/200 - 1 = 1.500
    assert res["outputs"]["bearing_stress_mpa"] == "200.000"
    assert res["outputs"]["bearing_ms"] == "1.500"
    assert res["exact_intervals"]["bearing_ms"]["mid"] == "1.500000"

    bound = bind_parameters_to_cards(
        [
            {"name": "applied_load_n", "value": "15000", "unit": "N"},
            {"name": "bearing_area_mm2", "value": "100", "unit": "mm2"},
            {"name": "fbr_mpa", "value": "500", "unit": "MPa"},
        ],
        auto_run=True,
    )
    assert "lug_bearing_check" in bound["ready_methods"]
    assert bound["cards"]["lug_bearing_check"]["execution"]["outputs"]["bearing_ms"] == "2.333"

    # Reject unsafe AST injection and built-in overwrites
    with pytest.raises(AbstainError, match="invalid_plugin_formula"):
        register_plugin_card(
            {
                "method_id": "bad_eval_card",
                "title": "Unsafe Card",
                "required": ["x"],
                "limits": {"x": {"min": "0", "max": "10"}},
                "formulas": [{"output": "y", "expr": "__import__('os').system('echo pwned')"}],
            }
        )
    with pytest.raises(AbstainError, match="builtin_method_protected"):
        register_plugin_card(
            {
                "method_id": "bolt_screen",
                "title": "Hijack Attempt",
                "required": ["x"],
                "limits": {"x": {"min": "0", "max": "10"}},
                "formulas": [{"output": "y", "expr": "x"}],
            }
        )

    assert delete_plugin_card("lug_bearing_check") is True
