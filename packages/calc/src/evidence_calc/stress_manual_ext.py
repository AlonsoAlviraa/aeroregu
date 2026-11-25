"""Five Additional Industrial Stress Manual Methods (Exact Decimal Precision).

Methods (completing the Stress Manual catalog to 52 methods):
1. bolt_prying_combined_tension_shear    - Bolt tension+prying amplification+bending+shear MS
2. goland_reissner_adhesive_peel_shear   - Goland-Reissner adhesive lap-joint peel & shear MS
3. orthotropic_composite_plate_buckling  - Specially orthotropic plate biaxial+shear buckling MS
4. skin_stringer_crippling_interaction   - Stiffened panel Von Karman + Euler-Johnson crippling MS
5. walker_mean_stress_crack_growth       - Closed-form Walker R-ratio fatigue crack growth life MS
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
    _d,
    _pos,
    _pow,
    quantize,
)

_THREE = Decimal("3")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_EIGHT = Decimal("8")
_TEN = Decimal("10")
_TWENTY = Decimal("20")
_THOUSAND = Decimal("1000")
_SQRT2 = Decimal("2").sqrt()


def run_bolt_prying_combined_tension_shear(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute bolted T-flange prying amplification and combined tension/bending/shear MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        p_t = _d(inputs["applied_tension_n"], "applied_tension_n")
        if p_t < _ZERO:
            raise AbstainError("outside_validity")
        v_s = abs(_d(inputs["applied_shear_n"], "applied_shear_n"))
        m_b = abs(_d(inputs["applied_bending_n_mm"], "applied_bending_n_mm"))
        a_mm = _pos(inputs["prying_lever_a_mm"], "prying_lever_a_mm")
        b_mm = _pos(inputs["prying_lever_b_mm"], "prying_lever_b_mm")
        t_fl = _pos(inputs["flange_thickness_mm"], "flange_thickness_mm")
        allow_t = _pos(inputs["bolt_tensile_allowable_n"], "bolt_tensile_allowable_n")
        allow_s = _pos(inputs["bolt_shear_allowable_n"], "bolt_shear_allowable_n")
        allow_b = _pos(inputs["bolt_bending_allowable_n_mm"], "bolt_bending_allowable_n_mm")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        q_cand = (b_mm / (_TWO * a_mm)) * (_TEN / (t_fl + _TEN))
        q_pry = min(Decimal("0.65"), q_cand)
        pry_force = p_t * q_pry
        tot_tension = p_t + pry_force

        r_t = tot_tension / allow_t
        r_b = m_b / allow_b
        r_s = v_s / allow_s
        idx = ((r_t + r_b) ** 2 + (r_s**2)).sqrt()
        ms = Decimal("99") if idx <= Decimal("1e-12") else (_ONE / (sf * idx)) - _ONE

        return {
            "prying_factor_q": quantize(q_pry, "0.0001"),
            "prying_force_n": quantize(pry_force, "0.0001"),
            "total_bolt_tension_n": quantize(tot_tension, "0.0001"),
            "tension_ratio": quantize(r_t, "0.0001"),
            "shear_ratio": quantize(r_s, "0.0001"),
            "combined_interaction_index": quantize(idx, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_goland_reissner_adhesive_peel_shear(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute Goland-Reissner eccentric single-lap peel + shear peak stresses & MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        load_w = _pos(inputs["tensile_load_per_width_n_mm"], "tensile_load_per_width_n_mm")
        l_ov = _pos(inputs["overlap_length_mm"], "overlap_length_mm")
        t_adh = _pos(inputs["adherend_thickness_mm"], "adherend_thickness_mm")
        e_adh = _pos(inputs["adherend_modulus_mpa"], "adherend_modulus_mpa")
        t_glue = _pos(inputs["adhesive_thickness_mm"], "adhesive_thickness_mm")
        e_glue = _pos(inputs["adhesive_modulus_mpa"], "adhesive_modulus_mpa")
        g_glue = _pos(inputs["adhesive_shear_modulus_mpa"], "adhesive_shear_modulus_mpa")
        peel_allow = _pos(inputs["peel_allowable_mpa"], "peel_allowable_mpa")
        shear_allow = _pos(inputs["shear_allowable_mpa"], "shear_allowable_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        c_half = l_ov / _TWO
        u2c = (c_half / t_adh) * ((_THREE * load_w) / (_TWO * e_adh * t_adh)).sqrt()
        if u2c >= _TWENTY:
            tanh_u = _ONE
        else:
            exp2 = (_TWO * u2c).exp()
            tanh_u = (exp2 - _ONE) / (exp2 + _ONE)

        k_gr = _ONE / (_ONE + _TWO * _SQRT2 * tanh_u)
        tau_avg = load_w / l_ov
        beta_s = ((_EIGHT * g_glue * t_adh) / (e_adh * t_glue)).sqrt() * (c_half / t_adh)
        peak_shear = tau_avg * (
            _ONE + Decimal("0.25") * (_ONE + _THREE * k_gr) * (_ONE + beta_s / _FOUR)
        )
        gamma_p = ((_SIX * e_glue * t_adh) / (e_adh * t_glue)).sqrt()
        peak_peel = (load_w / t_adh) * k_gr * Decimal("0.5") * gamma_p

        r_peel = peak_peel / peel_allow
        r_shear = peak_shear / shear_allow
        idx = (r_peel * r_peel + r_shear * r_shear).sqrt()
        if idx <= Decimal("1e-12"):
            raise AbstainError("outside_validity")
        ms = (_ONE / (sf * idx)) - _ONE

        return {
            "gr_bending_factor_k": quantize(k_gr, "0.0001"),
            "average_shear_mpa": quantize(tau_avg, "0.0001"),
            "peak_shear_mpa": quantize(peak_shear, "0.0001"),
            "peak_peel_mpa": quantize(peak_peel, "0.0001"),
            "combined_interaction_index": quantize(idx, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_orthotropic_composite_plate_buckling(inputs: dict[str, Any]) -> dict[str, str]:
    """Evaluate Lekhnitskii/Seydel orthotropic composite panel buckling under Nx, Ny, Nxy."""
    with localcontext() as ctx:
        ctx.prec = 55
        nx = _d(inputs["nx_comp_n_per_mm"], "nx_comp_n_per_mm")
        ny = _d(inputs["ny_comp_n_per_mm"], "ny_comp_n_per_mm")
        nxy = abs(_d(inputs["nxy_shear_n_per_mm"], "nxy_shear_n_per_mm"))
        len_a = _pos(inputs["plate_length_a_mm"], "plate_length_a_mm")
        wid_b = _pos(inputs["plate_width_b_mm"], "plate_width_b_mm")
        d11 = _pos(inputs["d11_n_mm"], "d11_n_mm")
        d22 = _pos(inputs["d22_n_mm"], "d22_n_mm")
        d12 = _pos(inputs["d12_n_mm"], "d12_n_mm")
        d66 = _pos(inputs["d66_n_mm"], "d66_n_mm")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        h_eff = d12 + _TWO * d66
        d_sqrt = (d11 * d22).sqrt()
        pi_sq = _PI * _PI
        nx_cr = (_TWO * pi_sq / (wid_b * wid_b)) * (d_sqrt + h_eff)
        ny_cr = (_TWO * pi_sq / (len_a * len_a)) * (d_sqrt + h_eff)

        theta_s = d_sqrt / h_eff
        k_s = Decimal("3.2") + Decimal("2.1") / (theta_s + Decimal("0.5"))
        d_fourth = (d11 * (d22**3)).sqrt().sqrt()
        nxy_cr = (_FOUR * k_s / (wid_b * wid_b)) * d_fourth

        r_x = max(_ZERO, nx) / nx_cr
        r_y = max(_ZERO, ny) / ny_cr
        r_xy = nxy / nxy_cr
        idx = r_x + r_y + (r_xy * r_xy)
        ms = Decimal("99") if idx <= Decimal("1e-12") else (_ONE / (sf * idx)) - _ONE

        return {
            "nx_critical_n_per_mm": quantize(nx_cr, "0.0001"),
            "ny_critical_n_per_mm": quantize(ny_cr, "0.0001"),
            "nxy_critical_n_per_mm": quantize(nxy_cr, "0.0001"),
            "orthotropy_param_theta": quantize(theta_s, "0.0001"),
            "combined_interaction_index": quantize(idx, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_skin_stringer_crippling_interaction(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute stiffened panel Von Karman effective width & Euler-Johnson crippling MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        p_app = _pos(inputs["applied_compression_n"], "applied_compression_n")
        l_pan = _pos(inputs["panel_length_mm"], "panel_length_mm")
        pitch = _pos(inputs["stringer_pitch_mm"], "stringer_pitch_mm")
        t_sk = _pos(inputs["skin_thickness_mm"], "skin_thickness_mm")
        a_str = _pos(inputs["stringer_area_mm2"], "stringer_area_mm2")
        f_cc = _pos(inputs["stringer_crippling_mpa"], "stringer_crippling_mpa")
        i_pan = _pos(inputs["panel_inertia_mm4"], "panel_inertia_mm4")
        c_fix = _pos(inputs["end_fixity_c"], "end_fixity_c")
        em = _pos(inputs["modulus_mpa"], "modulus_mpa")
        f_y = _pos(inputs["skin_yield_mpa"], "skin_yield_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")

        w_vk = Decimal("1.9") * t_sk * (em / f_y).sqrt()
        w_eff = min(pitch, w_vk)
        a_eff = a_str + w_eff * t_sk
        sig_cc = (a_str * f_cc + w_eff * t_sk * f_y) / a_eff
        rho_g = (i_pan / a_eff).sqrt()
        slend = l_pan / (rho_g * c_fix.sqrt())
        pi_sq = _PI * _PI
        lam_c = (_TWO * pi_sq * em / sig_cc).sqrt()

        if slend <= lam_c:
            sig_cr = sig_cc * (_ONE - (sig_cc * slend * slend) / (_FOUR * pi_sq * em))
            regime = "1.0000"
        else:
            sig_cr = (pi_sq * em) / (slend * slend)
            regime = "2.0000"

        sig_app = p_app / a_eff
        ms = (sig_cr / (sf * sig_app)) - _ONE

        return {
            "effective_skin_width_mm": quantize(w_eff, "0.0001"),
            "effective_panel_area_mm2": quantize(a_eff, "0.0001"),
            "weighted_crippling_cutoff_mpa": quantize(sig_cc, "0.0001"),
            "effective_slenderness": quantize(slend, "0.0001"),
            "column_regime_code": regime,
            "critical_panel_stress_mpa": quantize(sig_cr, "0.0001"),
            "applied_panel_stress_mpa": quantize(sig_app, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_walker_mean_stress_crack_growth(inputs: dict[str, Any]) -> dict[str, str]:
    """Integrate Walker R-ratio crack growth law analytically to critical crack size."""
    with localcontext() as ctx:
        ctx.prec = 55
        a0_mm = _pos(inputs["initial_crack_a0_mm"], "initial_crack_a0_mm")
        sig_max = _pos(inputs["sigma_max_mpa"], "sigma_max_mpa")
        r_rat = _d(inputs["stress_ratio_r"], "stress_ratio_r")
        beta = _pos(inputs["geometry_factor_beta"], "geometry_factor_beta")
        k_ic = _pos(
            inputs["fracture_toughness_kic_mpa_sqrt_m"], "fracture_toughness_kic_mpa_sqrt_m"
        )
        w_c = _pos(inputs["walker_c"], "walker_c")
        w_m = _pos(inputs["walker_m"], "walker_m")
        w_gamma = _pos(inputs["walker_gamma"], "walker_gamma")
        req_cyc = _pos(inputs["required_cycles"], "required_cycles")
        sf = _pos(inputs["scatter_factor"], "scatter_factor")

        if r_rat < Decimal("-0.5") or r_rat > Decimal("0.9"):
            raise AbstainError("outside_validity")
        if w_m <= Decimal("2.05") or w_m > Decimal("8"):
            raise AbstainError("outside_validity")
        if w_gamma < Decimal("0.2") or w_gamma > _ONE:
            raise AbstainError("outside_validity")

        a0_m = a0_mm / _THOUSAND
        ac_m = ((k_ic / (beta * sig_max)) ** 2) / _PI
        ac_mm = ac_m * _THOUSAND
        if ac_mm <= a0_mm:
            raise AbstainError("outside_validity")

        ds_eff = sig_max * _pow(_ONE - r_rat, w_gamma)
        dk_eff_0 = beta * ds_eff * (_PI * a0_m).sqrt()
        p_exp = _ONE - (w_m / _TWO)
        denom_const = w_c * _pow(beta * ds_eff * _PI.sqrt(), w_m)
        life_cycles = (_pow(ac_m, p_exp) - _pow(a0_m, p_exp)) / (p_exp * denom_const)
        insp_cyc = life_cycles / sf
        ms_life = (insp_cyc / req_cyc) - _ONE

        return {
            "critical_crack_ac_mm": quantize(ac_mm, "0.0001"),
            "walker_effective_stress_mpa": quantize(ds_eff, "0.0001"),
            "initial_delta_k_eff_mpa_sqrt_m": quantize(dk_eff_0, "0.0001"),
            "unfactored_life_cycles": quantize(life_cycles, "0.0001"),
            "safe_inspection_interval_cycles": quantize(insp_cyc, "0.0001"),
            "life_margin_of_safety": quantize(ms_life, "0.0001"),
        }


STRESS_MANUAL_EXT_RUNNERS: dict[str, Any] = {
    "bolt_prying_combined_tension_shear": run_bolt_prying_combined_tension_shear,
    "goland_reissner_adhesive_peel_shear": run_goland_reissner_adhesive_peel_shear,
    "orthotropic_composite_plate_buckling": run_orthotropic_composite_plate_buckling,
    "skin_stringer_crippling_interaction": run_skin_stringer_crippling_interaction,
    "walker_mean_stress_crack_growth": run_walker_mean_stress_crack_growth,
}

STRESS_MANUAL_EXT_CARD_RUNNERS: dict[str, Any] = {
    method_id: _wrap_rotorcraft_card_runner(method_id, fn)
    for method_id, fn in STRESS_MANUAL_EXT_RUNNERS.items()
}
