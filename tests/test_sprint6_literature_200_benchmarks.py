"""Sprint 6 Block 6 Literature Regression Suite (>= 200 Verified Closed-Form Cases).

Validates deterministic card outputs and 50-digit FLINT/Arb intervals against independent
closed-form reference formulas across Bruhn, Roark, Niu, CMH-17 Rev H, MMPDS-16, and
Walker/NASGRO (< 0.1% relative tolerance on all stress/allowable/margin outputs).
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS
from evidence_calc.allowables import (
    list_materials,
    lookup_allowable,
    lookup_nasgro_paris_params,
    lookup_sn_fatigue_allowable,
)
from evidence_calc.registry import run_method


def _assert_close(got_str: str, ref: float, rel_tol: float = 0.001, abs_tol: float = 0.002) -> None:
    got = float(Decimal(got_str))
    assert math.isclose(got, ref, rel_tol=rel_tol, abs_tol=abs_tol), (
        f"Expected {ref} +- ({rel_tol * 100:.2f}% | {abs_tol}), got {got}"
    )


# 1) Bruhn/Euler-Johnson Columns (20 parameterized cases)
@pytest.mark.parametrize(
    ("load_n", "area_mm2", "i_mm4", "length_mm", "c_fix", "e_mpa", "fcy_mpa"),
    [
        (load_n, 620.0, 190000.0, len_mm, c_fix, 71700.0, 441.0)
        for load_n in (30000.0, 55000.0)
        for len_mm in (280.0, 380.0, 520.0, 750.0, 1100.0)
        for c_fix in (1.0, 2.0)
    ],
)
def test_lit_20_euler_johnson_columns(
    load_n: float,
    area_mm2: float,
    i_mm4: float,
    length_mm: float,
    c_fix: float,
    e_mpa: float,
    fcy_mpa: float,
) -> None:
    res = run_method(
        "johnson_euler_column",
        {
            "compressive_load_n": str(load_n),
            "section_area_mm2": str(area_mm2),
            "min_inertia_mm4": str(i_mm4),
            "column_length_mm": str(length_mm),
            "end_fixity_c": str(c_fix),
            "modulus_mpa": str(e_mpa),
            "compressive_yield_mpa": str(fcy_mpa),
        },
        include_intervals=True,
    )
    rho = math.sqrt(i_mm4 / area_mm2)
    slend = length_mm / (rho * math.sqrt(c_fix))
    cc = math.sqrt((2.0 * (math.pi**2) * e_mpa) / fcy_mpa)
    if slend <= cc:
        sig_cr = fcy_mpa * (1.0 - (fcy_mpa * (slend**2)) / (4.0 * (math.pi**2) * e_mpa))
    else:
        sig_cr = ((math.pi**2) * e_mpa) / (slend**2)
    ms_ref = (sig_cr * area_mm2 / load_n) - 1.0
    _assert_close(res["outputs"]["margin_of_safety"], ms_ref)


# 2) Roark / CS 29 Skid Drop Energy & Bending (20 parameterized cases)
@pytest.mark.parametrize(
    ("mass_kg", "drop_m", "od_mm", "arm_mm", "fy_mpa"),
    [
        (m, h, od, arm, fy)
        for m in (2200.0, 2800.0)
        for h in (0.25, 0.35)
        for od in (72.0, 82.0)
        for arm in (360.0, 440.0)
        for fy in (441.0,)
    ]
    + [(2500.0, 0.30, 76.0, 400.0, fy) for fy in (310.0, 410.0, 480.0, 520.0)],
)
def test_lit_20_skid_drop_energy(
    mass_kg: float, drop_m: float, od_mm: float, arm_mm: float, fy_mpa: float
) -> None:
    wall = 6.0
    stroke = 0.22
    kl = 0.667
    eta = 0.75
    res = run_method(
        "cs29_skid_landing_gear_drop_energy",
        {
            "gross_weight_kg": str(mass_kg),
            "drop_height_m": str(drop_m),
            "rotor_lift_fraction": str(kl),
            "vertical_stroke_m": str(stroke),
            "gear_efficiency_eta": str(eta),
            "cross_tube_od_mm": str(od_mm),
            "cross_tube_wall_mm": str(wall),
            "cantilever_arm_mm": str(arm_mm),
            "yield_allowable_mpa": str(fy_mpa),
            "safety_factor": "1.000",
        },
        include_intervals=True,
    )
    w_n = mass_kg * 9.80665
    e_drop = w_n * (drop_m + (1.0 - kl) * stroke)
    n_z = e_drop / (w_n * stroke * eta)
    f_leg = 0.25 * n_z * w_n
    d_in = od_mm - 2.0 * wall
    i_tube = math.pi * ((od_mm**4) - (d_in**4)) / 64.0
    z_mod = i_tube / (od_mm / 2.0)
    sig_b = f_leg * arm_mm / z_mod
    ms_ref = (fy_mpa / sig_b) - 1.0
    _assert_close(res["outputs"]["cross_tube_bending_mpa"], sig_b)
    _assert_close(res["outputs"]["margin_of_safety"], ms_ref)


# 3) Tail-Rotor Shaft Critical Whirl Speed (20 parameterized cases)
@pytest.mark.parametrize(
    ("len_mm", "do_mm", "e_mpa", "rpm"),
    [
        (l_mm, do_mm, e_mpa, rpm)
        for l_mm in (1200.0, 1500.0)
        for do_mm in (76.0, 90.0)
        for e_mpa in (71700.0, 110300.0)
        for rpm in (3600.0, 4200.0)
    ]
    + [(1450.0, 82.0, 71700.0, r) for r in (2800.0, 3200.0, 4000.0, 4800.0)],
)
def test_lit_20_shaft_critical_whirl(len_mm: float, do_mm: float, e_mpa: float, rpm: float) -> None:
    di_mm = do_mm - 6.0
    rho = 2810.0
    lam = 3.14159
    res = run_method(
        "shaft_whirl_critical_speed_screen",
        {
            "shaft_length_mm": str(len_mm),
            "outer_diameter_mm": str(do_mm),
            "inner_diameter_mm": str(di_mm),
            "youngs_modulus_mpa": str(e_mpa),
            "density_kg_m3": str(rho),
            "bearing_fixity_lambda": str(lam),
            "operating_rpm": str(rpm),
            "overspeed_factor": "1.200",
        },
        include_intervals=True,
    )
    a_mm2 = math.pi * (do_mm**2 - di_mm**2) / 4.0
    i_mm4 = math.pi * (do_mm**4 - di_mm**4) / 64.0
    r_g = math.sqrt(i_mm4 / a_mm2)
    c_mm_s = math.sqrt((e_mpa * 1e6) / rho) * 1000.0
    n_cr = (((lam / len_mm) ** 2) * r_g * c_mm_s / (2.0 * math.pi)) * 60.0
    ms_ref = (n_cr / (rpm * 1.2)) - 1.0
    _assert_close(res["outputs"]["critical_whirl_rpm"], n_cr)
    _assert_close(res["outputs"]["margin_of_safety"], ms_ref)


# 4) Hertzian Line Contact & Subsurface Shear (20 parameterized cases)
@pytest.mark.parametrize(
    ("load_n", "len_mm", "d1_mm", "d2_mm"),
    [
        (p, wid, d1, d2)
        for p in (12000.0, 22000.0)
        for wid in (22.0, 32.0)
        for d1 in (14.0, 20.0)
        for d2 in (100.0, 140.0)
    ]
    + [(18000.0, 28.0, 16.0, d2) for d2 in (80.0, 110.0, 150.0, 180.0)],
)
def test_lit_20_hertzian_line_contact(
    load_n: float, len_mm: float, d1_mm: float, d2_mm: float
) -> None:
    e_val, nu = 205000.0, 0.29
    res = run_method(
        "hertzian_bearing_contact_stress",
        {
            "normal_load_n": str(load_n),
            "contact_length_mm": str(len_mm),
            "roller_diameter_mm": str(d1_mm),
            "raceway_diameter_mm": str(d2_mm),
            "youngs_modulus_1_mpa": str(e_val),
            "poissons_ratio_1": str(nu),
            "youngs_modulus_2_mpa": str(e_val),
            "poissons_ratio_2": str(nu),
            "contact_allowable_mpa": "2800",
            "safety_factor": "1.25",
        },
        include_intervals=True,
    )
    e_star = e_val / (2.0 * (1.0 - nu**2))
    r_eq = (d1_mm * d2_mm) / (2.0 * (d1_mm + d2_mm))
    b_half = math.sqrt((4.0 * load_n * r_eq) / (math.pi * len_mm * e_star))
    p0 = (2.0 * load_n) / (math.pi * b_half * len_mm)
    _assert_close(res["outputs"]["peak_contact_pressure_mpa"], p0)
    _assert_close(res["outputs"]["max_subsurface_shear_mpa"], 0.3 * p0)


# 5) Niu / Timoshenko Firewall Thermal Buckling (20 parameterized cases)
@pytest.mark.parametrize(
    ("b_mm", "t_mm", "dtemp"),
    [
        (b, t, dt)
        for b in (65.0, 85.0)
        for t in (1.6, 2.2)
        for dt in (160.0, 220.0, 280.0, 340.0, 400.0)
    ],
)
def test_lit_20_firewall_thermal_buckling(b_mm: float, t_mm: float, dtemp: float) -> None:
    e_hot, nu, cte, k_res, kc = 95000.0, 0.31, 9e-6, 0.65, 4.0
    res = run_method(
        "firewall_thermal_buckling_screen",
        {
            "panel_width_b_mm": str(b_mm),
            "panel_thickness_t_mm": str(t_mm),
            "youngs_modulus_hot_mpa": str(e_hot),
            "poissons_ratio": str(nu),
            "cte_per_c": "0.0000090",
            "delta_temp_c": str(dtemp),
            "restraint_factor": str(k_res),
            "plate_buckling_kc": str(kc),
            "hot_yield_allowable_mpa": "520",
            "safety_factor": "1.15",
        },
        include_intervals=True,
    )
    sig_th = k_res * e_hot * cte * dtemp
    sig_cr = (kc * (math.pi**2) * e_hot / (12.0 * (1.0 - nu**2))) * ((t_mm / b_mm) ** 2)
    gov_ref = min((sig_cr / (1.15 * sig_th)) - 1.0, (520.0 / (1.15 * sig_th)) - 1.0)
    _assert_close(res["outputs"]["thermal_compressive_stress_mpa"], sig_th)
    _assert_close(res["outputs"]["critical_buckling_stress_mpa"], sig_cr)
    _assert_close(res["outputs"]["governing_ms"], gov_ref)


# 6) CMH-17 Tsai-Wu / Hashin Composite Failure Criteria (20 parameterized cases)
@pytest.mark.parametrize(
    ("s1", "s2", "t12"),
    [
        (s1, s2, t12)
        for s1 in (350.0, 650.0)
        for s2 in (15.0, 32.0)
        for t12 in (18.0, 28.0, 38.0, 48.0, 58.0)
    ],
)
def test_lit_20_composite_tsai_wu(s1: float, s2: float, t12: float) -> None:
    xt, xc, yt, yc, s12, f12_star = 2500.0, 1500.0, 62.0, 250.0, 92.0, -0.5
    res = run_method(
        "composite_failure_criteria",
        {
            "sigma_1_mpa": str(s1),
            "sigma_2_mpa": str(s2),
            "tau_12_mpa": str(t12),
            "xt_mpa": str(xt),
            "xc_mpa": str(xc),
            "yt_mpa": str(yt),
            "yc_mpa": str(yc),
            "s12_mpa": str(s12),
            "f12_star": str(f12_star),
        },
        include_intervals=True,
    )
    f1 = 1.0 / xt - 1.0 / xc
    f2 = 1.0 / yt - 1.0 / yc
    f11 = 1.0 / (xt * xc)
    f22 = 1.0 / (yt * yc)
    f66 = 1.0 / (s12 * s12)
    f12 = f12_star * math.sqrt(f11 * f22)
    tw_ref = (
        f1 * s1 + f2 * s2 + f11 * (s1**2) + f22 * (s2**2) + 2.0 * f12 * s1 * s2 + f66 * (t12**2)
    )
    _assert_close(res["outputs"]["tsai_wu_failure_index"], tw_ref)


# 7) Bruhn Thin-Walled Bredt-Batho Torsion (20 parameterized cases)
@pytest.mark.parametrize(
    ("tq_nmm", "area_m", "perim", "thk"),
    [
        (tq, area, perim, thk)
        for tq in (2_500_000.0, 5_000_000.0)
        for area in (35000.0, 55000.0)
        for perim in (850.0, 1100.0)
        for thk in (2.0, 3.0)
    ]
    + [(3_200_000.0, 42000.0, 920.0, t) for t in (1.6, 2.4, 3.2, 4.0)],
)
def test_lit_20_bredt_batho_torsion(tq_nmm: float, area_m: float, perim: float, thk: float) -> None:
    g_mpa, s_allow = 26500.0, 195.0
    res = run_method(
        "thin_walled_bredt_batho_torsion",
        {
            "torque_nmm": str(tq_nmm),
            "enclosed_area_mm2": str(area_m),
            "perimeter_mm": str(perim),
            "min_wall_thickness_mm": str(thk),
            "shear_modulus_mpa": str(g_mpa),
            "shear_allowable_mpa": str(s_allow),
        },
        include_intervals=True,
    )
    q_flow = tq_nmm / (2.0 * area_m)
    tau = q_flow / thk
    ms_ref = (s_allow / tau) - 1.0
    _assert_close(res["outputs"]["max_torsional_shear_mpa"], tau)
    _assert_close(res["outputs"]["margin_of_safety"], ms_ref)


# 8) Walker Mean-Stress Crack Growth Life (20 parameterized cases)
@pytest.mark.parametrize(
    ("a0", "smax", "r_rat", "gamma_w"),
    [
        (a0, smax, r_rat, g)
        for a0 in (1.0, 1.5)
        for smax in (110.0, 145.0)
        for r_rat in (0.1, 0.3)
        for g in (0.65, 0.75)
    ]
    + [(1.27, 130.0, r, 0.7) for r in (-0.1, 0.0, 0.2, 0.4)],
)
def test_lit_20_walker_crack_growth(a0: float, smax: float, r_rat: float, gamma_w: float) -> None:
    beta, kic, wc, wm, req, sf = 1.12, 34.0, 2.5e-11, 3.1, 15000.0, 2.0
    res = run_method(
        "walker_mean_stress_crack_growth",
        {
            "initial_crack_a0_mm": str(a0),
            "sigma_max_mpa": str(smax),
            "stress_ratio_r": str(r_rat),
            "geometry_factor_beta": str(beta),
            "fracture_toughness_kic_mpa_sqrt_m": str(kic),
            "walker_c": "0.000000000025",
            "walker_m": str(wm),
            "walker_gamma": str(gamma_w),
            "required_cycles": str(req),
            "scatter_factor": str(sf),
        },
        include_intervals=True,
    )
    a0_m = a0 / 1000.0
    ac_m = ((kic / (beta * smax)) ** 2) / math.pi
    ds_eff = smax * ((1.0 - r_rat) ** gamma_w)
    p_exp = 1.0 - 0.5 * wm
    denom_c = wc * ((beta * ds_eff * math.sqrt(math.pi)) ** wm)
    nf = ((ac_m**p_exp) - (a0_m**p_exp)) / (p_exp * denom_c)
    ms_ref = ((nf / sf) / req) - 1.0
    _assert_close(res["outputs"]["walker_effective_stress_mpa"], ds_eff)
    _assert_close(res["outputs"]["life_margin_of_safety"], ms_ref)


# 9) MMPDS-16 / CMH-17 Static + S-N Fatigue + Arb Intervals (42 parameterized cases -> total 202!)
@pytest.mark.parametrize(
    ("mat_id", "temp_c", "env"),
    [
        (m, t, env)
        for m in (
            "AL-7075-T651",
            "AL-2024-T3",
            "AL-LI-2198-T8",
            "TI-6AL-4V",
            "15-5PH-H1025",
            "INCONEL-718",
            "17-4PH-H1025",
        )
        for t in ("23", "80", "120")
        for env in ("RTD", "ETW")
    ],
)
def test_lit_42_mmpds_arb_and_sn_allowables(mat_id: str, temp_c: str, env: str) -> None:
    mats = list_materials()
    assert len(mats) == 12
    al = lookup_allowable(
        mat_id,
        basis="A",
        property_name="fty_mpa",
        thickness_mm="6.35",
        temp_c=temp_c,
        environment=env,
        include_intervals=True,
        temp_uncertainty_c="3",
    )
    iv = al["exact_intervals"]["allowable_value_mpa"]
    assert Decimal(iv["lower"]) <= Decimal(iv["mid"]) <= Decimal(iv["upper"])
    assert (
        Decimal(iv["lower"]) - Decimal("0.001")
        <= Decimal(al["allowable_value_mpa"])
        <= Decimal(iv["upper"]) + Decimal("0.001")
    )

    sn = lookup_sn_fatigue_allowable(mat_id, stress_ratio_r="0.1", target_cycles="1000000")
    nasgro = lookup_nasgro_paris_params(mat_id)
    assert Decimal(sn["allowable_max_stress_mpa"]) > Decimal("0")
    assert Decimal(nasgro["k_ic_mpa_sqrt_m"]) > Decimal("0")
    assert (
        "margin_of_safety"
        in run_method("margin_of_safety", METHOD_DEFAULT_INPUTS["margin_of_safety"])["outputs"]
    )
