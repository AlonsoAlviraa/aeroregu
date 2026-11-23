"""Five Deterministic Rotorcraft & Composite Stress Office Methods (Exact Decimal Precision).

Methods:
1. clt_laminate_abd_stiffness      - 4-ply Classical Lamination Theory [A, B, D] & ply exposure MS
2. rotor_blade_centrifugal_bending - Rotor blade CF + flap/lag bending + Goodman fatigue MS
3. ground_resonance_coleman_screen - Coleman/Deutsch ground resonance speed & damping stability
4. cs29_crashworthiness_561_562_load - CS 29.561 ultimate inertia + CS 29.562 triangular pulse
5. multirow_bolt_load_distribution - Elastic 3-row splice load sharing (Huth + plate compliance)
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import parse_limited_decimal
from evidence_calc.stress_manual import (
    _ONE,
    _TWO,
    _ZERO,
    _cos_deg,
    _d,
    _pos,
    _pow,
    _sin_deg,
    quantize,
)

_THREE = Decimal("3")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_TEN = Decimal("10")
_TWENTY = Decimal("20")
_HUNDRED = Decimal("100")
_THOUSAND = Decimal("1000")
_G0 = Decimal("9.80665")


def _solve_linear_system(matrix: list[list[Decimal]], rhs: list[Decimal]) -> list[Decimal]:
    """Solve dense NxN linear system via partial-pivoting Gaussian elimination in Decimal."""
    n = len(rhs)
    aug = [list(matrix[r]) + [rhs[r]] for r in range(n)]
    with localcontext() as ctx:
        ctx.prec = 60
        for col in range(n):
            piv_row = col
            piv_abs = abs(aug[col][col])
            for r in range(col + 1, n):
                cand = abs(aug[r][col])
                if cand > piv_abs:
                    piv_abs = cand
                    piv_row = r
            if piv_abs <= Decimal("1e-30"):
                raise AbstainError("outside_validity")
            if piv_row != col:
                aug[col], aug[piv_row] = aug[piv_row], aug[col]
            piv = aug[col][col]
            for c in range(col, n + 1):
                aug[col][c] = aug[col][c] / piv
            for r in range(n):
                if r == col:
                    continue
                factor = aug[r][col]
                if factor == _ZERO:
                    continue
                for c in range(col, n + 1):
                    aug[r][c] = aug[r][c] - factor * aug[col][c]
        return [aug[r][n] for r in range(n)]


def run_clt_laminate_abd_stiffness(inputs: dict[str, Any]) -> dict[str, str]:
    """Compute Classical Lamination Theory [A, B, D] matrices, effective moduli & ply MS."""
    with localcontext() as ctx:
        ctx.prec = 55
        thetas = [
            _d(inputs["theta_1_deg"], "theta_1_deg"),
            _d(inputs["theta_2_deg"], "theta_2_deg"),
            _d(inputs["theta_3_deg"], "theta_3_deg"),
            _d(inputs["theta_4_deg"], "theta_4_deg"),
        ]
        t_ply = _pos(inputs["ply_thickness_mm"], "ply_thickness_mm")
        e1 = _pos(inputs["e1_mpa"], "e1_mpa")
        e2 = _pos(inputs["e2_mpa"], "e2_mpa")
        g12 = _pos(inputs["g12_mpa"], "g12_mpa")
        nu12 = _d(inputs["nu12"], "nu12")
        nx = _d(inputs["nx_n_per_mm"], "nx_n_per_mm")
        ny = _d(inputs["ny_n_per_mm"], "ny_n_per_mm")
        nxy = _d(inputs["nxy_n_per_mm"], "nxy_n_per_mm")
        mx = _d(inputs["mx_n_mm_per_mm"], "mx_n_mm_per_mm")
        xt = _pos(inputs["xt_mpa"], "xt_mpa")
        yt = _pos(inputs["yt_mpa"], "yt_mpa")
        s12_allow = _pos(inputs["s12_mpa"], "s12_mpa")

        nu21 = nu12 * e2 / e1
        denom = _ONE - (nu12 * nu21)
        if denom <= _ZERO:
            raise AbstainError("outside_validity")

        q11 = e1 / denom
        q22 = e2 / denom
        q12 = nu12 * e2 / denom
        q66 = g12

        total_h = _FOUR * t_ply
        half_h = total_h / _TWO

        a_mat = [[_ZERO, _ZERO, _ZERO] for _ in range(3)]
        b_mat = [[_ZERO, _ZERO, _ZERO] for _ in range(3)]
        d_mat = [[_ZERO, _ZERO, _ZERO] for _ in range(3)]

        ply_data: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
        for idx, theta in enumerate(thetas):
            z0 = -half_h + Decimal(idx) * t_ply
            z1 = z0 + t_ply
            c = _cos_deg(theta)
            s = _sin_deg(theta)
            c2 = c * c
            s2 = s * s
            c4 = c2 * c2
            s4 = s2 * s2
            sc = s * c

            qbar_11 = q11 * c4 + _TWO * (q12 + _TWO * q66) * s2 * c2 + q22 * s4
            qbar_12 = (q11 + q22 - _FOUR * q66) * s2 * c2 + q12 * (s4 + c4)
            qbar_22 = q11 * s4 + _TWO * (q12 + _TWO * q66) * s2 * c2 + q22 * c4
            qbar_16 = (q11 - q12 - _TWO * q66) * sc * c2 + (q12 - q22 + _TWO * q66) * s2 * sc
            qbar_26 = (q11 - q12 - _TWO * q66) * s2 * sc + (q12 - q22 + _TWO * q66) * sc * c2
            qbar_66 = (q11 + q22 - _TWO * q12 - _TWO * q66) * s2 * c2 + q66 * (s4 + c4)

            qb = [
                [qbar_11, qbar_12, qbar_16],
                [qbar_12, qbar_22, qbar_26],
                [qbar_16, qbar_26, qbar_66],
            ]
            dz1 = z1 - z0
            dz2 = (z1 * z1 - z0 * z0) / _TWO
            dz3 = (z1 * z1 * z1 - z0 * z0 * z0) / _THREE
            for i in range(3):
                for j in range(3):
                    a_mat[i][j] += qb[i][j] * dz1
                    b_mat[i][j] += qb[i][j] * dz2
                    d_mat[i][j] += qb[i][j] * dz3
            ply_data.append((c, s, z0, z1))

        max_abs_b = max(abs(b_mat[i][j]) for i in range(3) for j in range(3))

        # Assemble 6x6 [A, B; B, D] system for [eps0_x, eps0_y, gamma0_xy, kx, ky, kxy]
        abd = [[_ZERO for _ in range(6)] for _ in range(6)]
        for i in range(3):
            for j in range(3):
                abd[i][j] = a_mat[i][j]
                abd[i][j + 3] = b_mat[i][j]
                abd[i + 3][j] = b_mat[i][j]
                abd[i + 3][j + 3] = d_mat[i][j]

        load_vec = [nx, ny, nxy, mx, _ZERO, _ZERO]
        sol = _solve_linear_system(abd, load_vec)
        eps0 = sol[:3]
        kappa = sol[3:]

        # Effective laminate membrane engineering constants from [A]^{-1}
        a_inv_c0 = _solve_linear_system(a_mat, [_ONE, _ZERO, _ZERO])
        a_inv_c1 = _solve_linear_system(a_mat, [_ZERO, _ONE, _ZERO])
        a_inv_c2 = _solve_linear_system(a_mat, [_ZERO, _ZERO, _ONE])
        a11_inv = a_inv_c0[0]
        a21_inv = a_inv_c0[1]
        a22_inv = a_inv_c1[1]
        a66_inv = a_inv_c2[2]
        if a11_inv <= _ZERO or a22_inv <= _ZERO or a66_inv <= _ZERO:
            raise AbstainError("outside_validity")

        ex_eff = _ONE / (total_h * a11_inv)
        ey_eff = _ONE / (total_h * a22_inv)
        gxy_eff = _ONE / (total_h * a66_inv)
        nuxy_eff = -(a21_inv / a11_inv)

        max_fi = _ZERO
        for c, s, z0, z1 in ply_data:
            c2 = c * c
            s2 = s * s
            sc = s * c
            for z_pt in (z0, z1):
                ex = eps0[0] + z_pt * kappa[0]
                ey = eps0[1] + z_pt * kappa[1]
                gxy = eps0[2] + z_pt * kappa[2]

                # Transform global engineering strain -> ply principal strain (1, 2, gamma12)
                e1 = c2 * ex + s2 * ey + sc * gxy
                e2_loc = s2 * ex + c2 * ey - sc * gxy
                g12_loc = -_TWO * sc * ex + _TWO * sc * ey + (c2 - s2) * gxy

                sig1 = q11 * e1 + q12 * e2_loc
                sig2 = q12 * e1 + q22 * e2_loc
                tau12 = q66 * g12_loc

                fi = ((sig1 / xt) ** 2 + (sig2 / yt) ** 2 + (tau12 / s12_allow) ** 2).sqrt()
                if fi > max_fi:
                    max_fi = fi

        if max_fi <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (_ONE / max_fi) - _ONE

        return {
            "a11_n_per_mm": quantize(a_mat[0][0], "0.0001"),
            "a22_n_per_mm": quantize(a_mat[1][1], "0.0001"),
            "a66_n_per_mm": quantize(a_mat[2][2], "0.0001"),
            "d11_n_mm": quantize(d_mat[0][0], "0.0001"),
            "d22_n_mm": quantize(d_mat[1][1], "0.0001"),
            "d66_n_mm": quantize(d_mat[2][2], "0.0001"),
            "max_abs_b_coupling": quantize(max_abs_b, "0.0001"),
            "ex_eff_mpa": quantize(ex_eff, "0.0001"),
            "ey_eff_mpa": quantize(ey_eff, "0.0001"),
            "gxy_eff_mpa": quantize(gxy_eff, "0.0001"),
            "nuxy_eff": quantize(nuxy_eff, "0.0001"),
            "midplane_strain_x": quantize(eps0[0], "0.0001"),
            "midplane_strain_y": quantize(eps0[1], "0.0001"),
            "midplane_shear_xy": quantize(eps0[2], "0.0001"),
            "curvature_x_per_mm": quantize(kappa[0], "0.0001"),
            "max_ply_failure_index": quantize(max_fi, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


def run_rotor_blade_centrifugal_bending(inputs: dict[str, Any]) -> dict[str, str]:
    """Rotor blade root centrifugal tension + flap/lag bending + Modified Goodman fatigue."""
    with localcontext() as ctx:
        ctx.prec = 50
        m_blade = _pos(inputs["blade_mass_kg"], "blade_mass_kg")
        omega = _pos(inputs["rotor_omega_rad_s"], "rotor_omega_rad_s")
        r_cg = _pos(inputs["cg_radius_m"], "cg_radius_m")
        area = _pos(inputs["root_area_mm2"], "root_area_mm2")
        z_mod = _pos(inputs["root_section_modulus_mm3"], "root_section_modulus_mm3")
        m_flap = abs(_d(inputs["flap_bending_moment_n_m"], "flap_bending_moment_n_m"))
        m_lag = abs(_d(inputs["lag_bending_moment_n_m"], "lag_bending_moment_n_m"))
        f_tu = _pos(inputs["ultimate_tensile_mpa"], "ultimate_tensile_mpa")
        s_end = _pos(inputs["endurance_limit_mpa"], "endurance_limit_mpa")
        sf = _pos(inputs["safety_factor"], "safety_factor")
        if sf < _ONE:
            raise AbstainError("outside_validity")

        cf_force = m_blade * (omega * omega) * r_cg
        cf_stress = cf_force / area
        flap_stress = (m_flap * _THOUSAND) / z_mod
        lag_stress = (m_lag * _THOUSAND) / z_mod

        steady_mean = cf_stress
        alt_stress = (flap_stress * flap_stress + lag_stress * lag_stress).sqrt()
        peak_stress = steady_mean + alt_stress
        if peak_stress <= _ZERO:
            raise AbstainError("outside_validity")

        static_ms = (f_tu / (peak_stress * sf)) - _ONE
        goodman_util = (steady_mean / f_tu) + (alt_stress / s_end)
        if goodman_util <= _ZERO:
            raise AbstainError("outside_validity")
        goodman_rf = _ONE / goodman_util
        fatigue_ms = (goodman_rf / sf) - _ONE

        return {
            "centrifugal_force_n": quantize(cf_force, "0.001"),
            "centrifugal_stress_mpa": quantize(cf_stress, "0.001"),
            "flap_bending_stress_mpa": quantize(flap_stress, "0.001"),
            "lag_bending_stress_mpa": quantize(lag_stress, "0.001"),
            "steady_mean_stress_mpa": quantize(steady_mean, "0.001"),
            "alternating_stress_mpa": quantize(alt_stress, "0.001"),
            "peak_combined_stress_mpa": quantize(peak_stress, "0.001"),
            "static_margin_of_safety": quantize(static_ms, "0.001"),
            "goodman_reserve_factor": quantize(goodman_rf, "0.001"),
            "fatigue_margin_of_safety": quantize(fatigue_ms, "0.001"),
        }


def run_ground_resonance_coleman_screen(inputs: dict[str, Any]) -> dict[str, str]:
    """Coleman/Deutsch ground resonance coalescence separation & damping product margin."""
    with localcontext() as ctx:
        ctx.prec = 50
        omega = _pos(inputs["rotor_omega_rad_s"], "rotor_omega_rad_s")
        w_lag = _pos(inputs["blade_lead_lag_freq_rad_s"], "blade_lead_lag_freq_rad_s")
        w_fus = _pos(inputs["fuselage_mode_freq_rad_s"], "fuselage_mode_freq_rad_s")
        zeta_lag = _pos(inputs["blade_lag_damping_ratio"], "blade_lag_damping_ratio")
        zeta_fus = _pos(inputs["fuselage_damping_ratio"], "fuselage_damping_ratio")
        mu_mass = _pos(inputs["mass_coupling_ratio"], "mass_coupling_ratio")
        min_factor = _pos(inputs["min_damping_margin_factor"], "min_damping_margin_factor")
        if min_factor < _ONE:
            raise AbstainError("outside_validity")

        nu_lag = w_lag / omega
        regressive_freq = abs(omega - w_lag)
        coal_speed = w_fus + w_lag
        speed_sep_pct = (abs(omega - coal_speed) / coal_speed) * _HUNDRED

        damping_prod = zeta_lag * zeta_fus
        coleman_thresh = (mu_mass / _FOUR) * (omega / (w_lag + w_fus))
        if coleman_thresh <= _ZERO:
            raise AbstainError("outside_validity")
        stab_ratio = damping_prod / coleman_thresh
        stab_ms = (stab_ratio / min_factor) - _ONE

        return {
            "lag_freq_ratio_nu": quantize(nu_lag, "0.0001"),
            "regressive_lag_freq_rad_s": quantize(regressive_freq, "0.0001"),
            "coalescence_rotor_speed_rad_s": quantize(coal_speed, "0.0001"),
            "speed_separation_pct": quantize(speed_sep_pct, "0.0001"),
            "damping_product_actual": quantize(damping_prod, "0.0001"),
            "coleman_damping_threshold": quantize(coleman_thresh, "0.0001"),
            "damping_stability_ratio": quantize(stab_ratio, "0.0001"),
            "stability_margin_of_safety": quantize(stab_ms, "0.0001"),
        }


def run_cs29_crashworthiness_561_562_load(inputs: dict[str, Any]) -> dict[str, str]:
    """CS 29.561 emergency landing ultimate inertia loads + CS 29.562 triangular dynamic pulse."""
    with localcontext() as ctx:
        ctx.prec = 50
        mass = _pos(inputs["occupant_seat_mass_kg"], "occupant_seat_mass_kg")
        dv = _pos(inputs["delta_v_m_s"], "delta_v_m_s")
        t_rise = _pos(inputs["rise_time_s"], "rise_time_s")
        n_bolts = _pos(inputs["attachment_bolt_count"], "attachment_bolt_count")
        bolt_allow = _pos(inputs["bolt_allowable_load_n"], "bolt_allowable_load_n")
        fit_factor = _pos(inputs["floor_fitting_factor"], "floor_fitting_factor")
        if fit_factor < _ONE:
            raise AbstainError("outside_validity")

        ult_fwd = mass * _G0 * _TWENTY * fit_factor
        ult_down = mass * _G0 * _TWENTY * fit_factor
        ult_side = mass * _G0 * _TEN * fit_factor

        peak_g_562 = dv / (_G0 * t_rise)
        dyn_load = mass * (dv / t_rise) * fit_factor

        governing = max(ult_fwd, ult_down, dyn_load)
        per_bolt = governing / n_bolts
        if per_bolt <= _ZERO:
            raise AbstainError("outside_validity")
        ms = (bolt_allow / per_bolt) - _ONE

        return {
            "ultimate_forward_load_n": quantize(ult_fwd, "0.001"),
            "ultimate_downward_load_n": quantize(ult_down, "0.001"),
            "ultimate_sideward_load_n": quantize(ult_side, "0.001"),
            "cs29_562_peak_g": quantize(peak_g_562, "0.001"),
            "dynamic_pulse_load_n": quantize(dyn_load, "0.001"),
            "governing_design_load_n": quantize(governing, "0.001"),
            "per_attachment_load_n": quantize(per_bolt, "0.001"),
            "margin_of_safety": quantize(ms, "0.001"),
        }


def run_multirow_bolt_load_distribution(inputs: dict[str, Any]) -> dict[str, str]:
    """Solve elastic 3-row single-shear bolted splice load sharing using Huth compliance."""
    with localcontext() as ctx:
        ctx.prec = 55
        p_tot = _pos(inputs["total_applied_load_n"], "total_applied_load_n")
        pitch = _pos(inputs["pitch_mm"], "pitch_mm")
        width = _pos(inputs["width_mm"], "width_mm")
        t1 = _pos(inputs["plate1_thickness_mm"], "plate1_thickness_mm")
        t2 = _pos(inputs["plate2_thickness_mm"], "plate2_thickness_mm")
        e1 = _pos(inputs["plate1_modulus_mpa"], "plate1_modulus_mpa")
        e2 = _pos(inputs["plate2_modulus_mpa"], "plate2_modulus_mpa")
        d = _pos(inputs["bolt_diameter_mm"], "bolt_diameter_mm")
        eb = _pos(inputs["bolt_modulus_mpa"], "bolt_modulus_mpa")
        f_bru = _pos(inputs["bearing_allowable_mpa"], "bearing_allowable_mpa")
        if width <= d:
            raise AbstainError("outside_validity")

        a_exp = _TWO / _THREE
        geom = _pow((t1 + t2) / (_TWO * d), a_exp)
        compl = (
            (_ONE / (t1 * e1))
            + (_ONE / (t2 * e2))
            + (_ONE / (_TWO * t1 * eb))
            + (_ONE / (_TWO * t2 * eb))
        )
        c_f = geom * _THREE * compl

        c_p1 = pitch / (e1 * width * t1)
        c_p2 = pitch / (e2 * width * t2)

        mat = [
            [c_f + c_p1 + c_p2, -c_f, _ZERO],
            [c_p2, c_f + c_p2, -(c_f + c_p1)],
            [_ONE, _ONE, _ONE],
        ]
        rhs = [c_p1 * p_tot, _ZERO, p_tot]
        p1, p2, p3 = _solve_linear_system(mat, rhs)

        peak_load = max(p1, p2, p3)
        peak_frac = peak_load / p_tot
        t_min = min(t1, t2)
        peak_brg = peak_load / (d * t_min)
        if peak_brg <= _ZERO:
            raise AbstainError("outside_validity")
        bypass_r2 = p_tot - p1 - p2
        ms = (f_bru / peak_brg) - _ONE

        return {
            "huth_flexibility_mm_per_n": quantize(c_f, "0.0001"),
            "row1_load_n": quantize(p1, "0.0001"),
            "row2_load_n": quantize(p2, "0.0001"),
            "row3_load_n": quantize(p3, "0.0001"),
            "peak_row_load_fraction": quantize(peak_frac, "0.0001"),
            "peak_bearing_stress_mpa": quantize(peak_brg, "0.0001"),
            "bypass_load_row2_n": quantize(bypass_r2, "0.0001"),
            "margin_of_safety": quantize(ms, "0.0001"),
        }


ROTORCRAFT_STRESS_RUNNERS: dict[str, Any] = {
    "clt_laminate_abd_stiffness": run_clt_laminate_abd_stiffness,
    "rotor_blade_centrifugal_bending": run_rotor_blade_centrifugal_bending,
    "ground_resonance_coleman_screen": run_ground_resonance_coleman_screen,
    "cs29_crashworthiness_561_562_load": run_cs29_crashworthiness_561_562_load,
    "multirow_bolt_load_distribution": run_multirow_bolt_load_distribution,
}


def _wrap_rotorcraft_card_runner(method_id: str, fn: Any) -> Any:
    """Wrap a deterministic rotorcraft/composite stress calculator into a registry runner."""

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

    _runner.__name__ = f"rotorcraft_runner_{method_id}"
    return _runner


ROTORCRAFT_STRESS_CARD_RUNNERS: dict[str, Any] = {
    method_id: _wrap_rotorcraft_card_runner(method_id, fn)
    for method_id, fn in ROTORCRAFT_STRESS_RUNNERS.items()
}
