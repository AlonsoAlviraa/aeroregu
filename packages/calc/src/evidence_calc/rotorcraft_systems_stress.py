"""Four Rotorcraft Systems, Propulsion & Landing-Gear Stress Methods (Exact Decimal Precision).

Methods:
1. cs29_skid_landing_gear_drop_energy  - CS 29.725/727 skid landing-gear drop energy & cross-tube MS
2. shaft_whirl_critical_speed_screen    - Tail-rotor driveshaft critical whirl speed MS
3. firewall_thermal_buckling_screen     - CS 29.1191 constrained thermal buckling & yield MS
4. hertzian_bearing_contact_stress      - Cylindrical roller/raceway Hertzian contact & shear MS
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.stress_manual import (
    _ONE,
    _PI,
    _TWO,
    _ZERO,
    _d,
    _pos,
    quantize,
)

_FOUR = Decimal("4")
_TWELVE = Decimal("12")
_SIXTY = Decimal("60")
_SIXTY_FOUR = Decimal("64")
_THOUSAND = Decimal("1000")
_MILLION = Decimal("1000000")
_G0 = Decimal("9.80665")


def run_cs29_skid_landing_gear_drop_energy(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute CS 29.725/29.727 skid gear drop energy absorption, load factor, and tube MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        w_kg = _pos(inputs["gross_weight_kg"], "gross_weight_kg")
        h_drop = _pos(inputs["drop_height_m"], "drop_height_m")
        kl = _d(inputs["rotor_lift_fraction"], "rotor_lift_fraction")
        stroke = _pos(inputs["vertical_stroke_m"], "vertical_stroke_m")
        eta = _pos(inputs["gear_efficiency_eta"], "gear_efficiency_eta")
        od = _pos(inputs["cross_tube_od_mm"], "cross_tube_od_mm")
        wall = _pos(inputs["cross_tube_wall_mm"], "cross_tube_wall_mm")
        arm = _pos(inputs["cantilever_arm_mm"], "cantilever_arm_mm")
        fy = _pos(inputs["yield_allowable_mpa"], "yield_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        if kl < _ZERO or kl >= _ONE:
            raise AbstainError("outside_validity")
        if eta > _ONE:
            raise AbstainError("outside_validity")
        d_in = od - (_TWO * wall)
        if d_in <= _ZERO:
            raise AbstainError("outside_validity")

        weight_n = w_kg * _G0
        e_drop_j = weight_n * (h_drop + (_ONE - kl) * stroke)
        n_z = e_drop_j / (weight_n * stroke * eta)
        f_leg_n = Decimal("0.25") * n_z * weight_n
        i_tube = _PI * ((od**4) - (d_in**4)) / _SIXTY_FOUR
        z_mod = i_tube / (od / _TWO)
        sigma_bend = (f_leg_n * arm) / z_mod
        ms = (fy / (sf * sigma_bend)) - _ONE

        return {
            "total_drop_energy_j": quantize(e_drop_j, "0.001"),
            "landing_load_factor_nz": quantize(n_z, "0.0001"),
            "skid_leg_reaction_n": quantize(f_leg_n, "0.01"),
            "tube_section_modulus_mm3": quantize(z_mod, "0.01"),
            "cross_tube_bending_mpa": quantize(sigma_bend, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_shaft_whirl_critical_speed_screen(inputs: dict[str, Any]) -> dict[str, str]:
    """Evaluate Euler/Rayleigh first critical whirl speed and overspeed margin of a hollow shaft."""
    with localcontext() as ctx:
        ctx.prec = 55
        l_mm = _pos(inputs["shaft_length_mm"], "shaft_length_mm")
        d_o = _pos(inputs["outer_diameter_mm"], "outer_diameter_mm")
        d_i = _d(inputs["inner_diameter_mm"], "inner_diameter_mm")
        e_mpa = _pos(inputs["youngs_modulus_mpa"], "youngs_modulus_mpa")
        rho = _pos(inputs["density_kg_m3"], "density_kg_m3")
        lam = _pos(inputs["bearing_fixity_lambda"], "bearing_fixity_lambda")
        op_rpm = _pos(inputs["operating_rpm"], "operating_rpm")
        os_fac = _pos(inputs["overspeed_factor"], "overspeed_factor")

        if d_i < _ZERO or d_i >= d_o:
            raise AbstainError("outside_validity")
        if os_fac < _ONE:
            raise AbstainError("outside_validity")

        area_mm2 = _PI * ((d_o * d_o) - (d_i * d_i)) / _FOUR
        i_mm4 = _PI * ((d_o**4) - (d_i**4)) / _SIXTY_FOUR
        r_g_mm = (i_mm4 / area_mm2).sqrt()
        wave_speed_mm_s = ((e_mpa * _MILLION) / rho).sqrt() * _THOUSAND
        omega_rad_s = ((lam / l_mm) ** 2) * r_g_mm * wave_speed_mm_s
        f_hz = omega_rad_s / (_TWO * _PI)
        n_cr_rpm = f_hz * _SIXTY
        whirl_ratio = n_cr_rpm / op_rpm
        ms = (n_cr_rpm / (op_rpm * os_fac)) - _ONE

        return {
            "section_area_mm2": quantize(area_mm2, "0.01"),
            "section_inertia_mm4": quantize(i_mm4, "0.01"),
            "first_whirl_freq_hz": quantize(f_hz, "0.001"),
            "critical_whirl_rpm": quantize(n_cr_rpm, "0.01"),
            "whirl_speed_ratio": quantize(whirl_ratio, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_firewall_thermal_buckling_screen(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute CS 29.1191 engine-bay firewall constrained thermal stress, buckling, and yield MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        wid = _pos(inputs["panel_width_b_mm"], "panel_width_b_mm")
        thk = _pos(inputs["panel_thickness_t_mm"], "panel_thickness_t_mm")
        e_hot = _pos(inputs["youngs_modulus_hot_mpa"], "youngs_modulus_hot_mpa")
        nu = _d(inputs["poissons_ratio"], "poissons_ratio")
        cte = _pos(inputs["cte_per_c"], "cte_per_c")
        dtemp = _pos(inputs["delta_temp_c"], "delta_temp_c")
        k_res = _pos(inputs["restraint_factor"], "restraint_factor")
        kc = _pos(inputs["plate_buckling_kc"], "plate_buckling_kc")
        fy_hot = _pos(inputs["hot_yield_allowable_mpa"], "hot_yield_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        if nu < _ZERO or nu >= Decimal("0.5"):
            raise AbstainError("outside_validity")
        if k_res > _ONE:
            raise AbstainError("outside_validity")

        sigma_th = k_res * e_hot * cte * dtemp
        denom = _TWELVE * (_ONE - (nu * nu))
        sigma_cr = (kc * (_PI * _PI) * e_hot / denom) * ((thk / wid) ** 2)
        b_ms = (sigma_cr / (sf * sigma_th)) - _ONE
        y_ms = (fy_hot / (sf * sigma_th)) - _ONE
        gov_ms = b_ms if b_ms <= y_ms else y_ms

        return {
            "thermal_compressive_stress_mpa": quantize(sigma_th, "0.0001"),
            "critical_buckling_stress_mpa": quantize(sigma_cr, "0.0001"),
            "buckling_ms": quantize(b_ms, "0.0001"),
            "yield_ms": quantize(y_ms, "0.0001"),
            "governing_ms": quantize(gov_ms, "0.0001"),
        }


def run_hertzian_bearing_contact_stress(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute Hertzian line-contact peak pressure p0, subsurface tau_max, and static MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        load_n = _pos(inputs["normal_load_n"], "normal_load_n")
        len_mm = _pos(inputs["contact_length_mm"], "contact_length_mm")
        d1 = _pos(inputs["roller_diameter_mm"], "roller_diameter_mm")
        d2 = _pos(inputs["raceway_diameter_mm"], "raceway_diameter_mm")
        e1 = _pos(inputs["youngs_modulus_1_mpa"], "youngs_modulus_1_mpa")
        nu1 = _d(inputs["poissons_ratio_1"], "poissons_ratio_1")
        e2 = _pos(inputs["youngs_modulus_2_mpa"], "youngs_modulus_2_mpa")
        nu2 = _d(inputs["poissons_ratio_2"], "poissons_ratio_2")
        p_allow = _pos(inputs["contact_allowable_mpa"], "contact_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        if nu1 < _ZERO or nu1 >= Decimal("0.5") or nu2 < _ZERO or nu2 >= Decimal("0.5"):
            raise AbstainError("outside_validity")

        inv_e_star = ((_ONE - (nu1 * nu1)) / e1) + ((_ONE - (nu2 * nu2)) / e2)
        e_star = _ONE / inv_e_star
        r_eq = (d1 * d2) / (_TWO * (d1 + d2))
        b_half = ((_FOUR * load_n * r_eq) / (_PI * len_mm * e_star)).sqrt()
        p0 = (_TWO * load_n) / (_PI * b_half * len_mm)
        tau_max = Decimal("0.300") * p0
        z_depth = Decimal("0.786") * b_half
        ms = (p_allow / (sf * p0)) - _ONE

        return {
            "effective_modulus_mpa": quantize(e_star, "0.01"),
            "equivalent_radius_mm": quantize(r_eq, "0.0001"),
            "contact_half_width_mm": quantize(b_half, "0.0001"),
            "peak_contact_pressure_mpa": quantize(p0, "0.0001"),
            "max_subsurface_shear_mpa": quantize(tau_max, "0.0001"),
            "shear_depth_z_mm": quantize(z_depth, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def _wrap_card(fn: Any) -> Any:
    def _runner(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
        return {
            "method_id": card["method_id"],
            "method_version": card["method_version"],
            "outputs": fn(inputs),
            "label": card.get("label", "ESTIMATE"),
            "sources": card.get("sources", []),
        }

    return _runner


ROTORCRAFT_SYSTEMS_CARD_RUNNERS: dict[str, Any] = {
    "cs29_skid_landing_gear_drop_energy": _wrap_card(run_cs29_skid_landing_gear_drop_energy),
    "shaft_whirl_critical_speed_screen": _wrap_card(run_shaft_whirl_critical_speed_screen),
    "firewall_thermal_buckling_screen": _wrap_card(run_firewall_thermal_buckling_screen),
    "hertzian_bearing_contact_stress": _wrap_card(run_hertzian_bearing_contact_stress),
}
