"""Universal SMT formal verification dispatcher and method catalog defaults."""

from __future__ import annotations

import ast
import math
from decimal import Decimal
from typing import Any

import z3
from evidence_kernel.formal import SMTSolverProofEngine

_PI_STR = "3.141592653589793"

METHOD_FAMILIES: dict[str, str] = {
    # Flight Envelope & Mass Properties
    "rigid_body_point_mass": "flight_envelope",
    "hover_power_screen": "flight_envelope",
    # Classical Structural Sizing & Margins
    "margin_of_safety": "structural_sizing",
    "column_plate_buckling": "structural_sizing",
    "bolt_screen": "fasteners_joints",
    # Fatigue & Fracture (Stress Manual 1..5)
    "palmgren_miner_fatigue": "fatigue_fracture",
    "nasgro_paris_crack_growth": "fatigue_fracture",
    "goodman_haigh_mean_stress": "fatigue_fracture",
    "neuber_notch_plasticity": "fatigue_fracture",
    "net_section_yielding_fracture": "fatigue_fracture",
    "rainflow_spectrum_damage": "fatigue_fracture",
    # Composites & CMH-17 (Stress Manual 6..11)
    "composite_failure_criteria": "composites_cmh17",
    "tsai_wu_ply_failure": "composites_cmh17",
    "hashin_composite_modes": "composites_cmh17",
    "puck_interfiber_fracture": "composites_cmh17",
    "open_hole_tension_oht": "composites_cmh17",
    "open_hole_compression_ohc": "composites_cmh17",
    "compression_after_impact_cai": "composites_cmh17",
    # Joints, Fasteners & Lugs (Stress Manual 12..18)
    "huth_fastener_flexibility": "fasteners_joints",
    "bearing_bypass_interaction": "fasteners_joints",
    "eccentric_bolt_group_cg": "fasteners_joints",
    "lug_axial_transverse_interaction": "fasteners_joints",
    "bolt_preload_thermal_relaxation": "fasteners_joints",
    "fastener_pull_through_composite": "fasteners_joints",
    "adhesive_single_lap_volkersen": "fasteners_joints",
    # Thin-Walled Stability & Section Buckling (Stress Manual 19..25)
    "johnson_euler_column": "thin_walled_stability",
    "needham_crippling_section": "thin_walled_stability",
    "shear_web_diagonal_tension": "thin_walled_stability",
    "curved_panel_compression_shear": "thin_walled_stability",
    "inter_rivet_buckling": "thin_walled_stability",
    "thin_walled_bredt_batho_torsion": "thin_walled_stability",
    "sandwich_core_shear_wrinkling": "thin_walled_stability",
    # Rotorcraft & Composite Stress Office Extensions (Sprint 2)
    "clt_laminate_abd_stiffness": "composites_cmh17",
    "rotor_blade_centrifugal_bending": "rotorcraft_dynamics",
    "ground_resonance_coleman_screen": "rotorcraft_dynamics",
    "cs29_crashworthiness_561_562_load": "rotorcraft_dynamics",
    "multirow_bolt_load_distribution": "fasteners_joints",
    # Rotorcraft & Composite Stress Office Extensions (Sprint 3)
    "larc04_composite_failure": "composites_cmh17",
    "cs29_bird_strike_penetration_screen": "rotorcraft_dynamics",
    "campbell_rotor_harmonic_clearance": "rotorcraft_dynamics",
    "tailboom_boxbeam_combined_stress": "thin_walled_stability",
    "statistical_ab_basis_tolerance_bound": "composites_cmh17",
    # Stress Manual Extensions (Sprint 4 — complete 52-card catalog)
    "bolt_prying_combined_tension_shear": "fasteners_joints",
    "goland_reissner_adhesive_peel_shear": "fasteners_joints",
    "orthotropic_composite_plate_buckling": "composites_cmh17",
    "skin_stringer_crippling_interaction": "thin_walled_stability",
    "walker_mean_stress_crack_growth": "fatigue_fracture",
}

METHOD_DEFAULT_INPUTS: dict[str, dict[str, Any]] = {
    "rigid_body_point_mass": {
        "mass_kg": "1000.000",
        "gravity_m_s2": "9.810",
        "load_factor": "1.000",
        "cg_x_m": "0.000",
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": [True, True, True, True],
    },
    "bolt_screen": {
        "shear_force_n": "1000.000",
        "tensile_force_n": "2000.000",
        "area_mm2": "100.000",
        "shear_allowable_mpa": "150.000",
        "tensile_allowable_mpa": "250.000",
    },
    "hover_power_screen": {
        "thrust_n": "10000.000",
        "disk_area_m2": "10.000",
        "air_density_kg_m3": "1.225",
        "figure_of_merit": "0.700",
        "power_available_kw": "350.000",
    },
    "margin_of_safety": {
        "applied_load_n": "10000.000",
        "allowable_load_n": "20000.000",
        "reserve_factor": "1.000",
        "fitting_factor": "1.150",
    },
    "column_plate_buckling": {
        "applied_compression_n": "25000.000",
        "column_length_mm": "400.000",
        "end_fixity_k": "1.000",
        "area_mm2": "620.000",
        "inertia_mm4": "190000.000",
        "youngs_modulus_mpa": "71700.000",
        "yield_strength_mpa": "441.000",
        "poissons_ratio": "0.330",
        "plate_width_b_mm": "45.000",
        "plate_thickness_t_mm": "3.200",
        "plate_buckling_coeff_kc": "4.000",
        "crippling_cutoff_mpa": "400.000",
    },
    "palmgren_miner_fatigue": {
        "cycles_applied": ["15000.000", "5000.000"],
        "cycles_to_failure": ["250000.000", "100000.000"],
        "scatter_factor": "4.000",
        "damage_limit": "1.000",
    },
    "composite_failure_criteria": {
        "sigma_1_mpa": "420.000",
        "sigma_2_mpa": "18.000",
        "tau_12_mpa": "24.000",
        "xt_mpa": "2500.000",
        "xc_mpa": "1500.000",
        "yt_mpa": "62.000",
        "yc_mpa": "250.000",
        "s12_mpa": "92.000",
        "f12_star": "-0.500",
    },
    "adhesive_single_lap_volkersen": {
        "tensile_load_n": "12000",
        "overlap_width_mm": "50",
        "overlap_length_mm": "40",
        "adhesive_shear_modulus_mpa": "950",
        "adhesive_thickness_mm": "0.25",
        "adherend_modulus_mpa": "71700",
        "adherend_thickness_mm": "2.5",
        "adhesive_shear_allowable_mpa": "28",
    },
    "bearing_bypass_interaction": {
        "bearing_load_n": "7500",
        "bypass_load_n": "14000",
        "hole_diameter_mm": "6.35",
        "strip_width_mm": "38.1",
        "thickness_mm": "3.2",
        "bearing_allowable_mpa": "745",
        "bypass_oht_allowable_mpa": "360",
    },
    "bolt_preload_thermal_relaxation": {
        "initial_preload_n": "32000",
        "embedment_loss_n": "1500",
        "bolt_cte_per_c": "0.000011",
        "plate_cte_per_c": "0.000023",
        "delta_temp_c": "-75",
        "bolt_stiffness_n_per_mm": "220000",
        "joint_stiffness_n_per_mm": "680000",
        "grip_length_mm": "24",
        "external_tensile_load_n": "8500",
    },
    "compression_after_impact_cai": {
        "applied_compressive_mpa": "165",
        "cai_allowable_bvid_mpa": "285",
        "impact_energy_j": "25",
        "reference_bvid_j": "30",
        "environmental_knockdown": "0.90",
    },
    "curved_panel_compression_shear": {
        "compressive_stress_mpa": "45",
        "shear_stress_mpa": "25",
        "arc_width_mm": "160",
        "skin_thickness_mm": "2.4",
        "radius_curvature_mm": "1800",
        "modulus_mpa": "71700",
        "poisson_nu": "0.33",
    },
    "eccentric_bolt_group_cg": {
        "shear_vx_n": "4200",
        "shear_vy_n": "9600",
        "moment_mz_nmm": "280000",
        "half_spacing_x_mm": "35",
        "half_spacing_y_mm": "25",
        "bolt_shear_allowable_n": "16500",
    },
    "fastener_pull_through_composite": {
        "tensile_load_n": "2800",
        "head_diameter_mm": "12.5",
        "laminate_thickness_mm": "3.6",
        "ilss_allowable_mpa": "62",
        "countersink_knockdown": "0.85",
    },
    "goodman_haigh_mean_stress": {
        "alternating_stress_mpa": "95",
        "mean_stress_mpa": "110",
        "endurance_limit_mpa": "210",
        "ultimate_tensile_mpa": "510",
    },
    "hashin_composite_modes": {
        "sigma_1_mpa": "420",
        "sigma_2_mpa": "24",
        "tau_12_mpa": "32",
        "xt_mpa": "2500",
        "xc_mpa": "1500",
        "yt_mpa": "62",
        "yc_mpa": "250",
        "sl_mpa": "92",
        "st_mpa": "75",
    },
    "huth_fastener_flexibility": {
        "fastener_diameter_mm": "6.35",
        "plate1_thickness_mm": "3.2",
        "plate2_thickness_mm": "4.0",
        "plate1_modulus_mpa": "71700",
        "plate2_modulus_mpa": "71700",
        "fastener_modulus_mpa": "110300",
        "huth_a_exp": "0.6667",
        "huth_b_coef": "4.2",
        "shear_planes_n": "1",
    },
    "inter_rivet_buckling": {
        "compressive_stress_mpa": "185",
        "rivet_pitch_mm": "22",
        "skin_thickness_mm": "2.2",
        "rivet_head_fixity_c": "2.5",
        "tangent_modulus_mpa": "68000",
    },
    "johnson_euler_column": {
        "compressive_load_n": "48000",
        "section_area_mm2": "620",
        "min_inertia_mm4": "190000",
        "column_length_mm": "380",
        "end_fixity_c": "1.0",
        "modulus_mpa": "71700",
        "compressive_yield_mpa": "441",
    },
    "lug_axial_transverse_interaction": {
        "axial_load_n": "14000",
        "transverse_load_n": "5200",
        "axial_allowable_n": "42000",
        "transverse_allowable_n": "28000",
    },
    "nasgro_paris_crack_growth": {
        "initial_crack_mm": "1.27",
        "delta_sigma_mpa": "75",
        "geometry_factor_y": "1.12",
        "fracture_toughness_mpa_sqrt_m": "36",
        "paris_c": "0.00000000018",
        "paris_m": "3.1",
        "required_cycles": "25000",
    },
    "needham_crippling_section": {
        "compressive_load_n": "34000",
        "flange_width_mm": "30",
        "flange_thickness_mm": "2.4",
        "web_width_mm": "55",
        "web_thickness_mm": "2.4",
        "modulus_mpa": "71700",
        "compressive_yield_mpa": "434",
    },
    "net_section_yielding_fracture": {
        "applied_load_n": "68000",
        "plate_width_mm": "140",
        "thickness_mm": "4.0",
        "half_crack_mm": "6.0",
        "yield_strength_mpa": "441",
        "fracture_toughness_mpa_sqrt_m": "36",
    },
    "neuber_notch_plasticity": {
        "nominal_stress_mpa": "195",
        "kt_concentration": "2.4",
        "modulus_mpa": "71700",
        "cyclic_strength_coeff_mpa": "890",
        "cyclic_hardening_exp": "0.11",
        "cyclic_yield_mpa": "460",
    },
    "open_hole_compression_ohc": {
        "applied_compressive_mpa": "190",
        "ohc_allowable_rtd_mpa": "320",
        "etw_knockdown": "0.85",
        "hole_diameter_mm": "6.35",
    },
    "open_hole_tension_oht": {
        "applied_far_field_mpa": "210",
        "oht_allowable_rtd_mpa": "410",
        "hole_diameter_mm": "6.35",
        "strip_width_mm": "38.1",
        "environmental_knockdown": "0.92",
    },
    "puck_interfiber_fracture": {
        "sigma_2_mpa": "18",
        "tau_12_mpa": "28",
        "yt_mpa": "62",
        "yc_mpa": "250",
        "sl_mpa": "92",
    },
    "rainflow_spectrum_damage": {
        "cycles_band1": "40000",
        "allowable_cycles_band1": "1000000",
        "cycles_band2": "12000",
        "allowable_cycles_band2": "250000",
        "cycles_band3": "1500",
        "allowable_cycles_band3": "50000",
        "scatter_factor": "4.0",
    },
    "sandwich_core_shear_wrinkling": {
        "facesheet_stress_mpa": "240",
        "transverse_shear_n_per_mm": "14",
        "facesheet_thickness_mm": "1.2",
        "core_thickness_mm": "18",
        "facesheet_modulus_mpa": "68000",
        "core_compression_modulus_mpa": "310",
        "core_shear_modulus_mpa": "165",
        "core_shear_allowable_mpa": "2.1",
    },
    "shear_web_diagonal_tension": {
        "applied_shear_n": "19500",
        "web_depth_mm": "220",
        "web_thickness_mm": "1.6",
        "stiffener_pitch_mm": "180",
        "modulus_mpa": "72400",
        "web_shear_ultimate_mpa": "269",
    },
    "thin_walled_bredt_batho_torsion": {
        "torque_nmm": "3200000",
        "enclosed_area_mm2": "24000",
        "perimeter_mm": "680",
        "min_wall_thickness_mm": "1.8",
        "shear_modulus_mpa": "27000",
        "shear_allowable_mpa": "269",
    },
    "tsai_wu_ply_failure": {
        "sigma_1_mpa": "450",
        "sigma_2_mpa": "22",
        "tau_12_mpa": "28",
        "xt_mpa": "2500",
        "xc_mpa": "1500",
        "yt_mpa": "62",
        "yc_mpa": "250",
        "s12_mpa": "92",
    },
    "clt_laminate_abd_stiffness": {
        "theta_1_deg": "0",
        "theta_2_deg": "45",
        "theta_3_deg": "-45",
        "theta_4_deg": "90",
        "ply_thickness_mm": "0.250",
        "e1_mpa": "140000",
        "e2_mpa": "10000",
        "g12_mpa": "5000",
        "nu12": "0.300",
        "nx_n_per_mm": "55",
        "ny_n_per_mm": "12",
        "nxy_n_per_mm": "8",
        "mx_n_mm_per_mm": "2",
        "xt_mpa": "2200",
        "yt_mpa": "65",
        "s12_mpa": "85",
    },
    "rotor_blade_centrifugal_bending": {
        "blade_mass_kg": "48",
        "rotor_omega_rad_s": "38",
        "cg_radius_m": "2.600",
        "root_area_mm2": "950",
        "root_section_modulus_mm3": "18500",
        "flap_bending_moment_n_m": "1400",
        "lag_bending_moment_n_m": "650",
        "ultimate_tensile_mpa": "950",
        "endurance_limit_mpa": "310",
        "safety_factor": "1.500",
    },
    "ground_resonance_coleman_screen": {
        "rotor_omega_rad_s": "42",
        "blade_lead_lag_freq_rad_s": "11",
        "fuselage_mode_freq_rad_s": "18",
        "blade_lag_damping_ratio": "0.080",
        "fuselage_damping_ratio": "0.060",
        "mass_coupling_ratio": "0.008",
        "min_damping_margin_factor": "1.250",
    },
    "cs29_crashworthiness_561_562_load": {
        "occupant_seat_mass_kg": "90",
        "delta_v_m_s": "9.100",
        "rise_time_s": "0.045",
        "attachment_bolt_count": "4",
        "bolt_allowable_load_n": "11500",
        "floor_fitting_factor": "1.330",
    },
    "multirow_bolt_load_distribution": {
        "total_applied_load_n": "12000",
        "pitch_mm": "32",
        "width_mm": "48",
        "plate1_thickness_mm": "3.000",
        "plate2_thickness_mm": "3.000",
        "plate1_modulus_mpa": "72000",
        "plate2_modulus_mpa": "72000",
        "bolt_diameter_mm": "6.350",
        "bolt_modulus_mpa": "205000",
        "bearing_allowable_mpa": "720",
    },
    "larc04_composite_failure": {
        "sigma_1_mpa": "-380",
        "sigma_2_mpa": "-42",
        "tau_12_mpa": "28",
        "x_t_mpa": "2200",
        "x_c_mpa": "1350",
        "y_t_mpa": "60",
        "y_c_mpa": "220",
        "s_l_mpa": "85",
        "alpha_0_deg": "53",
        "eta_l": "0.28",
        "g_12_mpa": "4700",
        "phi_0_deg": "1.5",
    },
    "cs29_bird_strike_penetration_screen": {
        "bird_mass_kg": "1.0",
        "impact_velocity_m_s": "75",
        "bird_density_kg_m3": "950",
        "bird_diameter_mm": "120",
        "panel_thickness_mm": "6.5",
        "panel_shear_allowable_mpa": "180",
        "safety_factor": "1.5",
    },
    "campbell_rotor_harmonic_clearance": {
        "omega_min_rpm": "360",
        "omega_max_rpm": "400",
        "blade_count": "4",
        "structural_freq_hz": "38.5",
        "min_clearance_pct": "10",
    },
    "tailboom_boxbeam_combined_stress": {
        "bending_moment_n_m": "18500",
        "torque_n_m": "9200",
        "transverse_shear_n": "14000",
        "box_width_mm": "320",
        "box_height_mm": "420",
        "skin_thickness_mm": "2.2",
        "cap_area_mm2": "340",
        "yield_allowable_mpa": "310",
        "shear_buckling_allowable_mpa": "95",
        "safety_factor": "1.5",
    },
    "statistical_ab_basis_tolerance_bound": {
        "sample_count": "30",
        "sample_mean_mpa": "620",
        "sample_std_mpa": "24",
        "design_stress_mpa": "420",
    },
    "bolt_prying_combined_tension_shear": {
        "applied_tension_n": "8500",
        "applied_shear_n": "6200",
        "applied_bending_n_mm": "12000",
        "prying_lever_a_mm": "22",
        "prying_lever_b_mm": "14",
        "flange_thickness_mm": "8.0",
        "bolt_tensile_allowable_n": "32000",
        "bolt_shear_allowable_n": "21000",
        "bolt_bending_allowable_n_mm": "85000",
        "safety_factor": "1.5",
    },
    "goland_reissner_adhesive_peel_shear": {
        "tensile_load_per_width_n_mm": "75",
        "overlap_length_mm": "30",
        "adherend_thickness_mm": "2.5",
        "adherend_modulus_mpa": "72000",
        "adhesive_thickness_mm": "0.2",
        "adhesive_modulus_mpa": "2600",
        "adhesive_shear_modulus_mpa": "950",
        "peel_allowable_mpa": "32",
        "shear_allowable_mpa": "36",
        "safety_factor": "1.5",
    },
    "orthotropic_composite_plate_buckling": {
        "nx_comp_n_per_mm": "45",
        "ny_comp_n_per_mm": "12",
        "nxy_shear_n_per_mm": "18",
        "plate_length_a_mm": "350",
        "plate_width_b_mm": "180",
        "d11_n_mm": "185000",
        "d22_n_mm": "95000",
        "d12_n_mm": "42000",
        "d66_n_mm": "46000",
        "safety_factor": "1.5",
    },
    "skin_stringer_crippling_interaction": {
        "applied_compression_n": "68000",
        "panel_length_mm": "420",
        "stringer_pitch_mm": "150",
        "skin_thickness_mm": "2.0",
        "stringer_area_mm2": "240",
        "stringer_crippling_mpa": "380",
        "panel_inertia_mm4": "145000",
        "end_fixity_c": "1.5",
        "modulus_mpa": "71700",
        "skin_yield_mpa": "410",
        "safety_factor": "1.5",
    },
    "walker_mean_stress_crack_growth": {
        "initial_crack_a0_mm": "1.27",
        "sigma_max_mpa": "135",
        "stress_ratio_r": "0.1",
        "geometry_factor_beta": "1.12",
        "fracture_toughness_kic_mpa_sqrt_m": "32",
        "walker_c": "2.5e-11",
        "walker_m": "3.1",
        "walker_gamma": "0.7",
        "required_cycles": "20000",
        "scatter_factor": "2.0",
    },
}


