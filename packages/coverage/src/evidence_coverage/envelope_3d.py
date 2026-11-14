"""Deterministic 3D V-n flight envelope and CG cloud [X_cg, Y_cg, Z_cg] dataset builder."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
from evidence_coverage.grid import Cell, generate_cells
from evidence_coverage.status import gap_report, list_cells_with_status

Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
G0 = Decimal("9.807")


def _d(val: str | int | Decimal) -> Decimal:
    return val if isinstance(val, Decimal) else Decimal(str(val))


def _s3(val: Decimal) -> str:
    return format(val.quantize(Q3, rounding=ROUND_HALF_EVEN), "f")


def _s4(val: Decimal) -> str:
    return format(val.quantize(Q4, rounding=ROUND_HALF_EVEN), "f")


def _sqrt_dec(val: Decimal) -> Decimal:
    if val <= Decimal("0"):
        return Decimal("0")
    return val.sqrt()


def _stall_speed_mps(
    mass_kg: Decimal,
    rho_kg_m3: Decimal,
    wing_area_m2: Decimal,
    cl_max: Decimal,
) -> Decimal:
    weight_n = mass_kg * G0
    denom = Decimal("0.5") * rho_kg_m3 * wing_area_m2 * abs(cl_max)
    if denom <= Decimal("0"):
        return Decimal("0")
    return _sqrt_dec(weight_n / denom)


def _lateral_offset_from_unit(failed_unit: str) -> Decimal:
    mapping = {
        "none": Decimal("0.000"),
        "0": Decimal("-0.140"),
        "1": Decimal("-0.045"),
        "2": Decimal("0.045"),
        "3": Decimal("0.140"),
    }
    return mapping.get(failed_unit, Decimal("0.000"))


def _compute_vn_slice(
    mass_kg: Decimal,
    *,
    wing_area_m2: Decimal,
    rho_kg_m3: Decimal,
    cl_max_pos: Decimal,
    cl_max_neg: Decimal,
    nz_max: Decimal,
    nz_min: Decimal,
    v_c_mps: Decimal,
    v_d_mps: Decimal,
    gust_u_c_mps: Decimal,
    gust_u_d_mps: Decimal,
    cl_alpha: Decimal,
) -> dict[str, Any]:
    v_s_pos = _stall_speed_mps(mass_kg, rho_kg_m3, wing_area_m2, cl_max_pos)
    v_s_neg = _stall_speed_mps(mass_kg, rho_kg_m3, wing_area_m2, abs(cl_max_neg))
    v_a = v_s_pos * _sqrt_dec(nz_max)
    v_h_neg = v_s_neg * _sqrt_dec(abs(nz_min))

    upper_pts: list[dict[str, str]] = []
    # 0 -> Vs1 parabolic stall curve up to Va, then flat nz_max to Vd
    steps_stall = 8
    for i in range(steps_stall + 1):
        frac = Decimal(i) / Decimal(steps_stall)
        v = v_a * frac
        if v_s_pos > Decimal("0"):
            nz = min(nz_max, (v / v_s_pos) ** 2)
        else:
            nz = Decimal("0")
        upper_pts.append({"v_mps": _s3(v), "nz": _s3(nz), "mass_kg": _s3(mass_kg)})

    steps_cruise = 6
    for i in range(1, steps_cruise + 1):
        frac = Decimal(i) / Decimal(steps_cruise)
        v = v_a + (v_d_mps - v_a) * frac
        upper_pts.append({"v_mps": _s3(v), "nz": _s3(nz_max), "mass_kg": _s3(mass_kg)})

    lower_pts: list[dict[str, str]] = []
    for i in range(steps_stall + 1):
        frac = Decimal(i) / Decimal(steps_stall)
        v = v_h_neg * frac
        if v_s_neg > Decimal("0"):
            nz = -min(abs(nz_min), (v / v_s_neg) ** 2)
        else:
            nz = Decimal("0")
        lower_pts.append({"v_mps": _s3(v), "nz": _s3(nz), "mass_kg": _s3(mass_kg)})

    # Negative load factor tapers from nz_min at Vc up to 0 at Vd (CS-23 / CS-VTOL style)
    v_c_eff = v_c_mps if v_c_mps > v_h_neg else v_h_neg
    lower_pts.append({"v_mps": _s3(v_c_eff), "nz": _s3(nz_min), "mass_kg": _s3(mass_kg)})
    lower_pts.append({"v_mps": _s3(v_d_mps), "nz": "0.000", "mass_kg": _s3(mass_kg)})

    # Gust lines: delta_nz = (rho * V * cl_alpha * Kg * Ude) / (2 * W / S)
    wing_loading = (mass_kg * G0) / wing_area_m2
    gust_factor_c = (rho_kg_m3 * cl_alpha * Decimal("0.75") * gust_u_c_mps) / (
        Decimal("2") * wing_loading
    )
    gust_factor_d = (rho_kg_m3 * cl_alpha * Decimal("0.75") * gust_u_d_mps) / (
        Decimal("2") * wing_loading
    )
    nz_gust_c_pos = Decimal("1") + gust_factor_c * v_c_mps
    nz_gust_c_neg = Decimal("1") - gust_factor_c * v_c_mps
    nz_gust_d_pos = Decimal("1") + gust_factor_d * v_d_mps
    nz_gust_d_neg = Decimal("1") - gust_factor_d * v_d_mps

    gust_upper = [
        {"v_mps": "0.000", "nz": "1.000", "mass_kg": _s3(mass_kg)},
        {"v_mps": _s3(v_c_mps), "nz": _s3(nz_gust_c_pos), "mass_kg": _s3(mass_kg)},
        {"v_mps": _s3(v_d_mps), "nz": _s3(nz_gust_d_pos), "mass_kg": _s3(mass_kg)},
    ]
    gust_lower = [
        {"v_mps": "0.000", "nz": "1.000", "mass_kg": _s3(mass_kg)},
        {"v_mps": _s3(v_c_mps), "nz": _s3(nz_gust_c_neg), "mass_kg": _s3(mass_kg)},
        {"v_mps": _s3(v_d_mps), "nz": _s3(nz_gust_d_neg), "mass_kg": _s3(mass_kg)},
    ]

    return {
        "mass_kg": _s3(mass_kg),
        "characteristic_speeds_mps": {
            "v_s1": _s3(v_s_pos),
            "v_s_neg": _s3(v_s_neg),
            "v_a": _s3(v_a),
            "v_c": _s3(v_c_mps),
            "v_d": _s3(v_d_mps),
        },
        "maneuver_upper": upper_pts,
        "maneuver_lower": lower_pts,
        "gust_upper": gust_upper,
        "gust_lower": gust_lower,
        "closed_loop": upper_pts + list(reversed(lower_pts)),
    }


def _build_surface_mesh(
    slices: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build triangulated upper/lower 3D V-n manifold vertices & triangle indices."""
    vertices: list[dict[str, str]] = []
    triangles: list[list[int]] = []
    n_slices = len(slices)
    if n_slices == 0:
        return {"vertices": [], "triangles": []}

    # Use uniform closed_loop resampling length (upper_len = 15, lower_len = 11)
    # Build upper + lower continuous rings per mass slice
    ring_len = len(slices[0]["closed_loop"])
    for sl in slices:
        for pt in sl["closed_loop"]:
            vertices.append(
                {
                    "v_mps": pt["v_mps"],
                    "nz": pt["nz"],
                    "mass_kg": pt["mass_kg"],
                }
            )

    for s_idx in range(n_slices - 1):
        base_a = s_idx * ring_len
        base_b = (s_idx + 1) * ring_len
        for i in range(ring_len - 1):
            a0 = base_a + i
            a1 = base_a + i + 1
            b0 = base_b + i
            b1 = base_b + i + 1
            triangles.append([a0, b0, b1])
            triangles.append([a0, b1, a1])

    return {
        "vertices": vertices,
        "triangles": triangles,
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
    }


