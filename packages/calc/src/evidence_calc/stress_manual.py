"""25 Deterministic Aerospace Stress Office Analysis Methods (Exact Decimal Precision).

Covers:
- Metallic Fatigue & Damage Tolerance (Paris/NASGRO, Goodman/Haigh, Neuber, LEFM, Rainflow)
- Composite Laminates & CMH-17 (Tsai-Wu, Hashin 4-mode, Puck IFF, OHT, OHC, CAI)
- Joints, Fasteners & Lugs (Huth, Bearing-Bypass, Eccentric Bolt Group,
  NASA Lug, Thermal Preload, Pull-Through, Volkersen)
- Thin-Walled Stability & Sizing (Johnson-Euler, Needham Crippling,
  Kuhn Diagonal Tension, Curved Panel, Inter-Rivet, Bredt Torsion, Sandwich Wrinkling)
"""

from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.allowables import lookup_allowable
from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum, parse_limited_decimal

_CAPTURE_RAW: ContextVar[deque[tuple[str, Decimal]] | None] = ContextVar(
    "_CAPTURE_RAW", default=None
)


def quantize(val: Decimal, q_str: str) -> str:
    """Quantize a Decimal value using exact base-10 quantum string and format canonically."""
    out = format_quantum(val, Decimal(q_str))
    buf = _CAPTURE_RAW.get()
    if buf is not None:
        buf.append((out, val))
    return out


_PI = Decimal("3.141592653589793238462643383279502884197")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")


def _d(val: Any, name: str = "input") -> Decimal:
    try:
        d = Decimal(str(val))
    except Exception as exc:
        raise AbstainError(f"invalid_decimal:{name}") from exc
    if not d.is_finite():
        raise AbstainError(f"non_finite:{name}")
    return d


def _pos(val: Any, name: str) -> Decimal:
    d = _d(val, name)
    if d <= _ZERO:
        raise AbstainError("outside_validity")
    return d


def _nonneg(val: Any, name: str) -> Decimal:
    d = _d(val, name)
    if d < _ZERO:
        raise AbstainError("outside_validity")
    return d