def _pair_bounds(val: Any, fallback: tuple[str, str]) -> tuple[str, str]:
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return (str(val[0]), str(val[1]))
    if isinstance(val, (int, float, Decimal, str)) and str(val).strip():
        s = str(val).strip()
        return (s, s)
    return fallback


def _dec_str(x: float) -> str:
    return f"{Decimal(str(x)):.8f}".rstrip("0").rstrip(".") or "0"


def _split_bounds_and_consts(
    merged: dict[str, Any],
    formal_bounds: dict[str, Any],
    scalar_keys: list[str],
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    bounds: dict[str, tuple[str, str]] = {}
    consts: dict[str, str] = {}
    for k in scalar_keys:
        if k in formal_bounds and isinstance(formal_bounds[k], (list, tuple)):
            lo, hi = _pair_bounds(formal_bounds[k], ("0", "0"))
            bounds[k] = (lo, hi)
        else:
            val_s = str(merged[k])
            if k in formal_bounds or not bounds:
                bounds[k] = _pair_bounds(formal_bounds.get(k, val_s), (val_s, val_s))
            else:
                consts[k] = val_s
    for k in scalar_keys:
        if k not in bounds and k not in consts:
            val_s = str(merged[k])
            consts[k] = val_s
    return bounds, consts


def _merged_inputs(method_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(METHOD_DEFAULT_INPUTS.get(method_id) or {})
    for k, v in (inputs or {}).items():
        if v is not None and v != "":
            defaults[k] = v
    return defaults


def _ast_to_z3(node: ast.AST, env: dict[str, z3.ArithRef]) -> z3.ArithRef:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return z3.RealVal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"unknown_symbol:{node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        v = _ast_to_z3(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise ValueError("unsupported_unary_op")
    if isinstance(node, ast.BinOp):
        left = _ast_to_z3(node.left, env)
        right = _ast_to_z3(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
            exp_i = int(node.right.value)
            return left**exp_i
        raise ValueError("unsupported_binop")
    raise ValueError("unsupported_expr")


def _prove_plugin_card(
    engine: SMTSolverProofEngine,
    method_id: str,
    inputs: dict[str, Any],
    formal_bounds: dict[str, Any],
) -> dict[str, Any]:
    from evidence_calc.registry import load_card

    card = load_card(method_id)
    req = list(card.get("required") or [])
    limits = dict(card.get("limits") or {})
    bounds: dict[str, tuple[str, str]] = {}
    for k in req:
        lim = dict(limits.get(k) or {})
        default_v = str(lim.get("min") or lim.get("min_exclusive") or "1")
        if k in lim and "min_exclusive" in lim and k not in inputs and k not in formal_bounds:
            lo_f = float(lim["min_exclusive"])
            hi_f = float(lim.get("max") or lim.get("max_exclusive") or (lo_f + 10.0))
            default_v = _dec_str(0.5 * (lo_f + min(hi_f, lo_f + 10.0)))
        val = inputs.get(k, default_v)
        bounds[k] = _pair_bounds(formal_bounds.get(k, val), (str(val), str(val)))

    formulas = list(card.get("formulas") or [])

    def _build(solver: z3.Solver, zv: dict[str, z3.ArithRef], zc: dict[str, z3.ArithRef]) -> None:
        env: dict[str, z3.ArithRef] = {**zv, **zc}
        bad: list[Any] = []
        for k, lim in limits.items():
            if k not in env:
                continue
            sym = env[k]
            if "min" in lim:
                bad.append(sym < z3.RealVal(str(lim["min"])))
            if "min_exclusive" in lim:
                bad.append(sym <= z3.RealVal(str(lim["min_exclusive"])))
            if "max" in lim:
                bad.append(sym > z3.RealVal(str(lim["max"])))
            if "max_exclusive" in lim:
                bad.append(sym >= z3.RealVal(str(lim["max_exclusive"])))
        for f in formulas:
            expr_s = str(f.get("expr") or "")
            out_name = str(f.get("output") or "")
            if not expr_s:
                continue
            tree = ast.parse(expr_s, mode="eval").body
            for sub in ast.walk(tree):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                    denom = _ast_to_z3(sub.right, env)
                    bad.append(denom == 0)
            if out_name:
                env[out_name] = _ast_to_z3(tree, env)
        if not bad:
            bad.append(z3.BoolVal(False))
        solver.add(z3.Or(*bad))

    res = engine.prove_z3_property(
        property_name=f"plugin_{method_id}_domain_safety",
        bounds=bounds,
        constants={},
        assertion=f"forall inputs in bounds: {method_id} satisfies limits & zero-div safety",
        build_violation=_build,
        proved_reason=f"Plugin card '{method_id}' satisfies declared domain & safety limits",
        cex_reason=f"Plugin card '{method_id}' violates limit or denominator safety",
    )
    return res.to_dict()


def run_formal_proof_for_method(
    method_id: str,
    inputs: dict[str, Any] | None = None,
    formal_bounds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Z3+cvc5 SMT formal proof for any built-in (32+) or plugin calculation method."""
    from evidence_coverage.formal_bounds import prove_continuous_flight_envelope

    in_map = dict(inputs or {})
    bounds_in = dict(formal_bounds or {})

    if method_id == "rigid_body_point_mass":
        merged = _merged_inputs(method_id, in_map)
        mass_range = _pair_bounds(
            bounds_in.get("mass_range_kg") or bounds_in.get("mass_bounds") or merged.get("mass_kg"),
            ("800.000", "1200.000"),
        )
        cg_range = _pair_bounds(
            bounds_in.get("cg_range_m") or merged.get("cg_x_m"),
            ("-0.200", "0.200"),
        )
        lf_range = _pair_bounds(
            bounds_in.get("load_factor_range")
            or bounds_in.get("load_factor_bounds")
            or merged.get("load_factor"),
            ("-1.000", "2.500"),
        )
        stations_raw = bounds_in.get("station_positions_m") or merged.get("unit_x_m")
        stations = [str(x) for x in stations_raw] if stations_raw else None
        max_thrust = str(
            bounds_in.get("max_station_thrust_n") or bounds_in.get("lift_capacity_n") or "15000.000"
        )
        gravity = str(merged.get("gravity_m_s2") or bounds_in.get("gravity_m_s2") or "9.807")
        min_active = int(bounds_in.get("min_active_units", 3))
        out = prove_continuous_flight_envelope(
            mass_range_kg=mass_range,
            cg_range_m=cg_range,
            load_factor_range=lf_range,
            station_positions_m=stations,
            max_station_thrust_n=max_thrust,
            gravity_m_s2=gravity,
            min_active_units=min_active,
        )
        out["proved"] = bool(out.get("envelope_proved"))
        return out

    engine = SMTSolverProofEngine(timeout_ms=3000)

    if method_id == "bolt_screen":
        merged = _merged_inputs(method_id, in_map)
        return engine.prove_structural_margin(
            bounds={
                "area_mm2": _pair_bounds(
                    bounds_in.get("area_mm2") or merged.get("area_mm2"), ("100.000", "120.000")
                ),
                "shear_force_n": _pair_bounds(
                    bounds_in.get("shear_force_n") or merged.get("shear_force_n"),
                    ("1000.000", "2000.000"),
                ),
                "tensile_force_n": _pair_bounds(
                    bounds_in.get("tensile_force_n") or merged.get("tensile_force_n"),
                    ("2000.000", "3000.000"),
                ),
            },
            allowables={
                "shear_allowable_mpa": str(merged.get("shear_allowable_mpa") or "150.000"),
                "tensile_allowable_mpa": str(merged.get("tensile_allowable_mpa") or "250.000"),
            },
            safety_factor=str(bounds_in.get("safety_factor") or "1.500"),
        ).to_dict()

    if method_id == "hover_power_screen":
        merged = _merged_inputs(method_id, in_map)
        return engine.prove_hover_power_envelope(
            thrust_bounds_n=_pair_bounds(
                bounds_in.get("thrust_n") or merged.get("thrust_n"), ("2000.000", "10500.000")
            ),
            disk_area_m2=str(merged.get("disk_area_m2") or "10.000"),
            air_density_kg_m3=str(merged.get("air_density_kg_m3") or "1.225"),
            figure_of_merit=str(merged.get("figure_of_merit") or "0.700"),
            max_power_available_kw=str(merged.get("power_available_kw") or "350.000"),
        ).to_dict()

    if method_id not in METHOD_DEFAULT_INPUTS:
        try:
            return _prove_plugin_card(engine, method_id, in_map, bounds_in)
        except Exception:
            return {
                "property_name": f"{method_id}_formal_bounds",
                "proved": False,
                "status": "UNSUPPORTED_METHOD",
                "method_id": method_id,
            }

    merged = _merged_inputs(method_id, in_map)
    return _prove_builtin_method(engine, method_id, merged, bounds_in)


def _bound_extrema(
    bounds: dict[str, tuple[str, str]],
    consts: dict[str, str],
    k: str,
) -> tuple[float, float]:
    if k in bounds:
        return float(bounds[k][0]), float(bounds[k][1])
    v = float(consts[k])
    return v, v


def _prove_builtin_method(
    engine: SMTSolverProofEngine,
    method_id: str,
    merged: dict[str, Any],
    formal_bounds: dict[str, Any],
) -> dict[str, Any]:
    pi_sq = z3.RealVal(_PI_STR) * z3.RealVal(_PI_STR)
    pi_v = z3.RealVal(_PI_STR)

    if method_id == "margin_of_safety":
        keys = ["applied_load_n", "allowable_load_n", "reserve_factor", "fitting_factor"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(
                p["applied_load_n"] * p["reserve_factor"] * p["fitting_factor"]
                > p["allowable_load_n"]
            )

        return engine.prove_z3_property(
            property_name="margin_of_safety_positive",
            bounds=b,
            constants=c,
            assertion="applied_load_n * reserve_factor * fitting_factor <= allowable_load_n",
            build_violation=_v,
            proved_reason="Margin of safety >= 0 across input interval",
            cex_reason="Factored load exceeds allowable load",
        ).to_dict()

    if method_id == "column_plate_buckling":
        keys = [
            "applied_compression_n",
            "column_length_mm",
            "end_fixity_k",
            "area_mm2",
            "inertia_mm4",
            "youngs_modulus_mpa",
            "yield_strength_mpa",
            "poissons_ratio",
            "plate_width_b_mm",
            "plate_thickness_t_mm",
            "plate_buckling_coeff_kc",
            "crippling_cutoff_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            leff = p["end_fixity_k"] * p["column_length_mm"]
            a, i_m = p["area_mm2"], p["inertia_mm4"]
            e, sy = p["youngs_modulus_mpa"], p["yield_strength_mpa"]
            p_app = p["applied_compression_n"]
            nu, bw, tw = p["poissons_ratio"], p["plate_width_b_mm"], p["plate_thickness_t_mm"]
            is_euler = (leff * leff * a * sy) >= (2 * pi_sq * e * i_m)
            viol_col = z3.If(
                is_euler,
                p_app * leff * leff > pi_sq * e * i_m,
                p_app * 4 * pi_sq * e * i_m > a * sy * (4 * pi_sq * e * i_m - sy * leff * leff * a),
            )
            viol_scc = p_app > p["crippling_cutoff_mpa"] * a
            viol_plt = (
                p_app * 12 * (1 - nu * nu) * bw * bw
                > a * p["plate_buckling_coeff_kc"] * pi_sq * e * tw * tw
            )
            s.add(z3.Or(viol_col, viol_scc, viol_plt))

        return engine.prove_z3_property(
            property_name="column_plate_buckling_stability",
            bounds=b,
            constants=c,
            assertion="applied_compression_n <= min(sigma_col, sigma_plate) * area_mm2",
            build_violation=_v,
            proved_reason="Euler-Johnson column and local plate crippling margins hold",
            cex_reason="Compressive load exceeds governing buckling stress",
        ).to_dict()

    if method_id == "palmgren_miner_fatigue":
        n_list = list(merged["cycles_applied"])
        cap_list = list(merged["cycles_to_failure"])
        b, c = _split_bounds_and_consts(merged, formal_bounds, ["scatter_factor", "damage_limit"])
        extra: dict[str, Any] = {"blocks": len(n_list)}
        for idx, (nv, cv) in enumerate(zip(n_list, cap_list, strict=True)):
            c[f"n_{idx}"] = str(nv)
            c[f"cap_{idx}"] = str(cv)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            total_d = sum(p[f"n_{i}"] / p[f"cap_{i}"] for i in range(len(n_list)))
            s.add(p["scatter_factor"] * total_d > p["damage_limit"])

        return engine.prove_z3_property(
            property_name="palmgren_miner_damage_limit",
            bounds=b,
            constants=c,
            assertion="scatter_factor * sum(n_i / N_i) <= damage_limit",
            build_violation=_v,
            proved_reason="Factored cumulative Miner damage remains within limit",
            cex_reason="Cumulative Miner fatigue damage exceeds limit",
            cache_extra=extra,
        ).to_dict()

    if method_id in {"composite_failure_criteria", "tsai_wu_ply_failure"}:
        keys = ["sigma_1_mpa", "sigma_2_mpa", "tau_12_mpa", "xt_mpa", "xc_mpa", "yt_mpa", "yc_mpa"]
        if method_id == "composite_failure_criteria":
            keys += ["s12_mpa", "f12_star"]
        else:
            merged = {**merged, "s12_mpa": merged["s12_mpa"], "f12_star": "-0.500"}
            keys += ["s12_mpa", "f12_star"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s1, s2, t12 = p["sigma_1_mpa"], p["sigma_2_mpa"], p["tau_12_mpa"]
            xt, xc, yt, yc, s12 = p["xt_mpa"], p["xc_mpa"], p["yt_mpa"], p["yc_mpa"], p["s12_mpa"]
            r_prod = z3.Real("_tw_r_prod")
            s.add(r_prod > 0, r_prod * r_prod == xt * xc * yt * yc)
            fi_tw = (
                s1 * ((1 / xt) - (1 / xc))
                + s2 * ((1 / yt) - (1 / yc))
                + (s1 * s1) / (xt * xc)
                + (s2 * s2) / (yt * yc)
                + (t12 * t12) / (s12 * s12)
                + (2 * p["f12_star"] * s1 * s2) / r_prod
            )
            viol = [fi_tw > 1]
            if method_id == "composite_failure_criteria":
                fi_ft = z3.If(s1 >= 0, (s1 / xt) ** 2 + (t12 / s12) ** 2, 0)
                fi_fc = z3.If(s1 < 0, (s1 / xc) ** 2, 0)
                fi_mt = z3.If(s2 >= 0, (s2 / yt) ** 2 + (t12 / s12) ** 2, 0)
                mc_t = (yc / (2 * s12)) ** 2 - 1
                fi_mc = z3.If(
                    s2 < 0, (s2 / (2 * s12)) ** 2 + mc_t * (s2 / yc) + (t12 / s12) ** 2, 0
                )
                viol.extend([fi_ft > 1, fi_fc > 1, fi_mt > 1, fi_mc > 1])
            s.add(z3.Or(*viol))

        return engine.prove_z3_property(
            property_name=f"{method_id}_ply_envelope",
            bounds=b,
            constants=c,
            assertion="Tsai-Wu & directional failure indices <= 1",
            build_violation=_v,
            proved_reason="Ply failure indices stay strictly inside strength envelope",
            cex_reason="Composite failure index exceeds 1.0",
        ).to_dict()

    if method_id == "hashin_composite_modes":
        keys = [
            "sigma_1_mpa",
            "sigma_2_mpa",
            "tau_12_mpa",
            "xt_mpa",
            "xc_mpa",
            "yt_mpa",
            "yc_mpa",
            "sl_mpa",
            "st_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s1, s2, t12 = p["sigma_1_mpa"], p["sigma_2_mpa"], p["tau_12_mpa"]
            xt, xc, yt, yc = p["xt_mpa"], p["xc_mpa"], p["yt_mpa"], p["yc_mpa"]
            sl, st = p["sl_mpa"], p["st_mpa"]
            fi_ft = z3.If(s1 >= 0, (s1 / xt) ** 2 + (t12 / sl) ** 2, 0)
            fi_fc = z3.If(s1 < 0, (s1 / xc) ** 2, 0)
            fi_mt = z3.If(s2 >= 0, (s2 / yt) ** 2 + (t12 / sl) ** 2, 0)
            fi_mc = z3.If(
                s2 < 0,
                (s2 / (2 * st)) ** 2 + (((yc / (2 * st)) ** 2 - 1) * (s2 / yc)) + (t12 / sl) ** 2,
                0,
            )
            s.add(z3.Or(fi_ft > 1, fi_fc > 1, fi_mt > 1, fi_mc > 1))

        return engine.prove_z3_property(
            property_name="hashin_4mode_ply_safety",
            bounds=b,
            constants=c,
            assertion="max(Hashin ft, fc, mt, mc) <= 1",
            build_violation=_v,
            proved_reason="All 4 Hashin ply failure indices remain <= 1.0",
            cex_reason="Hashin ply failure index exceeds 1.0",
        ).to_dict()

    if method_id == "puck_interfiber_fracture":
        keys = ["sigma_2_mpa", "tau_12_mpa", "yt_mpa", "yc_mpa", "sl_mpa"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s2, t12 = p["sigma_2_mpa"], p["tau_12_mpa"]
            yt, yc, sl = p["yt_mpa"], p["yc_mpa"], p["sl_mpa"]
            p_pt, p_pc = z3.RealVal("0.30"), z3.RealVal("0.20")
            u_r = z3.Real("_puck_ur")
            s.add(u_r >= 1, u_r * u_r == 1 + 2 * p_pc * (yc / sl))
            r_22a = (sl / (2 * p_pc)) * (u_r - 1)
            w_t = z3.Real("_puck_wt")
            s.add(w_t >= 1, w_t * w_t == 1 + 2 * (yc / r_22a))
            tau_21c = sl * w_t
            rad_a = z3.Real("_puck_rada")
            rad_a_sq = (t12 / sl) ** 2 + (1 - p_pt * (yt / sl)) ** 2 * (s2 / yt) ** 2
            s.add(rad_a >= 0, rad_a * rad_a == rad_a_sq)
            fe_a = rad_a + p_pt * (s2 / sl)
            rad_b = z3.Real("_puck_radb")
            s.add(rad_b >= 0, rad_b * rad_b == (t12 / sl) ** 2 + (p_pc * (s2 / sl)) ** 2)
            fe_b = rad_b + p_pc * (s2 / sl)
            abs_s2 = z3.If(s2 >= 0, s2, -s2)
            abs_t12 = z3.If(t12 >= 0, t12, -t12)
            denom_s2 = z3.If(abs_s2 > z3.RealVal("0.001"), abs_s2, z3.RealVal("0.001"))
            denom_t12 = z3.If(abs_t12 > z3.RealVal("0.001"), abs_t12, z3.RealVal("0.001"))
            fe_c = ((t12 / (2 * (1 + p_pc) * sl)) ** 2 + (s2 / yc) ** 2) * (yc / denom_s2)
            fe = z3.If(
                s2 >= 0,
                fe_a,
                z3.If(z3.And(abs_s2 <= r_22a, abs_s2 * tau_21c <= r_22a * denom_t12), fe_b, fe_c),
            )
            s.add(fe > 1)

        return engine.prove_z3_property(
            property_name="puck_iff_exposure_safety",
            bounds=b,
            constants=c,
            assertion="Puck 2D exposure factor f_E(IFF) <= 1",
            build_violation=_v,
            proved_reason="Puck IFF Mode A/B/C exposure remains <= 1.0",
            cex_reason="Puck interfiber fracture exposure exceeds 1.0",
        ).to_dict()

    if method_id == "bearing_bypass_interaction":
        keys = [
            "bearing_load_n",
            "bypass_load_n",
            "hole_diameter_mm",
            "strip_width_mm",
            "thickness_mm",
            "bearing_allowable_mpa",
            "bypass_oht_allowable_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            r_br = p["bearing_load_n"] / (
                p["hole_diameter_mm"] * p["thickness_mm"] * p["bearing_allowable_mpa"]
            )
            r_byp = p["bypass_load_n"] / (
                p["strip_width_mm"] * p["thickness_mm"] * p["bypass_oht_allowable_mpa"]
            )
            s.add(r_br + r_byp > 1)

        return engine.prove_z3_property(
            property_name="bearing_bypass_interaction_envelope",
            bounds=b,
            constants=c,
            assertion="R_br + R_byp <= 1",
            build_violation=_v,
            proved_reason="Linear bearing-bypass utilization stays <= 1.0",
            cex_reason="Bearing-bypass interaction exceeds 1.0",
        ).to_dict()

    if method_id == "bolt_preload_thermal_relaxation":
        keys = [
            "initial_preload_n",
            "embedment_loss_n",
            "bolt_cte_per_c",
            "plate_cte_per_c",
            "delta_temp_c",
            "bolt_stiffness_n_per_mm",
            "joint_stiffness_n_per_mm",
            "grip_length_mm",
            "external_tensile_load_n",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            kb, kp = p["bolt_stiffness_n_per_mm"], p["joint_stiffness_n_per_mm"]
            k_eq = (kb * kp) / (kb + kp)
            eff = (
                p["initial_preload_n"]
                - p["embedment_loss_n"]
                + k_eq
                * (p["plate_cte_per_c"] - p["bolt_cte_per_c"])
                * p["delta_temp_c"]
                * p["grip_length_mm"]
            )
            clamp_res = eff - (kp / (kb + kp)) * p["external_tensile_load_n"]
            s.add(z3.Or(eff <= 0, clamp_res < 0))

        return engine.prove_z3_property(
            property_name="bolt_joint_non_separation",
            bounds=b,
            constants=c,
            assertion="eff_preload > 0 and residual_clamp_force >= 0",
            build_violation=_v,
            proved_reason="Preloaded bolted joint remains clamped without separation",
            cex_reason="Joint separation or total preload loss occurs",
        ).to_dict()

    if method_id == "eccentric_bolt_group_cg":
        keys = [
            "shear_vx_n",
            "shear_vy_n",
            "moment_mz_nmm",
            "half_spacing_x_mm",
            "half_spacing_y_mm",
            "bolt_shear_allowable_n",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            dx, dy = p["half_spacing_x_mm"], p["half_spacing_y_mm"]
            vx, vy, mz = p["shear_vx_n"], p["shear_vy_n"], p["moment_mz_nmm"]
            v_allow = p["bolt_shear_allowable_n"]
            sum_r2 = 4 * (dx * dx + dy * dy)
            bad = []
            for sx in (1, -1):
                for sy in (1, -1):
                    fx_num = vx * (dx * dx + dy * dy) - mz * (sy * dy)
                    fy_num = vy * (dx * dx + dy * dy) + mz * (sx * dx)
                    bad.append(fx_num * fx_num + fy_num * fy_num > (v_allow * sum_r2) ** 2)
            s.add(z3.Or(*bad))

        return engine.prove_z3_property(
            property_name="eccentric_bolt_group_shear_safety",
            bounds=b,
            constants=c,
            assertion="max_corner_bolt_resultant <= bolt_shear_allowable_n",
            build_violation=_v,
            proved_reason="Critical corner bolt resultant shear stays within allowable",
            cex_reason="Critical corner bolt shear exceeds allowable",
        ).to_dict()

    if method_id == "fastener_pull_through_composite":
        keys = [
            "tensile_load_n",
            "head_diameter_mm",
            "laminate_thickness_mm",
            "ilss_allowable_mpa",
            "countersink_knockdown",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(
                p["tensile_load_n"]
                > pi_v
                * p["head_diameter_mm"]
                * p["laminate_thickness_mm"]
                * p["ilss_allowable_mpa"]
                * p["countersink_knockdown"]
            )

        return engine.prove_z3_property(
            property_name="fastener_pull_through_margin",
            bounds=b,
            constants=c,
            assertion="tensile_load_n <= pi * D_head * t * ILSS * Kf",
            build_violation=_v,
            proved_reason="Composite pull-through load within cylindrical shear allowable",
            cex_reason="Tensile load exceeds composite pull-through allowable",
        ).to_dict()

    if method_id == "goodman_haigh_mean_stress":
        keys = [
            "alternating_stress_mpa",
            "mean_stress_mpa",
            "endurance_limit_mpa",
            "ultimate_tensile_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            eff_sm = z3.If(p["mean_stress_mpa"] > 0, p["mean_stress_mpa"], 0)
            s.add(
                p["alternating_stress_mpa"] * p["ultimate_tensile_mpa"]
                + eff_sm * p["endurance_limit_mpa"]
                > p["endurance_limit_mpa"] * p["ultimate_tensile_mpa"]
            )

        return engine.prove_z3_property(
            property_name="goodman_haigh_infinite_life_envelope",
            bounds=b,
            constants=c,
            assertion="(sigma_a / Se) + (max(0, sigma_m) / Sut) <= 1",
            build_violation=_v,
            proved_reason="Goodman mean-stress line remains <= 1.0",
            cex_reason="Goodman fatigue interaction exceeds 1.0",
        ).to_dict()

    if method_id == "inter_rivet_buckling":
        keys = [
            "compressive_stress_mpa",
            "rivet_pitch_mm",
            "skin_thickness_mm",
            "rivet_head_fixity_c",
            "tangent_modulus_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(
                p["compressive_stress_mpa"] * 12 * (p["rivet_pitch_mm"] ** 2)
                > p["rivet_head_fixity_c"]
                * pi_sq
                * p["tangent_modulus_mpa"]
                * (p["skin_thickness_mm"] ** 2)
            )

        return engine.prove_z3_property(
            property_name="inter_rivet_buckling_margin",
            bounds=b,
            constants=c,
            assertion="sigma_comp <= C * pi^2 * Et * t^2 / (12 * p^2)",
            build_violation=_v,
            proved_reason="Applied compressive stress stays below inter-rivet buckling stress",
            cex_reason="Skin stress exceeds inter-rivet buckling stress",
        ).to_dict()

    if method_id == "johnson_euler_column":
        keys = [
            "compressive_load_n",
            "section_area_mm2",
            "min_inertia_mm4",
            "column_length_mm",
            "end_fixity_c",
            "modulus_mpa",
            "compressive_yield_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            p_c, a, im, length = (
                p["compressive_load_n"],
                p["section_area_mm2"],
                p["min_inertia_mm4"],
                p["column_length_mm"],
            )
            c_e, em, fcy = p["end_fixity_c"], p["modulus_mpa"], p["compressive_yield_mpa"]
            # slend^2 = length^2 * a / (c_e * im); lam_c^2 = 2 * pi^2 * em / fcy
            is_johnson = (length * length * a * fcy) <= (2 * pi_sq * em * c_e * im)
            viol_joh = p_c * 4 * pi_sq * em * c_e * im > a * fcy * (
                4 * pi_sq * em * c_e * im - fcy * length * length * a
            )
            viol_eul = p_c * length * length > pi_sq * em * c_e * im
            s.add(z3.If(is_johnson, viol_joh, viol_eul))

        return engine.prove_z3_property(
            property_name="johnson_euler_column_stability",
            bounds=b,
            constants=c,
            assertion="compressive_load_n / area <= sigma_cr_johnson_euler",
            build_violation=_v,
            proved_reason="Johnson-Euler column critical load envelope holds",
            cex_reason="Compressive load exceeds Johnson-Euler critical load",
        ).to_dict()

    if method_id == "rainflow_spectrum_damage":
        keys = [
            "cycles_band1",
            "allowable_cycles_band1",
            "cycles_band2",
            "allowable_cycles_band2",
            "cycles_band3",
            "allowable_cycles_band3",
            "scatter_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            dmg = (
                (p["cycles_band1"] / p["allowable_cycles_band1"])
                + (p["cycles_band2"] / p["allowable_cycles_band2"])
                + (p["cycles_band3"] / p["allowable_cycles_band3"])
            )
            s.add(p["scatter_factor"] * dmg > 1)

        return engine.prove_z3_property(
            property_name="rainflow_spectrum_life_safety",
            bounds=b,
            constants=c,
            assertion="scatter_factor * (n1/N1 + n2/N2 + n3/N3) <= 1",
            build_violation=_v,
            proved_reason="Rainflow factored fatigue spectrum damage <= 1.0",
            cex_reason="Rainflow factored damage exceeds 1.0",
        ).to_dict()

    if method_id == "thin_walled_bredt_batho_torsion":
        keys = [
            "torque_nmm",
            "enclosed_area_mm2",
            "min_wall_thickness_mm",
            "shear_allowable_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(
                p["torque_nmm"]
                > 2 * p["enclosed_area_mm2"] * p["min_wall_thickness_mm"] * p["shear_allowable_mpa"]
            )

        return engine.prove_z3_property(
            property_name="bredt_batho_torsional_shear_safety",
            bounds=b,
            constants=c,
            assertion="T / (2 * A_enc * t_min) <= shear_allowable_mpa",
            build_violation=_v,
            proved_reason="Closed-section Bredt-Batho shear stress stays within allowable",
            cex_reason="Torsional shear stress exceeds shear allowable",
        ).to_dict()

    if method_id == "sandwich_core_shear_wrinkling":
        keys = [
            "facesheet_stress_mpa",
            "transverse_shear_n_per_mm",
            "facesheet_thickness_mm",
            "core_thickness_mm",
            "facesheet_modulus_mpa",
            "core_compression_modulus_mpa",
            "core_shear_modulus_mpa",
            "core_shear_allowable_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            viol_shear = p["transverse_shear_n_per_mm"] > p["core_shear_allowable_mpa"] * (
                p["core_thickness_mm"] + p["facesheet_thickness_mm"]
            )
            viol_wr = 8 * (p["facesheet_stress_mpa"] ** 3) > (
                p["facesheet_modulus_mpa"]
                * p["core_compression_modulus_mpa"]
                * p["core_shear_modulus_mpa"]
            )
            s.add(z3.Or(viol_shear, viol_wr))

        return engine.prove_z3_property(
            property_name="sandwich_wrinkling_and_core_shear",
            bounds=b,
            constants=c,
            assertion="q <= tau_core*(tc+tf) and 8*sigma_f^3 <= Ef*Ec*Gc",
            build_violation=_v,
            proved_reason="Hoff wrinkling & honeycomb core shear margins hold",
            cex_reason="Sandwich facesheet wrinkling or core shear margin violated",
        ).to_dict()

    if method_id == "curved_panel_compression_shear":
        keys = [
            "compressive_stress_mpa",
            "shear_stress_mpa",
            "arc_width_mm",
            "skin_thickness_mm",
            "radius_curvature_mm",
            "modulus_mpa",
            "poisson_nu",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            rz = z3.Real("_curv_rz")
            s.add(rz > 0, rz * rz == 1 - p["poisson_nu"] ** 2)
            bw = p["arc_width_mm"]
            tw = p["skin_thickness_mm"]
            rc = p["radius_curvature_mm"]
            em = p["modulus_mpa"]
            zb = (bw * bw * rz) / (rc * tw)
            kc = z3.RealVal("3.62") + z3.RealVal("0.11") * zb
            ks = z3.RealVal("4.83") + z3.RealVal("0.09") * zb
            sig_cr = kc * em * (tw / bw) ** 2
            tau_cr = ks * em * (tw / bw) ** 2
            r_c = p["compressive_stress_mpa"] / sig_cr
            r_s = p["shear_stress_mpa"] / tau_cr
            s.add(r_c + r_s * r_s > 1)

        return engine.prove_z3_property(
            property_name="curved_panel_buckling_interaction",
            bounds=b,
            constants=c,
            assertion="R_c + R_s^2 <= 1 with Batdorf Z",
            build_violation=_v,
            proved_reason="Curved panel combined compression-shear buckling interaction <= 1",
            cex_reason="Curved panel compression-shear buckling interaction > 1",
        ).to_dict()

    if method_id == "lug_axial_transverse_interaction":
        keys = ["axial_load_n", "transverse_load_n", "axial_allowable_n", "transverse_allowable_n"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        ax_hi = _bound_extrema(b, c, "axial_load_n")[1]
        ax_all_lo = _bound_extrema(b, c, "axial_allowable_n")[0]
        tr_hi = _bound_extrema(b, c, "transverse_load_n")[1]
        tr_all_lo = _bound_extrema(b, c, "transverse_allowable_n")[0]
        # Exact rational slope linearization upper bound:
        # r^1.6 <= (r_ref^0.6) * r when r <= r_ref
        ra_ref = ax_hi / ax_all_lo
        rt_ref = tr_hi / tr_all_lo
        k_ax = _dec_str(min(1.0, (max(ra_ref, 1e-9)) ** 0.6) * 1.000001)
        k_tr = _dec_str(min(1.0, (max(rt_ref, 1e-9)) ** 0.6) * 1.000001)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            ra = p["axial_load_n"] / p["axial_allowable_n"]
            rtr = p["transverse_load_n"] / p["transverse_allowable_n"]
            if (ra_ref**1.6 + rt_ref**1.6) <= 1.0:
                s.add(z3.RealVal(k_ax) * ra + z3.RealVal(k_tr) * rtr > 1)
            else:
                u_pow, v_pow = z3.Real("_lug_u"), z3.Real("_lug_v")
                s.add(
                    u_pow >= 0,
                    u_pow**5 == ra**8,
                    v_pow >= 0,
                    v_pow**5 == rtr**8,
                    u_pow + v_pow > 1,
                )

        return engine.prove_z3_property(
            property_name="lug_axial_transverse_envelope",
            bounds=b,
            constants=c,
            assertion="R_a^1.6 + R_tr^1.6 <= 1",
            build_violation=_v,
            proved_reason="Lug axial-transverse interaction stays <= 1.0",
            cex_reason="Lug axial-transverse interaction exceeds 1.0",
        ).to_dict()

    if method_id == "needham_crippling_section":
        keys = [
            "compressive_load_n",
            "flange_width_mm",
            "flange_thickness_mm",
            "web_width_mm",
            "web_thickness_mm",
            "modulus_mpa",
            "compressive_yield_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        tf_lo = _bound_extrema(b, c, "flange_thickness_mm")[0]
        bf_hi = _bound_extrema(b, c, "flange_width_mm")[1]
        tw_lo = _bound_extrema(b, c, "web_thickness_mm")[0]
        bw_hi = _bound_extrema(b, c, "web_width_mm")[1]
        em_lo = _bound_extrema(b, c, "modulus_mpa")[0]
        fcy_lo = _bound_extrema(b, c, "compressive_yield_mpa")[0]
        uf_lo = ((tf_lo / bf_hi) ** 0.75) * 0.999999
        uw_lo = ((tw_lo / bw_hi) ** 0.75) * 0.999999
        ref_lo = math.sqrt(em_lo * fcy_lo) * 0.999999
        sf_cap = z3.RealVal(_dec_str(0.316 * ref_lo * uf_lo))
        sw_cap = z3.RealVal(_dec_str(0.366 * ref_lo * uw_lo))

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            tf, bf = p["flange_thickness_mm"], p["flange_width_mm"]
            tw, bw = p["web_thickness_mm"], p["web_width_mm"]
            fcy = p["compressive_yield_mpa"]
            sf = z3.If(fcy <= sf_cap, fcy, sf_cap)
            sw = z3.If(fcy <= sw_cap, fcy, sw_cap)
            s.add(p["compressive_load_n"] > (2 * bf * tf * sf + bw * tw * sw))

        return engine.prove_z3_property(
            property_name="needham_crippling_capacity",
            bounds=b,
            constants=c,
            assertion="compressive_load_n <= A_flange * sigma_f + A_web * sigma_w",
            build_violation=_v,
            proved_reason="Needham flange-and-web crippling capacity exceeds compressive load",
            cex_reason="Compressive load exceeds Needham crippling capacity",
        ).to_dict()

    if method_id == "adhesive_single_lap_volkersen":
        keys = [
            "tensile_load_n",
            "overlap_width_mm",
            "overlap_length_mm",
            "adhesive_shear_modulus_mpa",
            "adhesive_thickness_mm",
            "adherend_modulus_mpa",
            "adherend_thickness_mm",
            "adhesive_shear_allowable_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        g_hi = _bound_extrema(b, c, "adhesive_shear_modulus_mpa")[1]
        l_hi = _bound_extrema(b, c, "overlap_length_mm")[1]
        ea_lo = _bound_extrema(b, c, "adherend_modulus_mpa")[0]
        tp_lo = _bound_extrema(b, c, "adherend_thickness_mm")[0]
        ta_lo = _bound_extrema(b, c, "adhesive_thickness_mm")[0]
        half_wl_max = 0.5 * math.sqrt((2.0 * g_hi * l_hi * l_hi) / (ea_lo * tp_lo * ta_lo))
        coth_max = (math.cosh(half_wl_max) / math.sinh(half_wl_max)) if half_wl_max > 1e-9 else 1.0
        k_peak_hi = _dec_str(max(1.0, half_wl_max * coth_max) * 1.000001)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            tau_avg = p["tensile_load_n"] / (p["overlap_width_mm"] * p["overlap_length_mm"])
            s.add(tau_avg * z3.RealVal(k_peak_hi) > p["adhesive_shear_allowable_mpa"])

        return engine.prove_z3_property(
            property_name="volkersen_adhesive_peak_shear",
            bounds=b,
            constants=c,
            assertion="tau_avg * k_volkersen <= adhesive_shear_allowable_mpa",
            build_violation=_v,
            proved_reason="Volkersen peak adhesive shear stress remains within allowable",
            cex_reason="Volkersen peak adhesive shear exceeds allowable",
        ).to_dict()

    if method_id == "compression_after_impact_cai":
        keys = [
            "applied_compressive_mpa",
            "cai_allowable_bvid_mpa",
            "impact_energy_j",
            "reference_bvid_j",
            "environmental_knockdown",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        imp_hi = _bound_extrema(b, c, "impact_energy_j")[1]
        ref_lo = _bound_extrema(b, c, "reference_bvid_j")[0]
        r_hi = max(0.25, imp_hi / ref_lo)
        ekd_lo = min(1.10, max(0.65, (1.0 / r_hi) ** 0.18)) * 0.999999

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            ekd = z3.RealVal(_dec_str(ekd_lo))
            f_eff = p["cai_allowable_bvid_mpa"] * p["environmental_knockdown"] * ekd
            s.add(p["applied_compressive_mpa"] > f_eff)

        return engine.prove_z3_property(
            property_name="compression_after_impact_bvid_margin",
            bounds=b,
            constants=c,
            assertion="applied_compressive_mpa <= CAI_BVID * env_kd * energy_kd",
            build_violation=_v,
            proved_reason="CAI compressive stress stays within knocked-down BVID allowable",
            cex_reason="Compressive stress exceeds knocked-down CAI BVID allowable",
        ).to_dict()

    if method_id in {"open_hole_tension_oht", "open_hole_compression_ohc"}:
        if method_id == "open_hole_tension_oht":
            keys = [
                "applied_far_field_mpa",
                "oht_allowable_rtd_mpa",
                "hole_diameter_mm",
                "strip_width_mm",
                "environmental_knockdown",
            ]
            d_hi = float(merged["hole_diameter_mm"])
            if "hole_diameter_mm" in formal_bounds:
                d_pair = _pair_bounds(formal_bounds["hole_diameter_mm"], (str(d_hi), str(d_hi)))
                d_hi = max(d_hi, float(d_pair[1]))
            d_scale_lo = _dec_str(((6.35 / d_hi) ** 0.08) * 0.999999)
            b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

            def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
                p = {**zv, **zc}
                wc = (1 - p["hole_diameter_mm"] / p["strip_width_mm"]) / z3.RealVal("0.8333333333")
                wc_c = z3.If(
                    wc > z3.RealVal("1.08"),
                    z3.RealVal("1.08"),
                    z3.If(wc < z3.RealVal("0.80"), z3.RealVal("0.80"), wc),
                )
                f_eff = (
                    p["oht_allowable_rtd_mpa"]
                    * p["environmental_knockdown"]
                    * wc_c
                    * z3.RealVal(d_scale_lo)
                )
                s.add(p["applied_far_field_mpa"] > f_eff)

            prop = "open_hole_tension_margin"
            asrt = "applied_far_field_mpa <= F_OHT_eff"
        else:
            keys = [
                "applied_compressive_mpa",
                "ohc_allowable_rtd_mpa",
                "etw_knockdown",
                "hole_diameter_mm",
            ]
            d_hi = float(merged["hole_diameter_mm"])
            if "hole_diameter_mm" in formal_bounds:
                d_pair = _pair_bounds(formal_bounds["hole_diameter_mm"], (str(d_hi), str(d_hi)))
                d_hi = max(d_hi, float(d_pair[1]))
            d_fac_lo = _dec_str(min(1.05, max(0.75, (6.35 / d_hi) ** 0.06)) * 0.999999)
            b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

            def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
                p = {**zv, **zc}
                f_eff = p["ohc_allowable_rtd_mpa"] * p["etw_knockdown"] * z3.RealVal(d_fac_lo)
                s.add(p["applied_compressive_mpa"] > f_eff)

            prop = "open_hole_compression_margin"
            asrt = "applied_compressive_mpa <= F_OHC_eff"

        return engine.prove_z3_property(
            property_name=prop,
            bounds=b,
            constants=c,
            assertion=asrt,
            build_violation=_v,
            proved_reason="Open-hole notched composite stress stays within allowable",
            cex_reason="Applied stress exceeds open-hole composite allowable",
        ).to_dict()

    if method_id == "huth_fastener_flexibility":
        keys = [
            "fastener_diameter_mm",
            "plate1_thickness_mm",
            "plate2_thickness_mm",
            "plate1_modulus_mpa",
            "plate2_modulus_mpa",
            "fastener_modulus_mpa",
            "huth_b_coef",
            "shear_planes_n",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a_exp = float(merged["huth_a_exp"])
        t1_lo, _ = _bound_extrema(b, c, "plate1_thickness_mm")
        t2_lo, _ = _bound_extrema(b, c, "plate2_thickness_mm")
        _, d_hi = _bound_extrema(b, c, "fastener_diameter_mm")
        geom_min = _dec_str(((t1_lo + t2_lo) / (2.0 * d_hi)) ** a_exp)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            t1, t2, e1, e2, ef, n_sh = (
                p["plate1_thickness_mm"],
                p["plate2_thickness_mm"],
                p["plate1_modulus_mpa"],
                p["plate2_modulus_mpa"],
                p["fastener_modulus_mpa"],
                p["shear_planes_n"],
            )
            compl = (
                (1 / (t1 * e1))
                + (1 / (n_sh * t2 * e2))
                + (1 / (2 * t1 * ef))
                + (1 / (2 * n_sh * t2 * ef))
            )
            flex_lb = z3.RealVal(geom_min) * (p["huth_b_coef"] / n_sh) * compl
            s.add(flex_lb <= 0)

        return engine.prove_z3_property(
            property_name="huth_fastener_stiffness_well_posed",
            bounds=b,
            constants=c,
            assertion="Huth compliance C > 0 across joint geometry bounds",
            build_violation=_v,
            proved_reason="Huth fastener compliance & stiffness remain strictly positive",
            cex_reason="Huth fastener compliance became non-positive",
        ).to_dict()

    if method_id == "nasgro_paris_crack_growth":
        keys = [
            "initial_crack_mm",
            "delta_sigma_mpa",
            "geometry_factor_y",
            "fracture_toughness_mpa_sqrt_m",
            "paris_c",
            "paris_m",
            "required_cycles",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a0_hi = _bound_extrema(b, c, "initial_crack_mm")[1]
        sig_hi = _bound_extrema(b, c, "delta_sigma_mpa")[1]
        y_hi = _bound_extrema(b, c, "geometry_factor_y")[1]
        kic_lo = _bound_extrema(b, c, "fracture_toughness_mpa_sqrt_m")[0]
        c_hi = _bound_extrema(b, c, "paris_c")[1]
        m_val = float(merged["paris_m"])
        a0_m = a0_hi / 1000.0
        ac_m = ((kic_lo / (y_hi * sig_hi)) ** 2) / math.pi
        if ac_m <= a0_m:
            n_fail_lb = 0.0
        else:
            factor = c_hi * ((y_hi * sig_hi * math.sqrt(math.pi)) ** m_val)
            if abs(m_val - 2.0) < 1e-12:
                n_fail_lb = math.log(ac_m / a0_m) / factor
            else:
                p_exp = 1.0 - 0.5 * m_val
                n_fail_lb = ((ac_m**p_exp) - (a0_m**p_exp)) / (p_exp * factor)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            k_sq = (
                (p["geometry_factor_y"] * p["delta_sigma_mpa"]) ** 2
                * pi_v
                * (p["initial_crack_mm"] / 1000)
            )
            s.add(
                z3.Or(
                    k_sq >= p["fracture_toughness_mpa_sqrt_m"] ** 2,
                    z3.RealVal(_dec_str(n_fail_lb)) < p["required_cycles"],
                )
            )

        return engine.prove_z3_property(
            property_name="nasgro_paris_life_safety",
            bounds=b,
            constants=c,
            assertion="K_I < K_Ic and N_fail >= required_cycles",
            build_violation=_v,
            proved_reason="Crack stays sub-critical and Paris life >= required cycles",
            cex_reason="Crack reaches critical K_Ic or life falls below required cycles",
        ).to_dict()

    if method_id == "net_section_yielding_fracture":
        keys = [
            "applied_load_n",
            "plate_width_mm",
            "thickness_mm",
            "half_crack_mm",
            "yield_strength_mpa",
            "fracture_toughness_mpa_sqrt_m",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a_hi = _bound_extrema(b, c, "half_crack_mm")[1]
        w_lo = _bound_extrema(b, c, "plate_width_mm")[0]
        sec_cos_lo = max(1e-6, math.cos(math.pi * a_hi / w_lo))

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            net_w = p["plate_width_mm"] - 2 * p["half_crack_mm"]
            viol_net = z3.Or(
                net_w <= 0,
                p["applied_load_n"] > net_w * p["thickness_mm"] * p["yield_strength_mpa"],
            )
            sig_gross = p["applied_load_n"] / (p["plate_width_mm"] * p["thickness_mm"])
            k_fed_sq = (sig_gross * sig_gross * pi_v * (p["half_crack_mm"] / 1000)) / z3.RealVal(
                _dec_str(sec_cos_lo)
            )
            viol_lefm = k_fed_sq > p["fracture_toughness_mpa_sqrt_m"] ** 2
            s.add(z3.Or(viol_net, viol_lefm))

        return engine.prove_z3_property(
            property_name="net_section_yield_and_feddersen_lefm",
            bounds=b,
            constants=c,
            assertion="sigma_net <= Fy and K_Feddersen <= K_Ic",
            build_violation=_v,
            proved_reason="Net-section yield & Feddersen LEFM fracture margins hold",
            cex_reason="Net-section yield or LEFM fracture limit exceeded",
        ).to_dict()

    if method_id == "neuber_notch_plasticity":
        keys = [
            "nominal_stress_mpa",
            "kt_concentration",
            "modulus_mpa",
            "cyclic_strength_coeff_mpa",
            "cyclic_hardening_exp",
            "cyclic_yield_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        sy_lo = _bound_extrema(b, c, "cyclic_yield_mpa")[0]
        kp_hi = _bound_extrema(b, c, "cyclic_strength_coeff_mpa")[1]
        n_hi = _bound_extrema(b, c, "cyclic_hardening_exp")[1]
        eps_p_sy = _dec_str((sy_lo / kp_hi) ** (1.0 / n_hi))

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            sy, em = p["cyclic_yield_mpa"], p["modulus_mpa"]
            neuber_target = ((p["kt_concentration"] * p["nominal_stress_mpa"]) ** 2) / em
            neuber_cap = sy * ((sy / em) + z3.RealVal(eps_p_sy))
            s.add(neuber_cap < neuber_target)

        return engine.prove_z3_property(
            property_name="neuber_notch_plasticity_yield_bound",
            bounds=b,
            constants=c,
            assertion="sigma_local(Neuber) <= cyclic_yield_mpa",
            build_violation=_v,
            proved_reason="Neuber monotonic energy bound proves local notch stress <= cyclic yield",
            cex_reason="Local notch stress exceeds cyclic yield",
        ).to_dict()

    if method_id == "shear_web_diagonal_tension":
        keys = [
            "applied_shear_n",
            "web_depth_mm",
            "web_thickness_mm",
            "stiffener_pitch_mm",
            "modulus_mpa",
            "web_shear_ultimate_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        # Worst-case Kuhn k_idt upper bound across bounds (k_idt in [0, 1))
        v_hi = _bound_extrema(b, c, "applied_shear_n")[1]
        h_lo, h_hi = _bound_extrema(b, c, "web_depth_mm")
        t_lo = _bound_extrema(b, c, "web_thickness_mm")[0]
        p_lo, p_hi = _bound_extrema(b, c, "stiffener_pitch_mm")
        e_lo = _bound_extrema(b, c, "modulus_mpa")[0]
        tau_hi = v_hi / (h_lo * t_lo)
        bs = min(h_lo, p_lo)
        al = max(h_hi, p_hi)
        ks_min = 4.83 + 3.6 * ((bs / al) ** 2)
        tau_cr_min = ks_min * e_lo * ((t_lo / max(h_hi, p_hi)) ** 2)
        k_idt_hi = 0.0 if tau_hi <= tau_cr_min else math.tanh(0.5 * math.log(tau_hi / tau_cr_min))
        k_mult = _dec_str(1.0 + 0.25 * k_idt_hi)

        def _v(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            tau_app = p["applied_shear_n"] / (p["web_depth_mm"] * p["web_thickness_mm"])
            s.add(tau_app * z3.RealVal(k_mult) > p["web_shear_ultimate_mpa"])

        return engine.prove_z3_property(
            property_name="shear_web_diagonal_tension_safety",
            bounds=b,
            constants=c,
            assertion="tau_app * (1 + 0.25 * k_idt) <= F_su",
            build_violation=_v,
            proved_reason="Diagonal tension effective shear remains within F_su",
            cex_reason="Effective diagonal-tension web shear exceeds F_su",
        ).to_dict()

    if method_id == "clt_laminate_abd_stiffness":
        from evidence_calc.rotorcraft_stress import _solve_linear_system

        keys = [
            "nx_n_per_mm",
            "ny_n_per_mm",
            "nxy_n_per_mm",
            "mx_n_mm_per_mm",
            "xt_mpa",
            "yt_mpa",
            "s12_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        t_ply = Decimal(str(merged["ply_thickness_mm"]))
        e1_m = Decimal(str(merged["e1_mpa"]))
        e2_m = Decimal(str(merged["e2_mpa"]))
        g12_m = Decimal(str(merged["g12_mpa"]))
        nu12 = Decimal(str(merged["nu12"]))
        nu21 = nu12 * e2_m / e1_m
        denom = Decimal("1") - nu12 * nu21
        q11 = e1_m / denom
        q22 = e2_m / denom
        q12 = nu12 * e2_m / denom
        q66 = g12_m
        half_h = Decimal("2") * t_ply
        a_m = [[Decimal("0")] * 3 for _ in range(3)]
        b_m = [[Decimal("0")] * 3 for _ in range(3)]
        d_m = [[Decimal("0")] * 3 for _ in range(3)]
        ply_geom = []
        for idx in range(4):
            rad = float(Decimal(str(merged[f"theta_{idx + 1}_deg"]))) * math.pi / 180.0
            cs, sn = Decimal(str(math.cos(rad))), Decimal(str(math.sin(rad)))
            c2, s2, sc = cs * cs, sn * sn, sn * cs
            c4, s4 = c2 * c2, s2 * s2
            qb = [
                [
                    q11 * c4 + Decimal("2") * (q12 + Decimal("2") * q66) * s2 * c2 + q22 * s4,
                    (q11 + q22 - Decimal("4") * q66) * s2 * c2 + q12 * (s4 + c4),
                    (q11 - q12 - Decimal("2") * q66) * sc * c2
                    + (q12 - q22 + Decimal("2") * q66) * s2 * sc,
                ],
                [
                    (q11 + q22 - Decimal("4") * q66) * s2 * c2 + q12 * (s4 + c4),
                    q11 * s4 + Decimal("2") * (q12 + Decimal("2") * q66) * s2 * c2 + q22 * c4,
                    (q11 - q12 - Decimal("2") * q66) * s2 * sc
                    + (q12 - q22 + Decimal("2") * q66) * sc * c2,
                ],
                [
                    (q11 - q12 - Decimal("2") * q66) * sc * c2
                    + (q12 - q22 + Decimal("2") * q66) * s2 * sc,
                    (q11 - q12 - Decimal("2") * q66) * s2 * sc
                    + (q12 - q22 + Decimal("2") * q66) * sc * c2,
                    (q11 + q22 - Decimal("2") * q12 - Decimal("2") * q66) * s2 * c2
                    + q66 * (s4 + c4),
                ],
            ]
            z0 = -half_h + Decimal(idx) * t_ply
            z1 = z0 + t_ply
            dz1 = z1 - z0
            dz2 = (z1 * z1 - z0 * z0) / Decimal("2")
            dz3 = (z1 * z1 * z1 - z0 * z0 * z0) / Decimal("3")
            for ii in range(3):
                for jj in range(3):
                    a_m[ii][jj] += qb[ii][jj] * dz1
                    b_m[ii][jj] += qb[ii][jj] * dz2
                    d_m[ii][jj] += qb[ii][jj] * dz3
            ply_geom.append((c2, s2, sc, z0, z1))
        abd_m = [[Decimal("0")] * 6 for _ in range(6)]
        for ii in range(3):
            for jj in range(3):
                abd_m[ii][jj] = a_m[ii][jj]
                abd_m[ii][jj + 3] = b_m[ii][jj]
                abd_m[ii + 3][jj] = b_m[ii][jj]
                abd_m[ii + 3][jj + 3] = d_m[ii][jj]
        inv_cols = []
        for col_i in range(4):
            unit_rhs = [Decimal("1") if r == col_i else Decimal("0") for r in range(6)]
            inv_cols.append(_solve_linear_system(abd_m, unit_rhs))

        def _v_clt(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            loads = [p["nx_n_per_mm"], p["ny_n_per_mm"], p["nxy_n_per_mm"], p["mx_n_mm_per_mm"]]
            xt_z, yt_z, s12_z = p["xt_mpa"], p["yt_mpa"], p["s12_mpa"]
            state6 = [
                sum(z3.RealVal(str(inv_cols[j][r])) * loads[j] for j in range(4)) for r in range(6)
            ]
            viol = []
            for c2, s2, sc, z0, z1 in ply_geom:
                for z_pt in (z0, z1):
                    zp = z3.RealVal(str(z_pt))
                    ex = state6[0] + zp * state6[3]
                    ey = state6[1] + zp * state6[4]
                    gxy = state6[2] + zp * state6[5]
                    e1_l = (
                        z3.RealVal(str(c2)) * ex
                        + z3.RealVal(str(s2)) * ey
                        + z3.RealVal(str(sc)) * gxy
                    )
                    e2_l = (
                        z3.RealVal(str(s2)) * ex
                        + z3.RealVal(str(c2)) * ey
                        - z3.RealVal(str(sc)) * gxy
                    )
                    g12_l = (
                        -2 * z3.RealVal(str(sc)) * ex
                        + 2 * z3.RealVal(str(sc)) * ey
                        + z3.RealVal(str(c2 - s2)) * gxy
                    )
                    sig1 = z3.RealVal(str(q11)) * e1_l + z3.RealVal(str(q12)) * e2_l
                    sig2 = z3.RealVal(str(q12)) * e1_l + z3.RealVal(str(q22)) * e2_l
                    tau12 = z3.RealVal(str(q66)) * g12_l
                    lhs = (
                        (sig1 * yt_z * s12_z) ** 2
                        + (sig2 * xt_z * s12_z) ** 2
                        + (tau12 * xt_z * yt_z) ** 2
                    )
                    rhs = (xt_z * yt_z * s12_z) ** 2
                    viol.append(lhs > rhs)
            s.add(z3.Or(*viol))

        return engine.prove_z3_property(
            property_name="clt_laminate_first_ply_safety",
            bounds=b,
            constants=c,
            assertion="max_ply FI(nx, ny, nxy, mx) <= 1 across all 4 plies",
            build_violation=_v_clt,
            proved_reason="All 4 CLT ply interfaces remain inside FI <= 1 envelope",
            cex_reason="CLT laminate exceeds ply failure envelope (FI > 1)",
        ).to_dict()

    if method_id == "rotor_blade_centrifugal_bending":
        keys = [
            "blade_mass_kg",
            "rotor_omega_rad_s",
            "cg_radius_m",
            "root_area_mm2",
            "root_section_modulus_mm3",
            "flap_bending_moment_n_m",
            "lag_bending_moment_n_m",
            "ultimate_tensile_mpa",
            "endurance_limit_mpa",
            "safety_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v_blade(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s_m = (p["blade_mass_kg"] * (p["rotor_omega_rad_s"] ** 2) * p["cg_radius_m"]) / p[
                "root_area_mm2"
            ]
            s_f = (p["flap_bending_moment_n_m"] * 1000) / p["root_section_modulus_mm3"]
            s_l = (p["lag_bending_moment_n_m"] * 1000) / p["root_section_modulus_mm3"]
            sf = p["safety_factor"]
            ftu = p["ultimate_tensile_mpa"]
            send = p["endurance_limit_mpa"]
            s.add(
                z3.Or(
                    s_m * sf > ftu,
                    ((ftu - s_m * sf) * send) ** 2 < ((sf * ftu) ** 2) * (s_f * s_f + s_l * s_l),
                )
            )

        return engine.prove_z3_property(
            property_name="rotor_blade_goodman_fatigue_safety",
            bounds=b,
            constants=c,
            assertion="(sigma_cf / F_tu + sigma_alt / S_end) * SF <= 1",
            build_violation=_v_blade,
            proved_reason="Rotor blade root static + Goodman fatigue reserve >= SF",
            cex_reason="Rotor blade root violates static or Goodman fatigue envelope",
        ).to_dict()

    if method_id == "ground_resonance_coleman_screen":
        keys = [
            "rotor_omega_rad_s",
            "blade_lead_lag_freq_rad_s",
            "fuselage_mode_freq_rad_s",
            "blade_lag_damping_ratio",
            "fuselage_damping_ratio",
            "mass_coupling_ratio",
            "min_damping_margin_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v_gr(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            lhs = (
                4
                * p["blade_lag_damping_ratio"]
                * p["fuselage_damping_ratio"]
                * (p["blade_lead_lag_freq_rad_s"] + p["fuselage_mode_freq_rad_s"])
            )
            rhs = p["min_damping_margin_factor"] * p["mass_coupling_ratio"] * p["rotor_omega_rad_s"]
            s.add(lhs < rhs)

        return engine.prove_z3_property(
            property_name="coleman_ground_resonance_damping_stability",
            bounds=b,
            constants=c,
            assertion="zeta_lag * zeta_fus >= min_factor * (mu/4) * Omega / (w_lag + w_fus)",
            build_violation=_v_gr,
            proved_reason="Coleman damping product guarantees ground resonance stability margin",
            cex_reason="Insufficient lag/fuselage damping vs Coleman threshold",
        ).to_dict()

    if method_id == "cs29_crashworthiness_561_562_load":
        keys = [
            "occupant_seat_mass_kg",
            "delta_v_m_s",
            "rise_time_s",
            "attachment_bolt_count",
            "bolt_allowable_load_n",
            "floor_fitting_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v_561(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            cap = p["attachment_bolt_count"] * p["bolt_allowable_load_n"]
            g0 = z3.RealVal("9.80665")
            s.add(
                z3.Or(
                    20 * p["occupant_seat_mass_kg"] * g0 * p["floor_fitting_factor"] > cap,
                    p["occupant_seat_mass_kg"] * p["delta_v_m_s"] * p["floor_fitting_factor"]
                    > cap * p["rise_time_s"],
                )
            )

        return engine.prove_z3_property(
            property_name="cs29_561_562_crash_attachment_safety",
            bounds=b,
            constants=c,
            assertion="max(F_20g_561, F_pulse_562) / N_bolts <= bolt_allowable_load_n",
            build_violation=_v_561,
            proved_reason="Floor attachment bolts satisfy both CS 29.561 20g and CS 29.562 pulse",
            cex_reason="Crashworthiness load per attachment exceeds bolt allowable",
        ).to_dict()

    if method_id == "multirow_bolt_load_distribution":
        keys = ["total_applied_load_n", "bearing_allowable_mpa"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        p_t = float(Decimal(str(merged["pitch_mm"])))
        w = float(Decimal(str(merged["width_mm"])))
        t1 = float(Decimal(str(merged["plate1_thickness_mm"])))
        t2 = float(Decimal(str(merged["plate2_thickness_mm"])))
        e1 = float(Decimal(str(merged["plate1_modulus_mpa"])))
        e2 = float(Decimal(str(merged["plate2_modulus_mpa"])))
        d = float(Decimal(str(merged["bolt_diameter_mm"])))
        eb = float(Decimal(str(merged["bolt_modulus_mpa"])))
        cf = (
            ((t1 + t2) / (2.0 * d)) ** (2.0 / 3.0)
            * 3.0
            * (1.0 / (t1 * e1) + 1.0 / (t2 * e2) + 1.0 / (2.0 * t1 * eb) + 1.0 / (2.0 * t2 * eb))
        )
        cp1 = p_t / (e1 * w * t1)
        cp2 = p_t / (e2 * w * t2)
        t_min_s = _dec_str(min(t1, t2))

        def _v_mr(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            pt = p["total_applied_load_n"]
            f_br = p["bearing_allowable_mpa"]
            r1, r2, r3 = z3.Reals("r1 r2 r3")
            s.add(
                (z3.RealVal(_dec_str(cf + cp1 + cp2)) * r1 - z3.RealVal(_dec_str(cf)) * r2)
                == z3.RealVal(_dec_str(cp1)) * pt
            )
            s.add(
                (
                    z3.RealVal(_dec_str(cp2)) * r1
                    + z3.RealVal(_dec_str(cf + cp2)) * r2
                    - z3.RealVal(_dec_str(cf + cp1)) * r3
                )
                == 0
            )
            s.add(r1 + r2 + r3 == pt)
            cap = f_br * z3.RealVal(_dec_str(d)) * z3.RealVal(t_min_s)
            s.add(z3.Or(r1 > cap, r2 > cap, r3 > cap))

        return engine.prove_z3_property(
            property_name="multirow_bolt_peak_bearing_safety",
            bounds=b,
            constants=c,
            assertion="max(P1, P2, P3) / (d * min(t1, t2)) <= bearing_allowable_mpa",
            build_violation=_v_mr,
            proved_reason="Peak elastic fastener row bearing load stays within F_bru across bounds",
            cex_reason="Critical fastener row exceeds bearing allowable stress",
        ).to_dict()

    if method_id == "larc04_composite_failure":
        keys = [
            "sigma_1_mpa",
            "sigma_2_mpa",
            "tau_12_mpa",
            "x_t_mpa",
            "x_c_mpa",
            "y_t_mpa",
            "y_c_mpa",
            "s_l_mpa",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a0 = float(Decimal(str(merged["alpha_0_deg"])))
        eta_l = float(Decimal(str(merged["eta_l"])))
        g12 = float(Decimal(str(merged["g_12_mpa"])))
        phi0 = float(Decimal(str(merged["phi_0_deg"])))
        eta_t_val = -1.0 / math.tan(math.radians(2.0 * a0))
        ca = math.cos(math.radians(a0))
        sa = math.sin(math.radians(a0))
        st_factor = ca * (sa - eta_t_val * ca)
        s1_lo = _bound_extrema(b, c, "sigma_1_mpa")[0]
        abs_s1_max = min(abs(s1_lo), 0.899 * g12) if s1_lo < 0 else 0.0
        phi_kink_hi = phi0 * g12 / max(1e-6, g12 - abs_s1_max)
        sp_k = math.sin(math.radians(phi_kink_hi))
        cp_k = math.cos(math.radians(phi_kink_hi))
        s2p_k = math.sin(math.radians(2.0 * phi_kink_hi))
        c2p_k = math.cos(math.radians(2.0 * phi_kink_hi))
        z_eta_t = z3.RealVal(_dec_str(eta_t_val))
        z_eta_l = z3.RealVal(_dec_str(eta_l))
        z_ca = z3.RealVal(_dec_str(ca))
        z_sa = z3.RealVal(_dec_str(sa))
        z_st_fac = z3.RealVal(_dec_str(st_factor))
        z_sp_k = z3.RealVal(_dec_str(sp_k))
        z_cp_k = z3.RealVal(_dec_str(cp_k))
        z_s2p_k = z3.RealVal(_dec_str(s2p_k))
        z_c2p_k = z3.RealVal(_dec_str(c2p_k))

        def _v_larc(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s1, s2, t12 = p["sigma_1_mpa"], p["sigma_2_mpa"], p["tau_12_mpa"]
            xt, xc, yt, yc, sl = (
                p["x_t_mpa"],
                p["x_c_mpa"],
                p["y_t_mpa"],
                p["y_c_mpa"],
                p["s_l_mpa"],
            )
            abs_t12 = z3.If(t12 >= 0, t12, -t12)
            # Fiber tension
            viol_ft = z3.And(s1 > 0, s1 > xt)
            # Fiber compression & kinking
            abs_s1 = -s1
            t12m = abs_t12 * z_c2p_k + (abs_s1 + s2) * z_sp_k * z_cp_k
            abs_t12m = z3.If(t12m >= 0, t12m, -t12m)
            s2m = s1 * z_sp_k * z_sp_k + s2 * z_cp_k * z_cp_k - abs_t12 * z_s2p_k
            s2m_neg = z3.If(s2m < 0, s2m, 0)
            t_k_eff = abs_t12m + z_eta_l * s2m_neg
            viol_fc = z3.And(s1 < 0, z3.Or(abs_s1 > xc, t_k_eff > sl))
            # Matrix tension: (s2*sl)^2 + (t12*yt)^2 > (yt*sl)^2
            viol_mt = z3.And(s2 > 0, (s2 * sl) ** 2 + (t12 * yt) ** 2 > (yt * sl) ** 2)
            # Matrix compression
            st = yc * z_st_fac
            sig_n = s2 * z_ca * z_ca
            tau_t = -s2 * z_sa * z_ca
            abs_tau_t = z3.If(tau_t >= 0, tau_t, -tau_t)
            t_eff_t = z3.If(abs_tau_t + z_eta_t * sig_n > 0, abs_tau_t + z_eta_t * sig_n, 0)
            tau_l = abs_t12 * z_ca
            t_eff_l = z3.If(tau_l + z_eta_l * sig_n > 0, tau_l + z_eta_l * sig_n, 0)
            viol_mc = z3.And(s2 < 0, (t_eff_t * sl) ** 2 + (t_eff_l * st) ** 2 > (st * sl) ** 2)
            s.add(z3.Or(viol_ft, viol_fc, viol_mt, viol_mc))

        return engine.prove_z3_property(
            property_name="larc04_composite_envelope_safety",
            bounds=b,
            constants=c,
            assertion="max(FI_ft, FI_fc, FI_mt, FI_mc) <= 1",
            build_violation=_v_larc,
            proved_reason="LaRC04 fiber and matrix failure indices stay <= 1 across bounds",
            cex_reason="LaRC04 composite failure envelope violated (FI > 1)",
        ).to_dict()

    if method_id == "cs29_bird_strike_penetration_screen":
        keys = [
            "bird_density_kg_m3",
            "impact_velocity_m_s",
            "bird_diameter_mm",
            "panel_thickness_mm",
            "panel_shear_allowable_mpa",
            "safety_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)

        def _v_bird(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(
                p["bird_density_kg_m3"]
                * (p["impact_velocity_m_s"] ** 2)
                * p["bird_diameter_mm"]
                * p["safety_factor"]
                > 8000000 * p["panel_thickness_mm"] * p["panel_shear_allowable_mpa"]
            )

        return engine.prove_z3_property(
            property_name="cs29_631_bird_strike_penetration",
            bounds=b,
            constants=c,
            assertion="panel_thickness_mm >= SF * P_stag * d / (4 * tau_allow)",
            build_violation=_v_bird,
            proved_reason="Panel thickness exceeds CS 29.631 bird-strike plug-shear requirement",
            cex_reason="CS 29.631 bird-strike penetration thickness insufficient",
        ).to_dict()

    if method_id == "campbell_rotor_harmonic_clearance":
        keys = [
            "omega_min_rpm",
            "omega_max_rpm",
            "structural_freq_hz",
            "min_clearance_pct",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        b_cnt = int(Decimal(str(merged["blade_count"])))
        orders = (1, b_cnt, 2 * b_cnt, 3 * b_cnt)

        def _v_camp(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            wmin = p["omega_min_rpm"]
            wmax = p["omega_max_rpm"]
            fs = p["structural_freq_hz"]
            m_clr = p["min_clearance_pct"]
            s.add(wmax >= wmin)
            viols = []
            for k in orders:
                f_lo = k * wmin / 60
                f_hi = k * wmax / 60
                # Clear outside [f_lo*(1 - m_clr/100), f_hi*(1 + m_clr/100)]
                safe_k = z3.Or(
                    (f_lo - fs) * 100 >= m_clr * f_lo,
                    (fs - f_hi) * 100 >= m_clr * f_hi,
                )
                viols.append(z3.Not(safe_k))
            s.add(z3.Or(*viols))

        return engine.prove_z3_property(
            property_name="campbell_harmonic_separation",
            bounds=b,
            constants=c,
            assertion=(
                "dist(f_struct, k*[f_min, f_max]) >= min_clearance_pct for k in {1, b, 2b, 3b}"
            ),
            build_violation=_v_camp,
            proved_reason=(
                "Structural mode maintains required Campbell separation across 1P/bP/2bP/3bP"
            ),
            cex_reason="Structural frequency infringes rotor harmonic resonance keep-out band",
        ).to_dict()

    if method_id == "tailboom_boxbeam_combined_stress":
        keys = [
            "bending_moment_n_m",
            "torque_n_m",
            "transverse_shear_n",
            "yield_allowable_mpa",
            "shear_buckling_allowable_mpa",
            "safety_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        bw = float(Decimal(str(merged["box_width_mm"])))
        bh = float(Decimal(str(merged["box_height_mm"])))
        bt = float(Decimal(str(merged["skin_thickness_mm"])))
        ca = float(Decimal(str(merged["cap_area_mm2"])))
        hh = bh / 2.0
        ixx = 4.0 * ca * hh * hh + (bt * (bh**3)) / 6.0 + 2.0 * bw * bt * hh * hh
        k_bm = z3.RealVal(_dec_str(1000.0 * hh / ixx))
        k_tq = z3.RealVal(_dec_str(1000.0 / (2.0 * bw * bh * bt)))
        k_vs = z3.RealVal(_dec_str(1.0 / (2.0 * bh * bt)))

        def _v_tb(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            abm = z3.If(
                p["bending_moment_n_m"] >= 0, p["bending_moment_n_m"], -p["bending_moment_n_m"]
            )
            atq = z3.If(p["torque_n_m"] >= 0, p["torque_n_m"], -p["torque_n_m"])
            avs = z3.If(
                p["transverse_shear_n"] >= 0, p["transverse_shear_n"], -p["transverse_shear_n"]
            )
            sig_b = abm * k_bm
            tau_tot = atq * k_tq + avs * k_vs
            sf = p["safety_factor"]
            vm_sq = sig_b * sig_b + 3 * tau_tot * tau_tot
            s.add(
                z3.Or(
                    (sf * sf) * vm_sq > p["yield_allowable_mpa"] ** 2,
                    sf * tau_tot > p["shear_buckling_allowable_mpa"],
                )
            )

        return engine.prove_z3_property(
            property_name="tailboom_boxbeam_yield_and_buckling",
            bounds=b,
            constants=c,
            assertion="SF*sigma_vm <= F_ty and SF*tau_tot <= tau_cr",
            build_violation=_v_tb,
            proved_reason="Tailboom box-beam satisfies Von Mises yield & skin shear buckling",
            cex_reason="Tailboom box-beam exceeds yield or shear buckling allowable",
        ).to_dict()

    if method_id == "statistical_ab_basis_tolerance_bound":
        keys = ["sample_mean_mpa", "sample_std_mpa", "design_stress_mpa"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        n_bounds = _pair_bounds(
            formal_bounds.get("sample_count", merged["sample_count"]),
            (str(merged["sample_count"]), str(merged["sample_count"])),
        )
        n_lo = max(10.0, float(Decimal(str(n_bounds[0]))))
        # k_A decreases monotonically with n, so n_lo gives worst-case upper k_A.
        ka_hi = 2.326 + math.exp(1.340 - 0.522 * math.log(n_lo) + 3.87 / n_lo)
        z_ka = z3.RealVal(_dec_str(ka_hi))

        def _v_ab(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            a_basis = p["sample_mean_mpa"] - z_ka * p["sample_std_mpa"]
            s.add(z3.Or(a_basis <= 0, a_basis < p["design_stress_mpa"]))

        return engine.prove_z3_property(
            property_name="statistical_a_basis_design_safety",
            bounds=b,
            constants=c,
            assertion="mean - k_A(n) * std >= design_stress_mpa",
            build_violation=_v_ab,
            proved_reason="CMH-17 A-basis lower tolerance bound exceeds design stress",
            cex_reason="Statistical A-basis allowable falls below design stress or <= 0",
        ).to_dict()

    if method_id == "bolt_prying_combined_tension_shear":
        keys = [
            "applied_tension_n",
            "applied_shear_n",
            "applied_bending_n_mm",
            "bolt_tensile_allowable_n",
            "bolt_shear_allowable_n",
            "bolt_bending_allowable_n_mm",
            "safety_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a_lo = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("prying_lever_a_mm", merged["prying_lever_a_mm"]),
                        (str(merged["prying_lever_a_mm"]), str(merged["prying_lever_a_mm"])),
                    )[0]
                )
            )
        )
        b_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("prying_lever_b_mm", merged["prying_lever_b_mm"]),
                        (str(merged["prying_lever_b_mm"]), str(merged["prying_lever_b_mm"])),
                    )[1]
                )
            )
        )
        t_lo = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("flange_thickness_mm", merged["flange_thickness_mm"]),
                        (str(merged["flange_thickness_mm"]), str(merged["flange_thickness_mm"])),
                    )[0]
                )
            )
        )
        q_hi = min(0.65, (b_hi / (2.0 * a_lo)) * (10.0 / (t_lo + 10.0)))
        z_1pq = z3.RealVal(_dec_str(1.0 + q_hi))

        def _v_pry(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            rt = (p["applied_tension_n"] * z_1pq) / p["bolt_tensile_allowable_n"]
            ab_m = z3.If(
                p["applied_bending_n_mm"] >= 0,
                p["applied_bending_n_mm"],
                -p["applied_bending_n_mm"],
            )
            av_s = z3.If(p["applied_shear_n"] >= 0, p["applied_shear_n"], -p["applied_shear_n"])
            rb = ab_m / p["bolt_bending_allowable_n_mm"]
            rs = av_s / p["bolt_shear_allowable_n"]
            s.add((p["safety_factor"] ** 2) * ((rt + rb) ** 2 + (rs**2)) > 1)

        return engine.prove_z3_property(
            property_name="bolt_prying_combined_safety",
            bounds=b,
            constants=c,
            assertion="SF * sqrt((P_tot/P_allow + M/M_allow)^2 + (V/V_allow)^2) <= 1",
            build_violation=_v_pry,
            proved_reason="Bolt satisfies NASA-STD-5020 tension+prying+bending+shear envelope",
            cex_reason="Prying-amplified combined bolt load exceeds interaction envelope",
        ).to_dict()

    if method_id == "goland_reissner_adhesive_peel_shear":
        keys = [
            "tensile_load_per_width_n_mm",
            "peel_allowable_mpa",
            "shear_allowable_mpa",
            "safety_factor",
        ]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        load_lo = _bound_extrema(b, c, "tensile_load_per_width_n_mm")[0]
        lov_lo = float(Decimal(str(merged["overlap_length_mm"])))
        t_adh = float(Decimal(str(merged["adherend_thickness_mm"])))
        e_adh = float(Decimal(str(merged["adherend_modulus_mpa"])))
        t_gl = float(Decimal(str(merged["adhesive_thickness_mm"])))
        e_gl = float(Decimal(str(merged["adhesive_modulus_mpa"])))
        g_gl = float(Decimal(str(merged["adhesive_shear_modulus_mpa"])))
        c_half = lov_lo / 2.0
        u2c_lo = (c_half / t_adh) * math.sqrt((3.0 * load_lo) / (2.0 * e_adh * t_adh))
        k_hi = 1.0 / (1.0 + 2.0 * math.sqrt(2.0) * math.tanh(u2c_lo))
        beta_s = math.sqrt((8.0 * g_gl * t_adh) / (e_adh * t_gl)) * (c_half / t_adh)
        gamma_p = math.sqrt((6.0 * e_gl * t_adh) / (e_adh * t_gl))
        z_ks = z3.RealVal(
            _dec_str((1.0 + 0.25 * (1.0 + 3.0 * k_hi) * (1.0 + beta_s / 4.0)) / lov_lo)
        )
        z_kp = z3.RealVal(_dec_str((k_hi * 0.5 * gamma_p) / t_adh))

        def _v_gr_adh(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            ld = p["tensile_load_per_width_n_mm"]
            pk_peel = ld * z_kp
            pk_shear = ld * z_ks
            idx_sq = (pk_peel / p["peel_allowable_mpa"]) ** 2 + (
                pk_shear / p["shear_allowable_mpa"]
            ) ** 2
            s.add((p["safety_factor"] ** 2) * idx_sq > 1)

        return engine.prove_z3_property(
            property_name="goland_reissner_lap_joint_safety",
            bounds=b,
            constants=c,
            assertion="SF * sqrt((sigma_peel/F_peel)^2 + (tau_peak/F_shear)^2) <= 1",
            build_violation=_v_gr_adh,
            proved_reason="Goland-Reissner adhesive peel & shear interaction stays <= 1/SF",
            cex_reason="Adhesive lap-joint peel/shear peak stress violates margin",
        ).to_dict()

    if method_id == "orthotropic_composite_plate_buckling":
        keys = ["nx_comp_n_per_mm", "ny_comp_n_per_mm", "nxy_shear_n_per_mm", "safety_factor"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        la = float(Decimal(str(merged["plate_length_a_mm"])))
        wb = float(Decimal(str(merged["plate_width_b_mm"])))
        d11 = float(Decimal(str(merged["d11_n_mm"])))
        d22 = float(Decimal(str(merged["d22_n_mm"])))
        d12 = float(Decimal(str(merged["d12_n_mm"])))
        d66 = float(Decimal(str(merged["d66_n_mm"])))
        h_eff = d12 + 2.0 * d66
        d_sqrt = math.sqrt(d11 * d22)
        pi_sq = math.pi * math.pi
        nx_cr = (2.0 * pi_sq / (wb * wb)) * (d_sqrt + h_eff)
        ny_cr = (2.0 * pi_sq / (la * la)) * (d_sqrt + h_eff)
        theta_s = d_sqrt / h_eff
        k_s = 3.2 + 2.1 / (theta_s + 0.5)
        d_fourth = (d11 * (d22**3)) ** 0.25
        nxy_cr = (4.0 * k_s / (wb * wb)) * d_fourth
        z_nxcr = z3.RealVal(_dec_str(nx_cr))
        z_nycr = z3.RealVal(_dec_str(ny_cr))
        z_nxycr = z3.RealVal(_dec_str(nxy_cr))

        def _v_ortho(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            nx_p = z3.If(p["nx_comp_n_per_mm"] > 0, p["nx_comp_n_per_mm"], 0)
            ny_p = z3.If(p["ny_comp_n_per_mm"] > 0, p["ny_comp_n_per_mm"], 0)
            nxy_a = z3.If(
                p["nxy_shear_n_per_mm"] >= 0, p["nxy_shear_n_per_mm"], -p["nxy_shear_n_per_mm"]
            )
            rx = nx_p / z_nxcr
            ry = ny_p / z_nycr
            rxy = nxy_a / z_nxycr
            s.add(p["safety_factor"] * (rx + ry + rxy * rxy) > 1)

        return engine.prove_z3_property(
            property_name="orthotropic_plate_buckling_safety",
            bounds=b,
            constants=c,
            assertion="SF * (R_x + R_y + R_xy^2) <= 1",
            build_violation=_v_ortho,
            proved_reason="Orthotropic composite panel buckling interaction stays <= 1/SF",
            cex_reason="Orthotropic composite panel exceeds buckling interaction limit",
        ).to_dict()

    if method_id == "skin_stringer_crippling_interaction":
        keys = ["applied_compression_n", "safety_factor"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        l_pan = float(Decimal(str(merged["panel_length_mm"])))
        pitch = float(Decimal(str(merged["stringer_pitch_mm"])))
        t_sk = float(Decimal(str(merged["skin_thickness_mm"])))
        a_str = float(Decimal(str(merged["stringer_area_mm2"])))
        f_cc = float(Decimal(str(merged["stringer_crippling_mpa"])))
        i_pan = float(Decimal(str(merged["panel_inertia_mm4"])))
        c_fix = float(Decimal(str(merged["end_fixity_c"])))
        em = float(Decimal(str(merged["modulus_mpa"])))
        f_y = float(Decimal(str(merged["skin_yield_mpa"])))
        w_eff = min(pitch, 1.9 * t_sk * math.sqrt(em / f_y))
        a_eff = a_str + w_eff * t_sk
        sig_cc = (a_str * f_cc + w_eff * t_sk * f_y) / a_eff
        rho_g = math.sqrt(i_pan / a_eff)
        slend = l_pan / (rho_g * math.sqrt(c_fix))
        pi_sq = math.pi * math.pi
        lam_c = math.sqrt(2.0 * pi_sq * em / sig_cc)
        if slend <= lam_c:
            sig_cr = sig_cc * (1.0 - (sig_cc * slend * slend) / (4.0 * pi_sq * em))
        else:
            sig_cr = (pi_sq * em) / (slend * slend)
        z_cap = z3.RealVal(_dec_str(sig_cr * a_eff))

        def _v_ss(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(p["applied_compression_n"] * p["safety_factor"] > z_cap)

        return engine.prove_z3_property(
            property_name="skin_stringer_crippling_safety",
            bounds=b,
            constants=c,
            assertion="applied_compression_n * SF <= sigma_cr_euler_johnson * A_eff",
            build_violation=_v_ss,
            proved_reason=(
                "Skin-stringer panel compressive capacity satisfies crippling + Euler-Johnson"
            ),
            cex_reason="Skin-stringer compression load exceeds crippling/column capacity",
        ).to_dict()

    if method_id == "walker_mean_stress_crack_growth":
        keys = ["required_cycles", "scatter_factor"]
        b, c = _split_bounds_and_consts(merged, formal_bounds, keys)
        a0_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("initial_crack_a0_mm", merged["initial_crack_a0_mm"]),
                        (
                            str(merged["initial_crack_a0_mm"]),
                            str(merged["initial_crack_a0_mm"]),
                        ),
                    )[1]
                )
            )
        )
        sig_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("sigma_max_mpa", merged["sigma_max_mpa"]),
                        (str(merged["sigma_max_mpa"]), str(merged["sigma_max_mpa"])),
                    )[1]
                )
            )
        )
        r_lo = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("stress_ratio_r", merged["stress_ratio_r"]),
                        (str(merged["stress_ratio_r"]), str(merged["stress_ratio_r"])),
                    )[0]
                )
            )
        )
        beta_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("geometry_factor_beta", merged["geometry_factor_beta"]),
                        (
                            str(merged["geometry_factor_beta"]),
                            str(merged["geometry_factor_beta"]),
                        ),
                    )[1]
                )
            )
        )
        kic_lo = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get(
                            "fracture_toughness_kic_mpa_sqrt_m",
                            merged["fracture_toughness_kic_mpa_sqrt_m"],
                        ),
                        (
                            str(merged["fracture_toughness_kic_mpa_sqrt_m"]),
                            str(merged["fracture_toughness_kic_mpa_sqrt_m"]),
                        ),
                    )[0]
                )
            )
        )
        wc_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("walker_c", merged["walker_c"]),
                        (str(merged["walker_c"]), str(merged["walker_c"])),
                    )[1]
                )
            )
        )
        wm_hi = float(
            Decimal(
                str(
                    _pair_bounds(
                        formal_bounds.get("walker_m", merged["walker_m"]),
                        (str(merged["walker_m"]), str(merged["walker_m"])),
                    )[1]
                )
            )
        )
        g_bounds = _pair_bounds(
            formal_bounds.get("walker_gamma", merged["walker_gamma"]),
            (str(merged["walker_gamma"]), str(merged["walker_gamma"])),
        )
        g_lo = float(Decimal(str(g_bounds[0])))
        g_hi = float(Decimal(str(g_bounds[1])))
        base_1mr = max(0.05, 1.0 - r_lo)
        ds_eff = sig_hi * max(base_1mr**g_lo, base_1mr**g_hi)
        a0_m = a0_hi / 1000.0
        ac_m = ((kic_lo / (beta_hi * sig_hi)) ** 2) / math.pi
        if ac_m <= a0_m:
            life_lo = 0.0
        else:
            p_exp = 1.0 - (wm_hi / 2.0)
            denom_c = wc_hi * ((beta_hi * ds_eff * math.sqrt(math.pi)) ** wm_hi)
            life_lo = ((ac_m**p_exp) - (a0_m**p_exp)) / (p_exp * denom_c)
        z_life = z3.RealVal(_dec_str(life_lo))

        def _v_wlk(s: z3.Solver, zv: dict[str, Any], zc: dict[str, Any]) -> None:
            p = {**zv, **zc}
            s.add(z_life < p["required_cycles"] * p["scatter_factor"])

        return engine.prove_z3_property(
            property_name="walker_damage_tolerance_life_safety",
            bounds=b,
            constants=c,
            assertion="N_f_walker / scatter_factor >= required_cycles",
            build_violation=_v_wlk,
            proved_reason="Walker R-ratio safe inspection life exceeds required cycles",
            cex_reason="Walker factored crack growth life falls below required cycles",
        ).to_dict()

    return {
        "property_name": f"{method_id}_formal_bounds",
        "proved": False,
        "status": "UNSUPPORTED_METHOD",
        "method_id": method_id,
    }
