"""Five Additional Rotorcraft & Composite Stress Office Methods (Exact Decimal Precision).

Methods:
1. larc04_composite_failure           - NASA LaRC04 (Pinho) matrix & fiber kinking failure criteria
2. cs29_bird_strike_penetration_screen - CS 29.631 1-kg bird-strike stagnation & penetration MS
3. campbell_rotor_harmonic_clearance  - Rotorcraft Campbell 1P / bP / 2bP / 3bP harmonic clearance
4. tailboom_boxbeam_combined_stress   - Thin-walled fuselage/tailboom bending + Bredt + shear MS
5. statistical_ab_basis_tolerance_bound - CMH-17 / MMPDS normal one-sided A-basis & B-basis bounds
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.rotorcraft_stress import _wrap_rotorcraft_card_runner
from evidence_calc.stress_manual import (
    _ONE,
    _PI,
    _TWO,
    _ZERO,
    _cos_deg,
    _d,
    _ln,
    _pos,
    _sin_deg,
    quantize,
)

_THREE = Decimal("3")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_HUNDRED = Decimal("100")
_THOUSAND = Decimal("1000")
_MILLION = Decimal("1000000")


def _tan_deg(deg: Decimal) -> Decimal:
    cos_v = _cos_deg(deg)
    if abs(cos_v) <= Decimal("1e-24"):
        raise AbstainError("outside_validity")
    return _sin_deg(deg) / cos_v


def run_larc04_composite_failure(inputs: dict[str, Any]) -> dict[str, str]:
    """Evaluate NASA LaRC04 3D/in-plane composite matrix and fiber kinking failure indices."""
    with localcontext() as ctx:
        ctx.prec = 55
        sig1 = _d(inputs["sigma_1_mpa"], "sigma_1_mpa")
        sig2 = _d(inputs["sigma_2_mpa"], "sigma_2_mpa")
        tau12 = _d(inputs["tau_12_mpa"], "tau_12_mpa")
        xt = _pos(inputs["x_t_mpa"], "x_t_mpa")
        xc = _pos(inputs["x_c_mpa"], "x_c_mpa")
        yt = _pos(inputs["y_t_mpa"], "y_t_mpa")
        yc = _pos(inputs["y_c_mpa"], "y_c_mpa")
        sl = _pos(inputs["s_l_mpa"], "s_l_mpa")
        alpha0 = _d(inputs["alpha_0_deg"], "alpha_0_deg")
        eta_l = _d(inputs["eta_l"], "eta_l")
        g12 = _pos(inputs["g_12_mpa"], "g_12_mpa")
        phi0 = _d(inputs["phi_0_deg"], "phi_0_deg")

        if alpha0 <= Decimal("45") or alpha0 >= Decimal("89"):
            raise AbstainError("outside_validity")
        if phi0 <= _ZERO or phi0 >= Decimal("15"):
            raise AbstainError("outside_validity")
        if eta_l < _ZERO or eta_l > Decimal("1"):
            raise AbstainError("outside_validity")

        # 1. Fiber tension
        fi_ft = (sig1 / xt) if sig1 > _ZERO else _ZERO

        # 2. Fiber compression (kinking with shear nonlinearity & transverse friction)
        if sig1 < _ZERO:
            abs_s1 = -sig1
            if abs_s1 >= Decimal("0.9") * g12:
                raise AbstainError("outside_validity")
            phi_kink = phi0 * g12 / (g12 - abs_s1)
            if phi_kink >= Decimal("45"):
                raise AbstainError("outside_validity")
            c_phi = _cos_deg(phi_kink)
            s_phi = _sin_deg(phi_kink)
            c2p = _cos_deg(_TWO * phi_kink)
            s2p = _sin_deg(_TWO * phi_kink)
            abs_t12 = abs(tau12)
            tau12m = abs_t12 * c2p + (abs_s1 + sig2) * s_phi * c_phi
            sig2m = sig1 * s_phi * s_phi + sig2 * c_phi * c_phi - abs_t12 * s2p
            tau_k_eff = abs(tau12m) + eta_l * (sig2m if sig2m < _ZERO else _ZERO)
            if tau_k_eff < _ZERO:
                tau_k_eff = _ZERO
            fi_fc = max(abs_s1 / xc, tau_k_eff / sl)
        else:
            phi_kink = phi0
            fi_fc = _ZERO

        # 3. Matrix tension
        if sig2 > _ZERO:
            fi_mt = ((sig2 / yt) ** 2 + (tau12 / sl) ** 2).sqrt()
        else:
            fi_mt = _ZERO

        # 4. Matrix compression (Mohr-Coulomb fracture plane alpha0)
        eta_t = -_ONE / _tan_deg(_TWO * alpha0)
        c_a = _cos_deg(alpha0)
        s_a = _sin_deg(alpha0)
        st = yc * c_a * (s_a - eta_t * c_a)
        if st <= _ZERO:
            raise AbstainError("outside_validity")
        if sig2 < _ZERO:
            sig_n = sig2 * c_a * c_a
            tau_t = -sig2 * s_a * c_a
            tau_l = abs(tau12) * c_a
            tau_eff_t = abs(tau_t) + eta_t * sig_n
            if tau_eff_t < _ZERO:
                tau_eff_t = _ZERO
            tau_eff_l = tau_l + eta_l * sig_n
            if tau_eff_l < _ZERO:
                tau_eff_l = _ZERO
            fi_mc = ((tau_eff_t / st) ** 2 + (tau_eff_l / sl) ** 2).sqrt()
        else:
            fi_mc = _ZERO

        gov_fi = max(fi_ft, fi_fc, fi_mt, fi_mc)
        if gov_fi <= Decimal("1e-12"):
            ms = Decimal("99")
        else:
            ms = (_ONE / gov_fi) - _ONE

        return {
            "eta_t_transverse": quantize(eta_t, "0.0001"),
            "transverse_shear_strength_st_mpa": quantize(st, "0.0001"),
            "kink_angle_deg": quantize(phi_kink, "0.0001"),
            "fi_fiber_tension": quantize(fi_ft, "0.0001"),
            "fi_fiber_compression": quantize(fi_fc, "0.0001"),
            "fi_matrix_tension": quantize(fi_mt, "0.0001"),
            "fi_matrix_compression": quantize(fi_mc, "0.0001"),
            "governing_failure_index": quantize(gov_fi, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_cs29_bird_strike_penetration_screen(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute CS 29.631 1 kg bird-strike stagnation pressure, impact force, & thickness MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        m_bird = _pos(inputs["bird_mass_kg"], "bird_mass_kg")
        vel = _pos(inputs["impact_velocity_m_s"], "impact_velocity_m_s")
        rho = _pos(inputs["bird_density_kg_m3"], "bird_density_kg_m3")
        diam = _pos(inputs["bird_diameter_mm"], "bird_diameter_mm")
        t_panel = _pos(inputs["panel_thickness_mm"], "panel_thickness_mm")
        tau_allow = _pos(inputs["panel_shear_allowable_mpa"], "panel_shear_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        ke_j = (m_bird * vel * vel) / _TWO
        p_stag_mpa = (rho * vel * vel) / (_TWO * _MILLION)
        radius = diam / _TWO
        area_mm2 = _PI * radius * radius
        f_eq_n = p_stag_mpa * area_mm2
        req_t = (f_eq_n * sf) / (_PI * diam * tau_allow)
        if req_t <= _ZERO:
            raise AbstainError("outside_validity")
        applied_shear = f_eq_n / (_PI * diam * t_panel)
        ms = (t_panel / req_t) - _ONE

        return {
            "kinetic_energy_j": quantize(ke_j, "0.0001"),
            "stagnation_pressure_mpa": quantize(p_stag_mpa, "0.0001"),
            "impact_area_mm2": quantize(area_mm2, "0.0001"),
            "equivalent_impact_force_n": quantize(f_eq_n, "0.0001"),
            "applied_plug_shear_mpa": quantize(applied_shear, "0.0001"),
            "required_thickness_mm": quantize(req_t, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_campbell_rotor_harmonic_clearance(inputs: dict[str, Any]) -> dict[str, str]:
    """Check Campbell frequency separation of natural mode against 1P, bP, 2bP, 3bP harmonics."""
    with localcontext() as ctx:
        ctx.prec = 55
        w_min = _pos(inputs["omega_min_rpm"], "omega_min_rpm")
        w_max = _pos(inputs["omega_max_rpm"], "omega_max_rpm")
        b_dec = _pos(inputs["blade_count"], "blade_count")
        f_struct = _pos(inputs["structural_freq_hz"], "structural_freq_hz")
        min_clr = _d(inputs["min_clearance_pct"], "min_clearance_pct")

        if w_max < w_min:
            raise AbstainError("outside_validity")
        if b_dec != b_dec.to_integral_value() or b_dec < _TWO or b_dec > Decimal("8"):
            raise AbstainError("outside_validity")
        if min_clr < _ZERO:
            raise AbstainError("outside_validity")

        sixty = Decimal("60")
        b_int = int(b_dec)
        orders = (1, b_int, 2 * b_int, 3 * b_int)

        one_p_max = w_max / sixty
        bp_min = (Decimal(b_int) * w_min) / sixty
        bp_max = (Decimal(b_int) * w_max) / sixty

        min_sep: Decimal | None = None
        gov_order = 1
        for k in orders:
            k_dec = Decimal(k)
            f_lo = (k_dec * w_min) / sixty
            f_hi = (k_dec * w_max) / sixty
            if f_struct < f_lo:
                sep = ((f_lo - f_struct) / f_lo) * _HUNDRED
            elif f_struct > f_hi:
                sep = ((f_struct - f_hi) / f_hi) * _HUNDRED
            else:
                sep = _ZERO
            if min_sep is None or sep < min_sep:
                min_sep = sep
                gov_order = k

        assert min_sep is not None
        clr_margin = min_sep - min_clr

        return {
            "one_p_max_hz": quantize(one_p_max, "0.0001"),
            "bp_min_hz": quantize(bp_min, "0.0001"),
            "bp_max_hz": quantize(bp_max, "0.0001"),
            "governing_harmonic_order": str(gov_order),
            "min_separation_pct": quantize(min_sep, "0.0001"),
            "clearance_margin_pct": quantize(clr_margin, "0.0001"),
        }


def run_tailboom_boxbeam_combined_stress(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute semi-monocoque tailboom box-beam bending, Bredt torsion, web shear & VM MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        bm = abs(_d(inputs["bending_moment_n_m"], "bending_moment_n_m"))
        tq = abs(_d(inputs["torque_n_m"], "torque_n_m"))
        vs = abs(_d(inputs["transverse_shear_n"], "transverse_shear_n"))
        width = _pos(inputs["box_width_mm"], "box_width_mm")
        height = _pos(inputs["box_height_mm"], "box_height_mm")
        thk = _pos(inputs["skin_thickness_mm"], "skin_thickness_mm")
        cap_area = _pos(inputs["cap_area_mm2"], "cap_area_mm2")
        fy = _pos(inputs["yield_allowable_mpa"], "yield_allowable_mpa")
        tau_cr = _pos(inputs["shear_buckling_allowable_mpa"], "shear_buckling_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        h_half = height / _TWO
        i_xx = (
            (_FOUR * cap_area * h_half * h_half)
            + ((thk * (height**3)) / _SIX)
            + (_TWO * width * thk * h_half * h_half)
        )
        sig_b = (bm * _THOUSAND * h_half) / i_xx
        tau_torsion = (tq * _THOUSAND) / (_TWO * width * height * thk)
        tau_web = vs / (_TWO * height * thk)
        tau_tot = tau_torsion + tau_web
        vm = (sig_b * sig_b + _THREE * tau_tot * tau_tot).sqrt()
        if vm <= _ZERO or tau_tot <= _ZERO:
            raise AbstainError("outside_validity")

        vm_ms = (fy / (sf * vm)) - _ONE
        sb_ms = (tau_cr / (sf * tau_tot)) - _ONE
        gov_ms = min(vm_ms, sb_ms)

        return {
            "section_inertia_ixx_mm4": quantize(i_xx, "0.0001"),
            "bending_stress_mpa": quantize(sig_b, "0.0001"),
            "torsion_shear_stress_mpa": quantize(tau_torsion, "0.0001"),
            "web_shear_stress_mpa": quantize(tau_web, "0.0001"),
            "total_shear_stress_mpa": quantize(tau_tot, "0.0001"),
            "von_mises_stress_mpa": quantize(vm, "0.0001"),
            "von_mises_ms": quantize(vm_ms, "0.0001"),
            "shear_buckling_ms": quantize(sb_ms, "0.0001"),
            "governing_ms": quantize(gov_ms, "0.0001"),
        }


def run_statistical_ab_basis_tolerance_bound(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute CMH-17 Rev H normal one-sided tolerance factors k_A / k_B and design margin."""
    with localcontext() as ctx:
        ctx.prec = 55
        n_dec = _pos(inputs["sample_count"], "sample_count")
        mean_v = _pos(inputs["sample_mean_mpa"], "sample_mean_mpa")
        std_v = _pos(inputs["sample_std_mpa"], "sample_std_mpa")
        sig_des = _pos(inputs["design_stress_mpa"], "design_stress_mpa")

        if n_dec != n_dec.to_integral_value() or n_dec < Decimal("10"):
            raise AbstainError("outside_validity")

        ln_n = _ln(n_dec)
        k_b = (
            Decimal("1.282")
            + (Decimal("0.958") - Decimal("0.520") * ln_n + Decimal("3.19") / n_dec).exp()
        )
        k_a = (
            Decimal("2.326")
            + (Decimal("1.340") - Decimal("0.522") * ln_n + Decimal("3.87") / n_dec).exp()
        )
        b_basis = mean_v - k_b * std_v
        a_basis = mean_v - k_a * std_v
        if a_basis <= _ZERO:
            raise AbstainError("outside_validity")
        cv_pct = (std_v / mean_v) * _HUNDRED
        ms_a = (a_basis / sig_des) - _ONE

        return {
            "k_b_factor": quantize(k_b, "0.0001"),
            "k_a_factor": quantize(k_a, "0.0001"),
            "b_basis_mpa": quantize(b_basis, "0.0001"),
            "a_basis_mpa": quantize(a_basis, "0.0001"),
            "coeff_variation_pct": quantize(cv_pct, "0.0001"),
            "margin_vs_a_basis": quantize(ms_a, "0.0001"),
        }


ROTORCRAFT_STRESS_EXT_RUNNERS: dict[str, Any] = {
    "larc04_composite_failure": run_larc04_composite_failure,
    "cs29_bird_strike_penetration_screen": run_cs29_bird_strike_penetration_screen,
    "campbell_rotor_harmonic_clearance": run_campbell_rotor_harmonic_clearance,
    "tailboom_boxbeam_combined_stress": run_tailboom_boxbeam_combined_stress,
    "statistical_ab_basis_tolerance_bound": run_statistical_ab_basis_tolerance_bound,
}

ROTORCRAFT_STRESS_EXT_CARD_RUNNERS: dict[str, Any] = {
    method_id: _wrap_rotorcraft_card_runner(method_id, fn)
    for method_id, fn in ROTORCRAFT_STRESS_EXT_RUNNERS.items()
}