def _pow(base: Decimal, exp: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        if base == _ZERO:
            if exp <= _ZERO:
                raise AbstainError("division_by_zero")
            return _ZERO
        if exp == exp.to_integral_value():
            return base ** int(exp)
        if base < _ZERO:
            raise AbstainError("outside_validity")
        return (exp * base.ln()).exp()


def _cos_deg(deg: Decimal) -> Decimal:
    """High-precision Taylor cosine in exact Decimal arithmetic."""
    with localcontext() as ctx:
        ctx.prec = 50
        rad = (deg % Decimal("360")) * _PI / Decimal("180")
        x2 = -(rad * rad)
        term = _ONE
        total = _ONE
        for k in range(1, 22):
            denom = Decimal((2 * k - 1) * (2 * k))
            term = term * x2 / denom
            total += term
        return total


def _sin_deg(deg: Decimal) -> Decimal:
    return _cos_deg(Decimal("90") - deg)


def _ln(x: Decimal) -> Decimal:
    if x <= _ZERO:
        raise AbstainError("outside_validity")
    with localcontext() as ctx:
        ctx.prec = 50
        return x.ln()


# ---------------------------------------------------------------------------
# 1..5: Metallic Fatigue & Damage Tolerance
# ---------------------------------------------------------------------------


def run_nasgro_paris_crack_growth(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        a0 = _pos(inputs["initial_crack_mm"], "initial_crack_mm")
        sigma = _pos(inputs["delta_sigma_mpa"], "delta_sigma_mpa")
        y_geo = _pos(inputs["geometry_factor_y"], "geometry_factor_y")
        k_ic = _pos(inputs["fracture_toughness_mpa_sqrt_m"], "fracture_toughness_mpa_sqrt_m")
        c_paris = _pos(inputs["paris_c"], "paris_c")
        m_paris = _pos(inputs["paris_m"], "paris_m")
        req_cycles = _pos(inputs["required_cycles"], "required_cycles")

        # Critical crack size a_c in meters then mm: K_Ic = Y * sigma * sqrt(pi * a_c)
        a0_m = a0 / Decimal("1000")
        ac_m = (k_ic / (y_geo * sigma)) ** 2 / _PI
        if ac_m <= a0_m:
            return {
                "critical_crack_mm": quantize(ac_m * Decimal("1000"), "0.001"),
                "delta_k_initial_mpa_sqrt_m": quantize(
                    y_geo * sigma * (_PI * a0_m).sqrt(), "0.001"
                ),
                "cycles_to_failure": "0",
                "life_margin_of_safety": quantize(Decimal("-1"), "0.0001"),
            }
        # Closed-form Paris integration for m != 2 and m == 2 (a in meters)
        factor = c_paris * _pow(y_geo * sigma * _PI.sqrt(), m_paris)
        if m_paris == _TWO:
            n_fail = (_ln(ac_m / a0_m)) / factor
        else:
            p = _ONE - m_paris / _TWO
            n_fail = (_pow(ac_m, p) - _pow(a0_m, p)) / (p * factor)
        ms = (n_fail / req_cycles) - _ONE
        return {
            "critical_crack_mm": quantize(ac_m * Decimal("1000"), "0.001"),
            "delta_k_initial_mpa_sqrt_m": quantize(y_geo * sigma * (_PI * a0_m).sqrt(), "0.001"),
            "cycles_to_failure": quantize(n_fail, "1"),
            "life_margin_of_safety": quantize(ms, "0.0001"),
        }


def run_goodman_haigh_mean_stress(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sa = _pos(inputs["alternating_stress_mpa"], "alternating_stress_mpa")
        sm = _d(inputs["mean_stress_mpa"], "mean_stress_mpa")
        s_e = _pos(inputs["endurance_limit_mpa"], "endurance_limit_mpa")
        s_ut = _pos(inputs["ultimate_tensile_mpa"], "ultimate_tensile_mpa")
        # Conservative Goodman for tensile mean stress; flat for compressive mean stress
        eff_sm = max(_ZERO, sm)
        if eff_sm >= s_ut:
            raise AbstainError("outside_validity")
        inv_nf = (sa / s_e) + (eff_sm / s_ut)
        safety_factor = _ONE / inv_nf
        eq_alt = sa / (_ONE - (eff_sm / s_ut))
        return {
            "equivalent_reversed_stress_mpa": quantize(eq_alt, "0.001"),
            "fatigue_safety_factor": quantize(safety_factor, "0.0001"),
            "margin_of_safety": quantize(safety_factor - _ONE, "0.0001"),
        }


def run_neuber_notch_plasticity(inputs: dict[str, Any]) -> dict[str, str]:
    """Solve Neuber rule: sigma_local * eps_local = (Kt * S)^2 / E."""
    with localcontext() as ctx:
        ctx.prec = 50
        s_nom = _pos(inputs["nominal_stress_mpa"], "nominal_stress_mpa")
        kt = _pos(inputs["kt_concentration"], "kt_concentration")
        e_mpa = _pos(inputs["modulus_mpa"], "modulus_mpa")
        k_prime = _pos(inputs["cyclic_strength_coeff_mpa"], "cyclic_strength_coeff_mpa")
        n_prime = _pos(inputs["cyclic_hardening_exp"], "cyclic_hardening_exp")
        s_yield = _pos(inputs["cyclic_yield_mpa"], "cyclic_yield_mpa")

        target = ((kt * s_nom) ** 2) / e_mpa
        inv_n = _ONE / n_prime
        lo = _ZERO
        hi = kt * s_nom + k_prime * Decimal("2")
        for _ in range(90):
            mid = (lo + hi) / _TWO
            lhs = mid * ((mid / e_mpa) + _pow(mid / k_prime, inv_n))
            if lhs < target:
                lo = mid
            else:
                hi = mid
        sig_loc = (lo + hi) / _TWO
        eps_loc = (sig_loc / e_mpa) + _pow(sig_loc / k_prime, inv_n)
        ms = (s_yield / sig_loc) - _ONE
        return {
            "local_notch_stress_mpa": quantize(sig_loc, "0.001"),
            "local_notch_strain": quantize(eps_loc, "0.000001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_net_section_yielding_fracture(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        load_n = _pos(inputs["applied_load_n"], "applied_load_n")
        width = _pos(inputs["plate_width_mm"], "plate_width_mm")
        thk = _pos(inputs["thickness_mm"], "thickness_mm")
        a_crack = _pos(inputs["half_crack_mm"], "half_crack_mm")
        fty = _pos(inputs["yield_strength_mpa"], "yield_strength_mpa")
        k_ic = _pos(inputs["fracture_toughness_mpa_sqrt_m"], "fracture_toughness_mpa_sqrt_m")

        net_width = width - _TWO * a_crack
        if net_width <= _ZERO:
            raise AbstainError("outside_validity")
        gross_area = width * thk
        net_area = net_width * thk
        sigma_gross = load_n / gross_area
        sigma_net = load_n / net_area
        ratio = _TWO * a_crack / width
        sec_arg = (_PI * ratio / _TWO) * Decimal("180") / _PI
        cos_v = _cos_deg(sec_arg)
        if cos_v <= _ZERO:
            raise AbstainError("outside_validity")
        feddersen = (_ONE / cos_v).sqrt()
        k_applied = feddersen * sigma_gross * (_PI * (a_crack / Decimal("1000"))).sqrt()
        ms_net = (fty / sigma_net) - _ONE
        ms_lefm = (k_ic / k_applied) - _ONE
        return {
            "net_section_stress_mpa": quantize(sigma_net, "0.001"),
            "stress_intensity_ki_mpa_sqrt_m": quantize(k_applied, "0.001"),
            "margin_of_safety": quantize(min(ms_net, ms_lefm), "0.0001"),
        }


def run_rainflow_spectrum_damage(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        n1 = _nonneg(inputs["cycles_band1"], "cycles_band1")
        nf1 = _pos(inputs["allowable_cycles_band1"], "allowable_cycles_band1")
        n2 = _nonneg(inputs["cycles_band2"], "cycles_band2")
        nf2 = _pos(inputs["allowable_cycles_band2"], "allowable_cycles_band2")
        n3 = _nonneg(inputs["cycles_band3"], "cycles_band3")
        nf3 = _pos(inputs["allowable_cycles_band3"], "allowable_cycles_band3")
        sf = _pos(inputs["scatter_factor"], "scatter_factor")

        raw_damage = (n1 / nf1) + (n2 / nf2) + (n3 / nf3)
        factored_damage = raw_damage * sf
        if factored_damage <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (_ONE / factored_damage) - _ONE
        return {
            "raw_miner_damage": quantize(raw_damage, "0.00001"),
            "factored_damage": quantize(factored_damage, "0.00001"),
            "life_margin_of_safety": quantize(ms, "0.0001"),
        }


# ---------------------------------------------------------------------------
# 6..11: Composites & CMH-17 Criteria
# ---------------------------------------------------------------------------


def run_tsai_wu_ply_failure(inputs: dict[str, Any]) -> dict[str, str]:
    """Solve quadratic Tsai-Wu F_ij terms: A*R^2 + B*R - 1 = 0 -> MS = R - 1."""
    with localcontext() as ctx:
        ctx.prec = 50
        s1 = _d(inputs["sigma_1_mpa"], "sigma_1_mpa")
        s2 = _d(inputs["sigma_2_mpa"], "sigma_2_mpa")
        t12 = _d(inputs["tau_12_mpa"], "tau_12_mpa")
        xt = _pos(inputs["xt_mpa"], "xt_mpa")
        xc = _pos(inputs["xc_mpa"], "xc_mpa")
        yt = _pos(inputs["yt_mpa"], "yt_mpa")
        yc = _pos(inputs["yc_mpa"], "yc_mpa")
        s12_allow = _pos(inputs["s12_mpa"], "s12_mpa")

        f1 = (_ONE / xt) - (_ONE / xc)
        f2 = (_ONE / yt) - (_ONE / yc)
        f11 = _ONE / (xt * xc)
        f22 = _ONE / (yt * yc)
        f66 = _ONE / (s12_allow * s12_allow)
        f12 = Decimal("-0.5") * (f11 * f22).sqrt()

        a_coef = f11 * s1 * s1 + _TWO * f12 * s1 * s2 + f22 * s2 * s2 + f66 * t12 * t12
        b_coef = f1 * s1 + f2 * s2
        if a_coef <= _ZERO:
            raise AbstainError("outside_validity")
        disc = b_coef * b_coef + Decimal("4") * a_coef
        sr = (-b_coef + disc.sqrt()) / (_TWO * a_coef)
        fi = a_coef + b_coef
        return {
            "tsai_wu_index": quantize(fi, "0.0001"),
            "strength_ratio": quantize(sr, "0.0001"),
            "margin_of_safety": quantize(sr - _ONE, "0.0001"),
        }


def run_hashin_composite_modes(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        s1 = _d(inputs["sigma_1_mpa"], "sigma_1_mpa")
        s2 = _d(inputs["sigma_2_mpa"], "sigma_2_mpa")
        t12 = _d(inputs["tau_12_mpa"], "tau_12_mpa")
        xt = _pos(inputs["xt_mpa"], "xt_mpa")
        xc = _pos(inputs["xc_mpa"], "xc_mpa")
        yt = _pos(inputs["yt_mpa"], "yt_mpa")
        yc = _pos(inputs["yc_mpa"], "yc_mpa")
        sl = _pos(inputs["sl_mpa"], "sl_mpa")
        st = _pos(inputs["st_mpa"], "st_mpa")

        if s1 >= _ZERO:
            ft_idx = (s1 / xt) ** 2 + (t12 / sl) ** 2
            fc_idx = _ZERO
        else:
            ft_idx = _ZERO
            fc_idx = (s1 / xc) ** 2

        if s2 >= _ZERO:
            mt_idx = (s2 / yt) ** 2 + (t12 / sl) ** 2
            mc_idx = _ZERO
        else:
            mt_idx = _ZERO
            term_c = (yc / (_TWO * st)) ** 2 - _ONE
            mc_idx = (s2 / (_TWO * st)) ** 2 + term_c * (s2 / yc) + (t12 / sl) ** 2

        crit_idx = max(ft_idx, fc_idx, mt_idx, mc_idx)
        if crit_idx <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (_ONE / crit_idx.sqrt()) - _ONE
        return {
            "fiber_index": quantize(max(ft_idx, fc_idx), "0.0001"),
            "matrix_index": quantize(max(mt_idx, mc_idx), "0.0001"),
            "critical_hashin_index": quantize(crit_idx, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_puck_interfiber_fracture(inputs: dict[str, Any]) -> dict[str, str]:
    """Puck 2D IFF criteria distinguishing Mode A tension, Mode B/C compression."""
    with localcontext() as ctx:
        ctx.prec = 50
        s2 = _d(inputs["sigma_2_mpa"], "sigma_2_mpa")
        t12 = _d(inputs["tau_12_mpa"], "tau_12_mpa")
        yt = _pos(inputs["yt_mpa"], "yt_mpa")
        yc = _pos(inputs["yc_mpa"], "yc_mpa")
        sl = _pos(inputs["sl_mpa"], "sl_mpa")
        p_pt = Decimal("0.30")
        p_pc = Decimal("0.20")

        r_22a = (sl / (_TWO * p_pc)) * ((_ONE + _TWO * p_pc * (yc / sl)).sqrt() - _ONE)
        tau_21c = sl * (_ONE + _TWO * (yc / r_22a)).sqrt()

        if s2 >= _ZERO:
            fe_iff = (
                ((t12 / sl) ** 2 + (_ONE - p_pt * (yt / sl)) ** 2 * (s2 / yt) ** 2).sqrt()
            ) + p_pt * (s2 / sl)
            mode = "1"  # Mode A
        elif abs(s2) <= r_22a and abs(t12) >= _ZERO:
            # Check Mode B vs Mode C transition
            if tau_21c > _ZERO and abs(s2 / max(Decimal("0.001"), abs(t12))) <= (r_22a / tau_21c):
                fe_iff = (((t12 / sl) ** 2 + (p_pc * (s2 / sl)) ** 2).sqrt()) + p_pc * (s2 / sl)
                mode = "2"  # Mode B
            else:
                fe_iff = ((t12 / (_TWO * (_ONE + p_pc) * sl)) ** 2 + (s2 / yc) ** 2) * (
                    yc / max(Decimal("0.001"), abs(s2))
                )
                mode = "3"  # Mode C
        else:
            fe_iff = ((t12 / (_TWO * (_ONE + p_pc) * sl)) ** 2 + (s2 / yc) ** 2) * (
                yc / max(Decimal("0.001"), abs(s2))
            )
            mode = "3"

        if fe_iff <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (_ONE / fe_iff) - _ONE
        return {
            "puck_iff_mode_code": mode,
            "exposure_factor_fe": quantize(fe_iff, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_open_hole_tension_oht(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_far = _pos(inputs["applied_far_field_mpa"], "applied_far_field_mpa")
        f_oht_base = _pos(inputs["oht_allowable_rtd_mpa"], "oht_allowable_rtd_mpa")
        hole_d = _pos(inputs["hole_diameter_mm"], "hole_diameter_mm")
        width = _pos(inputs["strip_width_mm"], "strip_width_mm")
        env_kd = _pos(inputs["environmental_knockdown"], "environmental_knockdown")

        if hole_d >= width:
            raise AbstainError("outside_validity")
        # Width finite-plate correction relative to reference 6.35mm/38.1mm coupon
        w_d = width / hole_d
        ref_wd = Decimal("6")
        width_corr = (_ONE - (hole_d / width)) / (_ONE - (_ONE / ref_wd))
        # Characteristic notch size adjustment from baseline D0 = 6.35 mm
        d_scale = _pow(Decimal("6.35") / hole_d, Decimal("0.08"))
        f_oht_eff = (
            f_oht_base * env_kd * min(Decimal("1.08"), max(Decimal("0.80"), width_corr)) * d_scale
        )
        ms = (f_oht_eff / sigma_far) - _ONE
        return {
            "width_to_diameter": quantize(w_d, "0.001"),
            "effective_oht_allowable_mpa": quantize(f_oht_eff, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_open_hole_compression_ohc(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_comp = _pos(inputs["applied_compressive_mpa"], "applied_compressive_mpa")
        f_ohc_base = _pos(inputs["ohc_allowable_rtd_mpa"], "ohc_allowable_rtd_mpa")
        etw_kd = _pos(inputs["etw_knockdown"], "etw_knockdown")
        hole_d = _pos(inputs["hole_diameter_mm"], "hole_diameter_mm")

        d_factor = _pow(Decimal("6.35") / hole_d, Decimal("0.06"))
        f_ohc_eff = f_ohc_base * etw_kd * min(Decimal("1.05"), max(Decimal("0.75"), d_factor))
        ms = (f_ohc_eff / sigma_comp) - _ONE
        return {
            "effective_ohc_allowable_mpa": quantize(f_ohc_eff, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_compression_after_impact_cai(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_comp = _pos(inputs["applied_compressive_mpa"], "applied_compressive_mpa")
        f_cai_base = _pos(inputs["cai_allowable_bvid_mpa"], "cai_allowable_bvid_mpa")
        impact_j = _pos(inputs["impact_energy_j"], "impact_energy_j")
        ref_j = _pos(inputs["reference_bvid_j"], "reference_bvid_j")
        env_kd = _pos(inputs["environmental_knockdown"], "environmental_knockdown")

        energy_ratio = impact_j / ref_j
        energy_kd = _pow(_ONE / max(Decimal("0.25"), energy_ratio), Decimal("0.18"))
        f_cai_eff = f_cai_base * env_kd * min(Decimal("1.10"), max(Decimal("0.65"), energy_kd))
        ms = (f_cai_eff / sigma_comp) - _ONE
        return {
            "effective_cai_allowable_mpa": quantize(f_cai_eff, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


# ---------------------------------------------------------------------------
# 12..18: Joints, Fasteners & Lugs
# ---------------------------------------------------------------------------


def run_huth_fastener_flexibility(inputs: dict[str, Any]) -> dict[str, str]:
    """Huth formula for fastener flexibility in double/single shear joints."""
    with localcontext() as ctx:
        ctx.prec = 50
        d = _pos(inputs["fastener_diameter_mm"], "fastener_diameter_mm")
        t1 = _pos(inputs["plate1_thickness_mm"], "plate1_thickness_mm")
        t2 = _pos(inputs["plate2_thickness_mm"], "plate2_thickness_mm")
        e1 = _pos(inputs["plate1_modulus_mpa"], "plate1_modulus_mpa")
        e2 = _pos(inputs["plate2_modulus_mpa"], "plate2_modulus_mpa")
        ef = _pos(inputs["fastener_modulus_mpa"], "fastener_modulus_mpa")
        a_exp = _pos(inputs["huth_a_exp"], "huth_a_exp")
        b_coef = _pos(inputs["huth_b_coef"], "huth_b_coef")
        n_shear = _pos(inputs["shear_planes_n"], "shear_planes_n")

        # C = ((t1 + t2) / (2 * d))^a * (b / n) *
        #     (1/(t1*E1) + 1/(n*t2*E2) + 1/(2*t1*Ef) + 1/(2*n*t2*Ef))
        geom = _pow((t1 + t2) / (_TWO * d), a_exp)
        compl = (
            (_ONE / (t1 * e1))
            + (_ONE / (n_shear * t2 * e2))
            + (_ONE / (_TWO * t1 * ef))
            + (_ONE / (_TWO * n_shear * t2 * ef))
        )
        flexibility = geom * (b_coef / n_shear) * compl
        stiffness_n_per_mm = _ONE / flexibility
        return {
            "fastener_flexibility_mm_per_n": quantize(flexibility, "0.00000001"),
            "fastener_stiffness_n_per_mm": quantize(stiffness_n_per_mm, "0.01"),
        }


def run_bearing_bypass_interaction(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        p_brg = _nonneg(inputs["bearing_load_n"], "bearing_load_n")
        p_byp = _nonneg(inputs["bypass_load_n"], "bypass_load_n")
        d = _pos(inputs["hole_diameter_mm"], "hole_diameter_mm")
        w = _pos(inputs["strip_width_mm"], "strip_width_mm")
        t = _pos(inputs["thickness_mm"], "thickness_mm")
        f_bru = _pos(inputs["bearing_allowable_mpa"], "bearing_allowable_mpa")
        f_oht = _pos(inputs["bypass_oht_allowable_mpa"], "bypass_oht_allowable_mpa")

        if w <= d:
            raise AbstainError("outside_validity")
        f_br_app = p_brg / (d * t)
        f_byp_app = p_byp / (w * t)
        r_br = f_br_app / f_bru
        r_byp = f_byp_app / f_oht
        # Conservative linear bearing-bypass interaction bound (R_br + R_byp <= 1)
        comb = r_br + r_byp
        if comb <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (_ONE / comb) - _ONE
        return {
            "bearing_stress_mpa": quantize(f_br_app, "0.001"),
            "bypass_gross_stress_mpa": quantize(f_byp_app, "0.001"),
            "interaction_utilization": quantize(comb, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_eccentric_bolt_group_cg(inputs: dict[str, Any]) -> dict[str, str]:
    """Symmetric 4-bolt rectangular flange pattern under eccentric shear (Vx, Vy) + Moment Mz."""
    with localcontext() as ctx:
        ctx.prec = 50
        vx = _d(inputs["shear_vx_n"], "shear_vx_n")
        vy = _d(inputs["shear_vy_n"], "shear_vy_n")
        mz = _d(inputs["moment_mz_nmm"], "moment_mz_nmm")
        dx = _pos(inputs["half_spacing_x_mm"], "half_spacing_x_mm")
        dy = _pos(inputs["half_spacing_y_mm"], "half_spacing_y_mm")
        n_bolts = Decimal("4")
        v_allow = _pos(inputs["bolt_shear_allowable_n"], "bolt_shear_allowable_n")

        sum_r2 = n_bolts * (dx * dx + dy * dy)
        direct_x = vx / n_bolts
        direct_y = vy / n_bolts
        max_bolt_force = _ZERO
        for sx in (Decimal("1"), Decimal("-1")):
            for sy in (Decimal("1"), Decimal("-1")):
                rx = sx * dx
                ry = sy * dy
                fx = direct_x - (mz * ry / sum_r2)
                fy = direct_y + (mz * rx / sum_r2)
                mag = (fx * fx + fy * fy).sqrt()
                if mag > max_bolt_force:
                    max_bolt_force = mag
        if max_bolt_force <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (v_allow / max_bolt_force) - _ONE
        return {
            "polar_moment_sum_r2_mm2": quantize(sum_r2, "0.01"),
            "max_bolt_shear_n": quantize(max_bolt_force, "0.01"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_lug_axial_transverse_interaction(inputs: dict[str, Any]) -> dict[str, str]:
    """Aerospace lug analysis with R_a^1.6 + R_tr^1.6 <= 1 combined interaction."""
    with localcontext() as ctx:
        ctx.prec = 50
        p_ax = _nonneg(inputs["axial_load_n"], "axial_load_n")
        p_tr = _nonneg(inputs["transverse_load_n"], "transverse_load_n")
        p_ax_allow = _pos(inputs["axial_allowable_n"], "axial_allowable_n")
        p_tr_allow = _pos(inputs["transverse_allowable_n"], "transverse_allowable_n")

        ra = p_ax / p_ax_allow
        rtr = p_tr / p_tr_allow
        comb = _pow(ra, Decimal("1.6")) + _pow(rtr, Decimal("1.6"))
        if comb <= _ZERO:
            raise AbstainError("outside_validity")
        sf = _pow(_ONE / comb, _ONE / Decimal("1.6"))
        return {
            "axial_ratio": quantize(ra, "0.0001"),
            "transverse_ratio": quantize(rtr, "0.0001"),
            "combined_margin_of_safety": quantize(sf - _ONE, "0.0001"),
        }


def run_bolt_preload_thermal_relaxation(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        fp0 = _pos(inputs["initial_preload_n"], "initial_preload_n")
        embed_loss = _nonneg(inputs["embedment_loss_n"], "embedment_loss_n")
        alpha_b = _pos(inputs["bolt_cte_per_c"], "bolt_cte_per_c")
        alpha_p = _pos(inputs["plate_cte_per_c"], "plate_cte_per_c")
        delta_t = _d(inputs["delta_temp_c"], "delta_temp_c")
        kb = _pos(inputs["bolt_stiffness_n_per_mm"], "bolt_stiffness_n_per_mm")
        kp = _pos(inputs["joint_stiffness_n_per_mm"], "joint_stiffness_n_per_mm")
        grip = _pos(inputs["grip_length_mm"], "grip_length_mm")
        f_ext = _nonneg(inputs["external_tensile_load_n"], "external_tensile_load_n")

        # Stiffness factor phi = kb / (kb + kp)
        phi = kb / (kb + kp)
        # Thermal preload delta when plate & bolt differ in CTE:
        # k_eq * (alpha_p - alpha_b) * dT * L
        k_series = (kb * kp) / (kb + kp)
        delta_fp_thermal = k_series * (alpha_p - alpha_b) * delta_t * grip
        eff_preload = fp0 - embed_loss + delta_fp_thermal
        if eff_preload <= _ZERO:
            return {
                "effective_preload_n": quantize(eff_preload, "0.01"),
                "residual_clamp_force_n": "0",
                "gapping_margin_of_safety": quantize(Decimal("-1"), "0.0001"),
            }
        clamp_res = eff_preload - (_ONE - phi) * f_ext
        sep_load = eff_preload / (_ONE - phi)
        ms_gap = (sep_load / f_ext) - _ONE if f_ext > _ZERO else Decimal("99")
        return {
            "effective_preload_n": quantize(eff_preload, "0.01"),
            "residual_clamp_force_n": quantize(clamp_res, "0.01"),
            "gapping_margin_of_safety": quantize(ms_gap, "0.0001"),
        }


def run_fastener_pull_through_composite(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        p_t = _pos(inputs["tensile_load_n"], "tensile_load_n")
        d_head = _pos(inputs["head_diameter_mm"], "head_diameter_mm")
        t_lam = _pos(inputs["laminate_thickness_mm"], "laminate_thickness_mm")
        ilss = _pos(inputs["ilss_allowable_mpa"], "ilss_allowable_mpa")
        kf = _pos(inputs["countersink_knockdown"], "countersink_knockdown")

        area_shear = _PI * d_head * t_lam
        p_allow = area_shear * ilss * kf
        tau_app = p_t / (area_shear * kf)
        ms = (p_allow / p_t) - _ONE
        return {
            "pull_through_stress_mpa": quantize(tau_app, "0.001"),
            "allowable_load_n": quantize(p_allow, "0.01"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_adhesive_single_lap_volkersen(inputs: dict[str, Any]) -> dict[str, str]:
    """Volkersen closed-form differential shear-lag peak adhesive shear stress."""
    with localcontext() as ctx:
        ctx.prec = 50
        load_n = _pos(inputs["tensile_load_n"], "tensile_load_n")
        b = _pos(inputs["overlap_width_mm"], "overlap_width_mm")
        l_ov = _pos(inputs["overlap_length_mm"], "overlap_length_mm")
        g_adh = _pos(inputs["adhesive_shear_modulus_mpa"], "adhesive_shear_modulus_mpa")
        t_adh = _pos(inputs["adhesive_thickness_mm"], "adhesive_thickness_mm")
        e_adh = _pos(inputs["adherend_modulus_mpa"], "adherend_modulus_mpa")
        t_adh_plate = _pos(inputs["adherend_thickness_mm"], "adherend_thickness_mm")
        tau_allow = _pos(inputs["adhesive_shear_allowable_mpa"], "adhesive_shear_allowable_mpa")

        tau_avg = load_n / (b * l_ov)
        # Shear-lag parameter omega * L = sqrt((2 * G_a * L^2) / (E * t_plate * t_adh))
        # for equal adherends
        w_l = ((_TWO * g_adh * l_ov * l_ov) / (e_adh * t_adh_plate * t_adh)).sqrt()
        half_wl = w_l / _TWO
        # coth(x) = (exp(x) + exp(-x)) / (exp(x) - exp(-x))
        ex_p = half_wl.exp()
        ex_m = (-half_wl).exp()
        denom = ex_p - ex_m
        coth_half = (ex_p + ex_m) / denom if denom != _ZERO else _ONE
        tau_peak = tau_avg * half_wl * coth_half
        ms = (tau_allow / tau_peak) - _ONE
        return {
            "average_shear_mpa": quantize(tau_avg, "0.001"),
            "peak_volkersen_shear_mpa": quantize(tau_peak, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


# ---------------------------------------------------------------------------
# 19..25: Thin-Walled Stability & Wing/Fuselage Sizing
# ---------------------------------------------------------------------------


def run_johnson_euler_column(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        p_comp = _pos(inputs["compressive_load_n"], "compressive_load_n")
        area = _pos(inputs["section_area_mm2"], "section_area_mm2")
        i_min = _pos(inputs["min_inertia_mm4"], "min_inertia_mm4")
        length = _pos(inputs["column_length_mm"], "column_length_mm")
        c_end = _pos(inputs["end_fixity_c"], "end_fixity_c")
        e_mpa = _pos(inputs["modulus_mpa"], "modulus_mpa")
        fcy = _pos(inputs["compressive_yield_mpa"], "compressive_yield_mpa")

        rho_g = (i_min / area).sqrt()
        slenderness = length / (c_end.sqrt() * rho_g)
        lam_c = (_TWO * _PI * _PI * e_mpa / fcy).sqrt()
        if slenderness <= lam_c:
            # Johnson parabolic curve
            sigma_cr = fcy * (
                _ONE - (fcy * slenderness * slenderness) / (Decimal("4") * _PI * _PI * e_mpa)
            )
            regime = "1"  # Johnson inelastic
        else:
            sigma_cr = (_PI * _PI * e_mpa) / (slenderness * slenderness)
            regime = "2"  # Euler elastic
        sigma_app = p_comp / area
        ms = (sigma_cr / sigma_app) - _ONE
        return {
            "effective_slenderness": quantize(slenderness, "0.001"),
            "critical_stress_mpa": quantize(sigma_cr, "0.001"),
            "regime_code": regime,
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_needham_crippling_section(inputs: dict[str, Any]) -> dict[str, str]:
    """Needham crippling formula for extruded/formed stiffener flange + web segments."""
    with localcontext() as ctx:
        ctx.prec = 50
        p_comp = _pos(inputs["compressive_load_n"], "compressive_load_n")
        b_flange = _pos(inputs["flange_width_mm"], "flange_width_mm")
        t_flange = _pos(inputs["flange_thickness_mm"], "flange_thickness_mm")
        b_web = _pos(inputs["web_width_mm"], "web_width_mm")
        t_web = _pos(inputs["web_thickness_mm"], "web_thickness_mm")
        e_mpa = _pos(inputs["modulus_mpa"], "modulus_mpa")
        fcy = _pos(inputs["compressive_yield_mpa"], "compressive_yield_mpa")

        # Needham C_e coefficients: 0.316 one edge free (flange), 0.366 no edge free (web)
        sqrt_efcy = (fcy * e_mpa).sqrt()
        s_flange = min(
            fcy, Decimal("0.316") * sqrt_efcy * _pow(t_flange / b_flange, Decimal("0.75"))
        )
        s_web = min(fcy, Decimal("0.366") * sqrt_efcy * _pow(t_web / b_web, Decimal("0.75")))
        a_flange = _TWO * b_flange * t_flange
        a_web = b_web * t_web
        a_total = a_flange + a_web
        sigma_cc = (a_flange * s_flange + a_web * s_web) / a_total
        sigma_app = p_comp / a_total
        ms = (sigma_cc / sigma_app) - _ONE
        return {
            "flange_crippling_mpa": quantize(s_flange, "0.001"),
            "web_crippling_mpa": quantize(s_web, "0.001"),
            "section_crippling_mpa": quantize(sigma_cc, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_shear_web_diagonal_tension(inputs: dict[str, Any]) -> dict[str, str]:
    """Kuhn incomplete diagonal tension web shear."""
    with localcontext() as ctx:
        ctx.prec = 50
        v_shear = _pos(inputs["applied_shear_n"], "applied_shear_n")
        h_web = _pos(inputs["web_depth_mm"], "web_depth_mm")
        t_web = _pos(inputs["web_thickness_mm"], "web_thickness_mm")
        pitch = _pos(inputs["stiffener_pitch_mm"], "stiffener_pitch_mm")
        e_mpa = _pos(inputs["modulus_mpa"], "modulus_mpa")
        fsu = _pos(inputs["web_shear_ultimate_mpa"], "web_shear_ultimate_mpa")

        tau_app = v_shear / (h_web * t_web)
        b_short = min(h_web, pitch)
        a_long = max(h_web, pitch)
        ks = Decimal("4.83") + Decimal("3.6") * ((b_short / a_long) ** 2)
        tau_cr = ks * e_mpa * ((t_web / b_short) ** 2)
        ratio = tau_app / tau_cr
        if ratio <= _ONE:
            k_idt = _ZERO
        else:
            # tanh(0.5 * ln(tau / tau_cr))
            ln_r = _ln(ratio)
            arg = Decimal("0.5") * ln_r
            ep = arg.exp()
            em = (-arg).exp()
            k_idt = (ep - em) / (ep + em)
        tau_eff = tau_app * (_ONE + Decimal("0.25") * k_idt)
        ms = (fsu / tau_eff) - _ONE
        return {
            "applied_shear_stress_mpa": quantize(tau_app, "0.001"),
            "initial_buckling_shear_mpa": quantize(tau_cr, "0.001"),
            "diagonal_tension_factor_k": quantize(k_idt, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_curved_panel_compression_shear(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_c = _nonneg(inputs["compressive_stress_mpa"], "compressive_stress_mpa")
        tau_s = _nonneg(inputs["shear_stress_mpa"], "shear_stress_mpa")
        b = _pos(inputs["arc_width_mm"], "arc_width_mm")
        t = _pos(inputs["skin_thickness_mm"], "skin_thickness_mm")
        r_curv = _pos(inputs["radius_curvature_mm"], "radius_curvature_mm")
        e_mpa = _pos(inputs["modulus_mpa"], "modulus_mpa")
        nu = _pos(inputs["poisson_nu"], "poisson_nu")

        # Batdorf curvature Z = (b^2 / (R*t)) * sqrt(1 - nu^2)
        z_batdorf = (b * b / (r_curv * t)) * (_ONE - nu * nu).sqrt()
        # Flat + curvature buckling knock-up per NASA SP-8007
        kc = Decimal("3.62") + Decimal("0.11") * z_batdorf
        ks = Decimal("4.83") + Decimal("0.09") * z_batdorf
        sigma_cr = kc * e_mpa * ((t / b) ** 2)
        tau_cr = ks * e_mpa * ((t / b) ** 2)
        rc = sigma_c / sigma_cr
        rs = tau_s / tau_cr
        comb = rc + rs * rs
        if comb <= _ZERO:
            raise AbstainError("outside_validity")
        # Solve R_c * sf + R_s^2 * sf^2 = 1 for load reserve factor sf
        if rs == _ZERO:
            sf = _ONE / rc
        else:
            sf = (-rc + (rc * rc + Decimal("4") * rs * rs).sqrt()) / (_TWO * rs * rs)
        return {
            "batdorf_curvature_z": quantize(z_batdorf, "0.001"),
            "critical_compression_mpa": quantize(sigma_cr, "0.001"),
            "critical_shear_mpa": quantize(tau_cr, "0.001"),
            "margin_of_safety": quantize(sf - _ONE, "0.0001"),
        }


def run_inter_rivet_buckling(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_comp = _pos(inputs["compressive_stress_mpa"], "compressive_stress_mpa")
        p_riv = _pos(inputs["rivet_pitch_mm"], "rivet_pitch_mm")
        t_skin = _pos(inputs["skin_thickness_mm"], "skin_thickness_mm")
        c_fix = _pos(inputs["rivet_head_fixity_c"], "rivet_head_fixity_c")
        e_tan = _pos(inputs["tangent_modulus_mpa"], "tangent_modulus_mpa")

        sigma_ir = (c_fix * _PI * _PI * e_tan / Decimal("12")) * ((t_skin / p_riv) ** 2)
        ms = (sigma_ir / sigma_comp) - _ONE
        return {
            "inter_rivet_critical_mpa": quantize(sigma_ir, "0.001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_thin_walled_bredt_batho_torsion(inputs: dict[str, Any]) -> dict[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        torque = _pos(inputs["torque_nmm"], "torque_nmm")
        a_m = _pos(inputs["enclosed_area_mm2"], "enclosed_area_mm2")
        perim = _pos(inputs["perimeter_mm"], "perimeter_mm")
        t_min = _pos(inputs["min_wall_thickness_mm"], "min_wall_thickness_mm")
        g_mpa = _pos(inputs["shear_modulus_mpa"], "shear_modulus_mpa")
        fsu = _pos(inputs["shear_allowable_mpa"], "shear_allowable_mpa")

        q_flow = torque / (_TWO * a_m)
        tau_max = q_flow / t_min
        twist_rad_per_mm = (q_flow * perim) / (_TWO * a_m * g_mpa * t_min)
        ms = (fsu / tau_max) - _ONE
        return {
            "shear_flow_n_per_mm": quantize(q_flow, "0.001"),
            "max_torsional_shear_mpa": quantize(tau_max, "0.001"),
            "twist_rate_rad_per_m": quantize(twist_rad_per_mm * Decimal("1000"), "0.00001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_sandwich_core_shear_wrinkling(inputs: dict[str, Any]) -> dict[str, str]:
    """Hoff facesheet wrinkling + honeycomb core shear check."""
    with localcontext() as ctx:
        ctx.prec = 50
        sigma_f = _pos(inputs["facesheet_stress_mpa"], "facesheet_stress_mpa")
        v_shear = _pos(inputs["transverse_shear_n_per_mm"], "transverse_shear_n_per_mm")
        t_f = _pos(inputs["facesheet_thickness_mm"], "facesheet_thickness_mm")
        t_c = _pos(inputs["core_thickness_mm"], "core_thickness_mm")
        e_f = _pos(inputs["facesheet_modulus_mpa"], "facesheet_modulus_mpa")
        e_c = _pos(inputs["core_compression_modulus_mpa"], "core_compression_modulus_mpa")
        g_c = _pos(inputs["core_shear_modulus_mpa"], "core_shear_modulus_mpa")
        f_cs_allow = _pos(inputs["core_shear_allowable_mpa"], "core_shear_allowable_mpa")

        # Hoff wrinkling stress: sigma_wr = 0.5 * (E_f * E_c * G_c)^(1/3)
        sigma_wr = Decimal("0.5") * _pow(e_f * e_c * g_c, _ONE / Decimal("3"))
        tau_core = v_shear / (t_c + t_f)
        ms_wr = (sigma_wr / sigma_f) - _ONE
        ms_core = (f_cs_allow / tau_core) - _ONE
        return {
            "wrinkling_critical_mpa": quantize(sigma_wr, "0.001"),
            "core_shear_stress_mpa": quantize(tau_core, "0.001"),
            "margin_of_safety": quantize(min(ms_wr, ms_core), "0.0001"),
        }


def run_mmpds_allowable_lookup(inputs: dict[str, Any]) -> dict[str, str]:
    """Direct traceable MMPDS-16 / CMH-17 allowable query helper."""
    res = lookup_allowable(
        str(inputs["material_id"]),
        basis=str(inputs.get("basis", "A")),
        property_name=str(inputs.get("property_name", "fty_mpa")),
        thickness_mm=str(inputs.get("thickness_mm", "10")),
        temp_c=str(inputs.get("temp_c", "23")),
        environment=str(inputs.get("environment", "RTD")),
    )
    return {
        "allowable_value_mpa": str(res["allowable_value_mpa"]),
        "knockdown_factor": str(res["knockdown_factor"]),
        "catalog_sha256": str(res["catalog_sha256"]),
    }


STRESS_MANUAL_RUNNERS = {
    "nasgro_paris_crack_growth": run_nasgro_paris_crack_growth,
    "goodman_haigh_mean_stress": run_goodman_haigh_mean_stress,
    "neuber_notch_plasticity": run_neuber_notch_plasticity,
    "net_section_yielding_fracture": run_net_section_yielding_fracture,
    "rainflow_spectrum_damage": run_rainflow_spectrum_damage,
    "tsai_wu_ply_failure": run_tsai_wu_ply_failure,
    "hashin_composite_modes": run_hashin_composite_modes,
    "puck_interfiber_fracture": run_puck_interfiber_fracture,
    "open_hole_tension_oht": run_open_hole_tension_oht,
    "open_hole_compression_ohc": run_open_hole_compression_ohc,
    "compression_after_impact_cai": run_compression_after_impact_cai,
    "huth_fastener_flexibility": run_huth_fastener_flexibility,
    "bearing_bypass_interaction": run_bearing_bypass_interaction,
    "eccentric_bolt_group_cg": run_eccentric_bolt_group_cg,
    "lug_axial_transverse_interaction": run_lug_axial_transverse_interaction,
    "bolt_preload_thermal_relaxation": run_bolt_preload_thermal_relaxation,
    "fastener_pull_through_composite": run_fastener_pull_through_composite,
    "adhesive_single_lap_volkersen": run_adhesive_single_lap_volkersen,
    "johnson_euler_column": run_johnson_euler_column,
    "needham_crippling_section": run_needham_crippling_section,
    "shear_web_diagonal_tension": run_shear_web_diagonal_tension,
    "curved_panel_compression_shear": run_curved_panel_compression_shear,
    "inter_rivet_buckling": run_inter_rivet_buckling,
    "thin_walled_bredt_batho_torsion": run_thin_walled_bredt_batho_torsion,
    "sandwich_core_shear_wrinkling": run_sandwich_core_shear_wrinkling,
}


def _wrap_stress_card_runner(method_id: str, fn: Any) -> Any:
    """Wrap a pure stress manual calculator into a standard registry card runner."""

    def _runner(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
        limits = card.get("limits", {})
        required = card.get("required", [])
        validated: dict[str, Any] = dict(inputs)
        for key in required:
            if key not in inputs:
                raise AbstainError("missing_required_input")
            if key in limits:
                validated[key] = parse_limited_decimal(inputs[key], limits[key])
        outputs = fn(validated)
        return {
            "method_id": str(card["method_id"]),
            "method_version": str(card["method_version"]),
            "outputs": outputs,
            "sources": list(card["sources"]),
            "card_title": str(card["title"]),
            "label": str(card["label"]),
        }

    _runner.__name__ = f"card_runner_{method_id}"
    return _runner


STRESS_MANUAL_CARD_RUNNERS: dict[str, Any] = {
    method_id: _wrap_stress_card_runner(method_id, fn)
    for method_id, fn in STRESS_MANUAL_RUNNERS.items()
}


def evaluate_stress_manual_unrounded(
    method_id: str,
    inputs: dict[str, Any],
) -> dict[str, Decimal]:
    """Capture 50-digit unrounded Decimal intermediates matching Stress Office outputs."""
    fn = STRESS_MANUAL_RUNNERS.get(method_id)
    if fn is None:
        return {}
    buf: deque[tuple[str, Decimal]] = deque()
    token = _CAPTURE_RAW.set(buf)
    try:
        outputs = fn(inputs)
    finally:
        _CAPTURE_RAW.reset(token)
    unrounded: dict[str, Decimal] = {}
    for key, formatted in outputs.items():
        if buf and buf[0][0] == formatted:
            _, raw_val = buf.popleft()
            unrounded[key] = raw_val
    return unrounded
