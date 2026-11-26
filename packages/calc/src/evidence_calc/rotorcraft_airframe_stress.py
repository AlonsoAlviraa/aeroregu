"""Four Rotorcraft & Airframe Structural Stress Methods (Exact Decimal Precision).

Methods:
1. composite_bolted_joint_bearing_tension_shear - CMH-17 composite bolted joint multi-mode MS
2. rotor_hub_elastomeric_bearing_strain         - CS-29 hub elastomeric bearing equiv strain MS
3. cs29_ditching_water_impact_panel             - CS 29.801 Wagner deadrise ditching panel MS
4. pressure_bulkhead_hoop_longitudinal_stress   - Thin-walled pressure vessel biaxial + LEFM MS
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.rotorcraft_stress_ext import _tan_deg
from evidence_calc.stress_manual import (
    _ONE,
    _PI,
    _TWO,
    _ZERO,
    _d,
    _nonneg,
    _pos,
    quantize,
)

_THREE = Decimal("3")
_FOUR_FIVE = Decimal("4.5")
_HALF = Decimal("0.5")
_THOUSAND = Decimal("1000")
_MILLION = Decimal("1000000")
_MIN_DEADRISE = Decimal("2")
_MAX_DEADRISE = Decimal("60")


def run_composite_bolted_joint_bearing_tension_shear(inputs: dict[str, Any]) -> dict[str, str]:
    """Screen CMH-17 composite single-fastener joint in bearing, net tension, and shear-out."""
    with localcontext() as ctx:
        ctx.prec = 55
        load_n = _pos(inputs["applied_load_n"], "applied_load_n")
        d_mm = _pos(inputs["bolt_diameter_mm"], "bolt_diameter_mm")
        thk_mm = _pos(inputs["laminate_thickness_mm"], "laminate_thickness_mm")
        e_mm = _pos(inputs["edge_distance_e_mm"], "edge_distance_e_mm")
        w_mm = _pos(inputs["strip_width_w_mm"], "strip_width_w_mm")
        f_br = _pos(inputs["bearing_allowable_mpa"], "bearing_allowable_mpa")
        f_oht = _pos(inputs["oht_allowable_mpa"], "oht_allowable_mpa")
        f_so = _pos(inputs["shear_out_allowable_mpa"], "shear_out_allowable_mpa")
        kd = _pos(inputs["knockdown_factor"], "knockdown_factor")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        net_width = w_mm - d_mm
        shear_out_arm = e_mm - (d_mm * _HALF)
        if net_width <= _ZERO or shear_out_arm <= _ZERO:
            raise AbstainError("outside_validity")

        sig_br = load_n / (d_mm * thk_mm)
        sig_nt = load_n / (net_width * thk_mm)
        tau_so = load_n / (_TWO * shear_out_arm * thk_mm)

        ms_br = ((kd * f_br) / (sf * sig_br)) - _ONE
        ms_nt = ((kd * f_oht) / (sf * sig_nt)) - _ONE
        ms_so = ((kd * f_so) / (sf * tau_so)) - _ONE
        gov_ms = min(ms_br, ms_nt, ms_so)

        return {
            "bearing_stress_mpa": quantize(sig_br, "0.0001"),
            "net_tension_stress_mpa": quantize(sig_nt, "0.0001"),
            "shear_out_stress_mpa": quantize(tau_so, "0.0001"),
            "bearing_ms": quantize(ms_br, "0.0001"),
            "net_tension_ms": quantize(ms_nt, "0.0001"),
            "shear_out_ms": quantize(ms_so, "0.0001"),
            "governing_ms": quantize(gov_ms, "0.0001"),
        }


def run_rotor_hub_elastomeric_bearing_strain(inputs: dict[str, Any]) -> dict[str, str]:
    """Evaluate elastomeric rotor hub bearing combined compression and shear equivalent strain."""
    with localcontext() as ctx:
        ctx.prec = 55
        f_cf = _pos(inputs["axial_cf_load_n"], "axial_cf_load_n")
        area = _pos(inputs["bonded_area_mm2"], "bonded_area_mm2")
        t_layer = _pos(inputs["layer_thickness_mm"], "layer_thickness_mm")
        n_layers = _pos(inputs["num_layers"], "num_layers")
        g_mpa = _pos(inputs["elastomer_shear_modulus_mpa"], "elastomer_shear_modulus_mpa")
        s_fac = _pos(inputs["shape_factor_s"], "shape_factor_s")
        delta_s = _nonneg(inputs["shear_deflection_mm"], "shear_deflection_mm")
        k_wt = _pos(inputs["compression_strain_weight_k"], "compression_strain_weight_k")
        eps_allow = _pos(inputs["allowable_equiv_strain"], "allowable_equiv_strain")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        e_c = g_mpa * (_THREE + (_FOUR_FIVE * s_fac * s_fac))
        sig_c = f_cf / area
        eps_c = sig_c / e_c
        gamma_s = delta_s / (n_layers * t_layer)
        gamma_eq = ((k_wt * eps_c) ** 2 + (gamma_s * gamma_s)).sqrt()
        if gamma_eq <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (eps_allow / (sf * gamma_eq)) - _ONE

        return {
            "effective_compression_modulus_mpa": quantize(e_c, "0.01"),
            "compressive_stress_mpa": quantize(sig_c, "0.0001"),
            "compressive_strain": quantize(eps_c, "0.00001"),
            "shear_strain": quantize(gamma_s, "0.00001"),
            "equivalent_octahedral_strain": quantize(gamma_eq, "0.00001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_cs29_ditching_water_impact_panel(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute CS 29.801 Wagner deadrise wedge water-entry impact pressure and plate MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        v_z = _pos(inputs["vertical_sink_speed_m_s"], "vertical_sink_speed_m_s")
        rho_w = _pos(inputs["water_density_kg_m3"], "water_density_kg_m3")
        beta_deg = _d(inputs["deadrise_angle_deg"], "deadrise_angle_deg")
        _pos(inputs["panel_span_a_mm"], "panel_span_a_mm")
        b_mm = _pos(inputs["panel_width_b_mm"], "panel_width_b_mm")
        t_mm = _pos(inputs["panel_thickness_t_mm"], "panel_thickness_t_mm")
        beta_plate = _pos(inputs["bending_coeff_beta"], "bending_coeff_beta")
        fy_mpa = _pos(inputs["yield_allowable_mpa"], "yield_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        if beta_deg <= _MIN_DEADRISE or beta_deg >= _MAX_DEADRISE:
            raise AbstainError("outside_validity")

        tan_beta = _tan_deg(beta_deg)
        c_p = (_PI / (_TWO * tan_beta)) ** 2
        p_imp_mpa = (_HALF * rho_w * v_z * v_z * (_ONE + c_p)) / _MILLION
        sig_bend = beta_plate * p_imp_mpa * ((b_mm / t_mm) ** 2)
        ms = (fy_mpa / (sf * sig_bend)) - _ONE

        return {
            "deadrise_tan_beta": quantize(tan_beta, "0.0001"),
            "wagner_pressure_coeff": quantize(c_p, "0.0001"),
            "impact_pressure_mpa": quantize(p_imp_mpa, "0.0001"),
            "panel_bending_stress_mpa": quantize(sig_bend, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_pressure_bulkhead_hoop_longitudinal_stress(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute pressurized cabin/fuel-cell shell biaxial + torsion von Mises and LEFM K_I MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        delta_p = _pos(inputs["internal_delta_p_mpa"], "internal_delta_p_mpa")
        r_mm = _pos(inputs["cylinder_radius_mm"], "cylinder_radius_mm")
        t_mm = _pos(inputs["wall_thickness_mm"], "wall_thickness_mm")
        t_nm = _nonneg(inputs["applied_torsion_nm"], "applied_torsion_nm")
        fy = _pos(inputs["yield_allowable_mpa"], "yield_allowable_mpa")
        k_ic = _pos(
            inputs["fracture_toughness_kic_mpa_sqrt_m"],
            "fracture_toughness_kic_mpa_sqrt_m",
        )
        a_mm = _pos(inputs["half_crack_length_a_mm"], "half_crack_length_a_mm")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        sig_h = (delta_p * r_mm) / t_mm
        sig_l = (delta_p * r_mm) / (_TWO * t_mm)
        tau_t = (t_nm * _THOUSAND) / (_TWO * _PI * r_mm * r_mm * t_mm)
        sig_vm = (
            (sig_h * sig_h) - (sig_h * sig_l) + (sig_l * sig_l) + (_THREE * tau_t * tau_t)
        ).sqrt()
        if sig_vm <= _ZERO:
            raise AbstainError("outside_validity")
        ms_yield = (fy / (sf * sig_vm)) - _ONE

        a_m = a_mm / _THOUSAND
        k_applied = sig_h * (_PI * a_m).sqrt()
        ms_frac = (k_ic / (sf * k_applied)) - _ONE
        gov_ms = min(ms_yield, ms_frac)

        return {
            "hoop_stress_mpa": quantize(sig_h, "0.0001"),
            "longitudinal_stress_mpa": quantize(sig_l, "0.0001"),
            "torsional_shear_mpa": quantize(tau_t, "0.0001"),
            "von_mises_stress_mpa": quantize(sig_vm, "0.0001"),
            "stress_intensity_k_mpa_sqrt_m": quantize(k_applied, "0.0001"),
            "yield_ms": quantize(ms_yield, "0.0001"),
            "fracture_ms": quantize(ms_frac, "0.0001"),
            "governing_ms": quantize(gov_ms, "0.0001"),
        }


def _card_runner(fn: Any) -> Any:
    def _run(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
        return {
            "method_id": card["method_id"],
            "method_version": card["method_version"],
            "outputs": fn(inputs),
            "label": card.get("label", "ASSUMPTION"),
            "sources": card.get("sources", []),
        }

    return _run


ROTORCRAFT_AIRFRAME_CARD_RUNNERS: dict[str, Any] = {
    "composite_bolted_joint_bearing_tension_shear": _card_runner(
        run_composite_bolted_joint_bearing_tension_shear
    ),
    "rotor_hub_elastomeric_bearing_strain": _card_runner(run_rotor_hub_elastomeric_bearing_strain),
    "cs29_ditching_water_impact_panel": _card_runner(run_cs29_ditching_water_impact_panel),
    "pressure_bulkhead_hoop_longitudinal_stress": _card_runner(
        run_pressure_bulkhead_hoop_longitudinal_stress
    ),
}