def build_vn_cg_envelope_3d(
    events: list[dict[str, Any]] | None = None,
    *,
    cells: list[Cell] | None = None,
    cad_cg_points: list[dict[str, Any]] | None = None,
    mass_kg_override: str | None = None,
    wing_area_m2: str = "12.000",
    v_c_mps: str = "65.000",
    v_d_mps: str = "82.000",
    nz_max: str = "2.500",
    nz_min: str = "-1.000",
    cg_limits_m: dict[str, str] | None = None,
    fem_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic 3D V-n flight envelope and [X_cg, Y_cg, Z_cg] CG cloud.

    Physical parameters default to synthetic reference eVTOL assumptions tagged ASSUMPTION.
    All numeric physical quantities are Decimal-serialized strings.
    """
    ev_list = list(events or [])
    chosen_cells = cells or generate_cells()
    cell_rows = list_cells_with_status(ev_list, cells=chosen_cells)
    summary = gap_report(ev_list, chosen_cells)

    area = _d(wing_area_m2)
    rho = Decimal("1.225")
    cl_max_pos = Decimal("1.550")
    cl_max_neg = Decimal("-0.850")
    nz_hi = _d(nz_max)
    nz_lo = _d(nz_min)
    vc = _d(v_c_mps)
    vd = _d(v_d_mps)
    u_c = Decimal("15.240")
    u_d = Decimal("7.620")
    cl_alpha = Decimal("4.800")

    mass_stations = [
        Decimal("800.000"),
        Decimal("900.000"),
        Decimal("1050.000"),
        Decimal("1200.000"),
    ]
    if mass_kg_override is not None:
        m_ov = _d(mass_kg_override)
        if m_ov > Decimal("0") and all(abs(m_ov - ms) > Decimal("1.000") for ms in mass_stations):
            mass_stations.append(m_ov)
            mass_stations.sort()

    vn_slices = [
        _compute_vn_slice(
            ms,
            wing_area_m2=area,
            rho_kg_m3=rho,
            cl_max_pos=cl_max_pos,
            cl_max_neg=cl_max_neg,
            nz_max=nz_hi,
            nz_min=nz_lo,
            v_c_mps=vc,
            v_d_mps=vd,
            gust_u_c_mps=u_c,
            gust_u_d_mps=u_d,
            cl_alpha=cl_alpha,
        )
        for ms in mass_stations
    ]
    vn_mesh = _build_surface_mesh(vn_slices)

    limits = cg_limits_m or {
        "x_min_m": "-0.200",
        "x_max_m": "0.200",
        "y_min_m": "-0.180",
        "y_max_m": "0.180",
        "z_min_m": "0.050",
        "z_max_m": "0.300",
    }

    x_min = _d(limits["x_min_m"])
    x_max = _d(limits["x_max_m"])
    y_min = _d(limits["y_min_m"])
    y_max = _d(limits["y_max_m"])
    z_min = _d(limits["z_min_m"])
    z_max = _d(limits["z_max_m"])

    cg_cloud: list[dict[str, Any]] = []
    for row in cell_rows:
        axes = row["axes"]
        m_val = _d(axes["mass_kg"])
        xcg = _d(axes["cg_x_m"])
        ycg = _lateral_offset_from_unit(axes["failed_unit"])
        # Nominal Z_cg shifts slightly with payload loading and load factor
        nz_val = _d(axes["load_factor"])
        zcg = (
            Decimal("0.150")
            + (m_val - Decimal("900.000")) * Decimal("0.00025")
            + (nz_val - Decimal("1.000")) * Decimal("0.008")
        )
        in_box = x_min <= xcg <= x_max and y_min <= ycg <= y_max and z_min <= zcg <= z_max
        cg_cloud.append(
            {
                "point_id": row["cell_id"],
                "source": "coverage_cell",
                "x_cg_m": _s4(xcg),
                "y_cg_m": _s4(ycg),
                "z_cg_m": _s4(zcg),
                "mass_kg": axes["mass_kg"],
                "load_factor": axes["load_factor"],
                "failed_unit": axes["failed_unit"],
                "status": row["status"],
                "stale": bool(row["stale"]),
                "within_cg_limits": in_box,
                "evidence_event_hash": row["evidence_event_hash"],
            }
        )

    cad_points_added = 0
    for idx, cpt in enumerate(cad_cg_points or []):
        xcg = _d(cpt.get("x_cg_m", cpt.get("x_m", "0")))
        ycg = _d(cpt.get("y_cg_m", cpt.get("y_m", "0")))
        zcg = _d(cpt.get("z_cg_m", cpt.get("z_m", "0")))
        in_box = x_min <= xcg <= x_max and y_min <= ycg <= y_max and z_min <= zcg <= z_max
        cad_points_added += 1
        cg_cloud.append(
            {
                "point_id": str(cpt.get("point_id", f"CAD-CG-{idx + 1}")),
                "source": str(cpt.get("source", "cad_cae")),
                "x_cg_m": _s4(xcg),
                "y_cg_m": _s4(ycg),
                "z_cg_m": _s4(zcg),
                "mass_kg": str(cpt.get("mass_kg", mass_kg_override or "900.000")),
                "load_factor": str(cpt.get("load_factor", "1.000")),
                "failed_unit": str(cpt.get("failed_unit", "none")),
                "status": "cad_reference",
                "stale": False,
                "within_cg_limits": in_box,
                "evidence_event_hash": "",
                "label": str(cpt.get("label", cpt.get("name", f"CAD CG #{idx + 1}"))),
            }
        )

    smt_proof = prove_continuous_flight_envelope(
        mass_range_kg=(_s3(min(mass_stations)), _s3(max(mass_stations))),
        cg_range_m=(limits["x_min_m"], limits["x_max_m"]),
        load_factor_range=(_s3(nz_lo), _s3(nz_hi)),
    )

    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "kind": "ASSUMPTION",
        "axes_meta": {
            "vn_3d": {
                "x": "airspeed_mps (m/s)",
                "y": "load_factor (nz)",
                "z": "mass_kg (kg)",
            },
            "cg_3d": {
                "x": "X_cg (m, longitudinal)",
                "y": "Y_cg (m, lateral)",
                "z": "Z_cg (m, vertical)",
            },
        },
        "aerodynamic_reference": {
            "wing_area_m2": _s3(area),
            "air_density_kg_m3": _s3(rho),
            "cl_max_pos": _s3(cl_max_pos),
            "cl_max_neg": _s3(cl_max_neg),
            "nz_max": _s3(nz_hi),
            "nz_min": _s3(nz_lo),
            "v_c_mps": _s3(vc),
            "v_d_mps": _s3(vd),
        },
        "vn_envelope": {
            "mass_slices": vn_slices,
            "surface_mesh": vn_mesh,
        },
        "cg_cloud": {
            "total_points": len(cg_cloud),
            "coverage_points": len(cell_rows),
            "cad_cae_points": cad_points_added,
            "limits_box_m": limits,
            "points": cg_cloud,
        },
        "coverage_summary": summary,
        "smt_proof": smt_proof,
    }
    if fem_overlay is not None:
        result["fem_overlay"] = fem_overlay
    return result
