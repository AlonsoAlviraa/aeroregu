from __future__ import annotations

from evidence_calc.cad_bindings import bind_parameters_to_cards


def test_bind_knowledgeware_parameters_with_unit_conversion_and_autorun() -> None:
    params = [
        {
            "name": "shear_force_kn",
            "path": "CATIA\\Loads\\shear_force_kn",
            "value": "2.5",
            "unit": "kN",
        },
        {
            "name": "tensile_force_n",
            "path": "CATIA\\Loads\\tensile_force_n",
            "value": "4000",
            "unit": "N",
        },
        {"name": "area_mm2", "path": "CATIA\\Geom\\area_mm2", "value": "80", "unit": "mm^2"},
        {"name": "shear_allowable_mpa", "path": "MAT\\tau_allow", "value": "250", "unit": "MPa"},
        {"name": "tensile_allowable_mpa", "path": "MAT\\sig_allow", "value": "250", "unit": "MPa"},
        {"name": "thickness_mm", "path": "CATIA\\Geom\\t", "value": "5", "unit": "mm"},
    ]
    formulas = [
        {
            "name": "InteractionFormula",
            "output_param": "interaction_ratio",
            "declared_value": "0.210",
            "unit": "",
        }
    ]
    res = bind_parameters_to_cards(params, formulas=formulas, auto_run=True)
    assert "bolt_screen" in res["ready_methods"]
    bolt = res["cards"]["bolt_screen"]
    assert bolt["ready_to_run"] is True
    assert bolt["execution"]["confidence"] == "deterministic"
    assert bolt["execution"]["outputs"]["shear_stress_mpa"] == "31.250"
    assert bolt["declared_outputs"]["interaction_ratio"] == "0.210"
    assert len(bolt["execution"]["unit_conversions"]) >= 1


def test_bind_detects_ambiguous_duplicate_parameters_fail_closed() -> None:
    params = [
        {"name": "mass_kg", "path": "PartA\\mass_kg", "value": "900", "unit": "kg"},
        {"name": "mass_kg", "path": "PartB\\mass_kg", "value": "950", "unit": "kg"},
        {"name": "load_factor", "path": "Flight\\nz", "value": "2.5", "unit": ""},
        {"name": "cg_x_m", "path": "Mass\\cg_x_m", "value": "0.05", "unit": "m"},
        {"name": "unit_x_m", "path": "Rotors\\x", "value": ["-2", "-1", "1", "2"], "unit": "m"},
        {
            "name": "unit_operative",
            "path": "Rotors\\op",
            "value": [True, True, True, True],
            "unit": "",
        },
        {"name": "gravity_m_s2", "path": "Env\\g", "value": "9.81", "unit": "m/s2"},
    ]
    res = bind_parameters_to_cards(params, auto_run=True)
    rb = res["cards"]["rigid_body_point_mass"]
    assert rb["ready_to_run"] is False
    assert len(rb["ambiguous_conflicts"]) == 1
