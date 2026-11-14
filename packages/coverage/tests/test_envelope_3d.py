from __future__ import annotations

from decimal import Decimal

from evidence_coverage.envelope_3d import build_vn_cg_envelope_3d
from evidence_coverage.grid import generate_cells


def test_build_vn_cg_envelope_3d_includes_135_cells_and_cad_overlay() -> None:
    expected_cells = len(generate_cells())
    res = build_vn_cg_envelope_3d(
        [],
        cad_cg_points=[
            {
                "point_id": "CAD-HUB-1",
                "x_cg_m": "0.045",
                "y_cg_m": "-0.012",
                "z_cg_m": "0.165",
                "mass_kg": "950.000",
            },
            {
                "point_id": "CAD-OUT-OF-BOX",
                "x_cg_m": "0.450",
                "y_cg_m": "0.000",
                "z_cg_m": "0.150",
                "mass_kg": "950.000",
            },
        ],
        mass_kg_override="950.000",
    )
    assert res["kind"] == "ASSUMPTION"
    slices = res["vn_envelope"]["mass_slices"]
    assert len(slices) == 5  # 4 default + 950.000 override
    mesh = res["vn_envelope"]["surface_mesh"]
    ring_lens = {len(sl["closed_loop"]) for sl in slices}
    assert len(ring_lens) == 1
    assert mesh["vertex_count"] == len(slices) * next(iter(ring_lens))
    assert mesh["triangle_count"] > 0
    for idx_tri in mesh["triangles"]:
        assert all(0 <= v < mesh["vertex_count"] for v in idx_tri)

    cloud = res["cg_cloud"]
    assert cloud["coverage_points"] == expected_cells
    assert cloud["cad_cae_points"] == 2
    assert cloud["total_points"] == expected_cells + 2
    cad_in = next(p for p in cloud["points"] if p["point_id"] == "CAD-HUB-1")
    cad_out = next(p for p in cloud["points"] if p["point_id"] == "CAD-OUT-OF-BOX")
    assert cad_in["within_cg_limits"] is True
    assert cad_out["within_cg_limits"] is False
    # Check Decimal-formatted string speeds are monotonic Va <= Vc <= Vd
    sp = slices[0]["characteristic_speeds_mps"]
    assert Decimal(sp["v_s1"]) < Decimal(sp["v_a"]) < Decimal(sp["v_d"])
    assert res["smt_proof"]["envelope_proved"] is True
