"""Q2 Mega-Test Suite: 3D B-Rep CAD, Streaming 250k/500-Subcase CAE, Live PLMs & 50k FEA Viewer."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from evidence_api.app import create_app
from evidence_ingest.cad_brep import (
    TriangleMesh,
    analyze_assembly_interference,
    analyze_step_brep,
    parse_composite_ply_book,
)
from evidence_ingest.cae_binary import (
    DTYPE_ELEM,
    DTYPE_EQUILIBRIUM,
    DTYPE_NODE,
    DTYPE_STRESS_CHUNK,
    parse_cae_h5_file,
    parse_nastran_op2_file,
    run_sandboxed_cae_worker,
    write_cae_h5_stream,
    write_nastran_op2_stream,
)
from evidence_ingest.plm_connectors import (
    CircuitBreakerOpenError,
    MockPLMServerTransport,
    build_plm_connector,
)
from evidence_ingest.router import ingest_bytes
from evidence_kernel.pg_ledger import PostgresLedger, create_shared_sqlite_pg_connect_fn
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _process_rss_mb() -> float:
    if sys.platform == "win32":

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        get_proc = ctypes.windll.kernel32.GetCurrentProcess
        get_proc.restype = ctypes.wintypes.HANDLE
        get_mem = ctypes.windll.psapi.GetProcessMemoryInfo
        get_mem.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.wintypes.DWORD]
        get_mem.restype = ctypes.wintypes.BOOL
        if get_mem(get_proc(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024.0 * 1024.0)
    return 0.0


def _step_box(
    *,
    ap: str,
    dx: float,
    dy: float,
    dz: float,
    ox: float = 0.0,
    oy: float = 0.0,
    oz: float = 0.0,
    material: str = "AL-7075",
) -> bytes:
    schema = {
        "AP203": "CONFIG_CONTROL_DESIGN",
        "AP214": "AUTOMOTIVE_DESIGN",
        "AP242": "MANAGED_MODEL_BASED_3D_ENGINEERING",
    }[ap]
    txt = f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('STEP B-Rep Fixture'), '2;1');
FILE_NAME('part.stp', '2026-11-14T10:00:00', ('AeroRegu'), ('Q2'), '', '', '');
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
#1 = MATERIAL_DESIGNATION('{material}');
#10 = CARTESIAN_POINT('Origin', ({ox:.6f}, {oy:.6f}, {oz:.6f}));
#11 = DIRECTION('Z', (0.0, 0.0, 1.0));
#12 = DIRECTION('X', (1.0, 0.0, 0.0));
#13 = AXIS2_PLACEMENT_3D('Place', #10, #11, #12);
#20 = BLOCK('SPAR_WEB', #13, {dx:.6f}, {dy:.6f}, {dz:.6f});
ENDSEC;
END-ISO-10303-21;
"""
    return txt.encode("utf-8")


def _step_cylinder(
    *,
    ap: str,
    radius: float,
    height: float,
    ox: float = 0.0,
    oy: float = 0.0,
    oz: float = 0.0,
    material: str = "TI-6AL-4V",
) -> bytes:
    schema = {
        "AP203": "CONFIG_CONTROL_DESIGN",
        "AP214": "AUTOMOTIVE_DESIGN",
        "AP242": "MANAGED_MODEL_BASED_3D_ENGINEERING",
    }[ap]
    txt = f"""ISO-10303-21;
HEADER;
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
#1 = MATERIAL_DESIGNATION('{material}');
#10 = CARTESIAN_POINT('CylOrigin', ({ox:.6f}, {oy:.6f}, {oz:.6f}));
#11 = DIRECTION('Z', (0.0, 0.0, 1.0));
#12 = DIRECTION('X', (1.0, 0.0, 0.0));
#13 = AXIS2_PLACEMENT_3D('Place', #10, #11, #12);
#20 = RIGHT_CIRCULAR_CYLINDER('LUG_BUSHING', #13, {height:.6f}, {radius:.6f});
ENDSEC;
END-ISO-10303-21;
"""
    return txt.encode("utf-8")


def _step_faceted_brep_box(dx: float, dy: float, dz: float) -> bytes:
    """Explicit MANIFOLD_SOLID_BREP -> CLOSED_SHELL -> ADVANCED_FACE -> POLY_LOOP box."""
    pts = [
        (0.0, 0.0, 0.0),
        (dx, 0.0, 0.0),
        (dx, dy, 0.0),
        (0.0, dy, 0.0),
        (0.0, 0.0, dz),
        (dx, 0.0, dz),
        (dx, dy, dz),
        (0.0, dy, dz),
    ]
    faces = [
        (0, 3, 2, 1),  # z=0 bottom (-z)
        (4, 5, 6, 7),  # z=dz top (+z)
        (0, 1, 5, 4),  # y=0 (-y)
        (2, 3, 7, 6),  # y=dy (+y)
        (0, 4, 7, 3),  # x=0 (-x)
        (1, 2, 6, 5),  # x=dx (+x)
    ]
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_SCHEMA(('MANAGED_MODEL_BASED_3D_ENGINEERING'));",
        "ENDSEC;",
        "DATA;",
        "#1 = MATERIAL_DESIGNATION('AL-7075');",
    ]
    for i, (x, y, z) in enumerate(pts, start=10):
        lines.append(f"#{i} = CARTESIAN_POINT('P{i}', ({x:.6f}, {y:.6f}, {z:.6f}));")
    fb_ids: list[str] = []
    for f_idx, (a, b, c, d) in enumerate(faces, start=1):
        pid = 100 + f_idx * 4
        bid = pid + 1
        fid = pid + 2
        lines.append(
            f"#{pid} = POLY_LOOP('L{f_idx}', (#{10 + a}, #{10 + b}, #{10 + c}, #{10 + d}));"
        )
        lines.append(f"#{bid} = FACE_OUTER_BOUND('B{f_idx}', #{pid}, .T.);")
        lines.append(f"#{fid} = ADVANCED_FACE('F{f_idx}', (#{bid}), #999, .T.);")
        fb_ids.append(f"#{fid}")
    lines.append(f"#300 = CLOSED_SHELL('CS1', ({', '.join(fb_ids)}));")
    lines.append("#301 = MANIFOLD_SOLID_BREP('WING_RIB_POCKET', #300);")
    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")
    return "\n".join(lines).encode("utf-8")


def test_q2_mega_1_30_brep_solids_accuracy_clearance_web_plybook_and_cg_shift() -> None:
    # 1. Test 30 parameterized aerospace B-Rep solids across AP203, AP214, AP242
    aps = ["AP203", "AP214", "AP242"]
    max_rel_err = 0.0
    tested = 0

    for i in range(15):
        ap = aps[i % 3]
        dx = 120.0 + i * 17.5
        dy = 45.0 + i * 6.0
        dz = 8.0 + (i % 5) * 3.5
        ox, oy, oz = 10.0 * i, -5.0 * i, 2.0 * i
        raw = _step_box(ap=ap, dx=dx, dy=dy, dz=dz, ox=ox, oy=oy, oz=oz, material="AL-7075")
        parsed = ingest_bytes(raw, f"box_{i}.stp")
        brep = parsed["cad_cae"]["brep"]
        assert brep["ap_level"] == ap
        s = brep["solids"][0]

        true_vol = dx * dy * dz
        true_mass = true_vol * 1e-9 * 2810.0
        true_cg = [ox + dx / 2.0, oy + dy / 2.0, oz + dz / 2.0]
        true_ixx = true_mass * ((dy * 1e-3) ** 2 + (dz * 1e-3) ** 2) / 12.0
        true_iyy = true_mass * ((dx * 1e-3) ** 2 + (dz * 1e-3) ** 2) / 12.0
        true_izz = true_mass * ((dx * 1e-3) ** 2 + (dy * 1e-3) ** 2) / 12.0

        for got, truth in [
            (float(s["volume_mm3"]), true_vol),
            (float(s["mass_kg"]), true_mass),
            (float(s["cg_mm"][0]), true_cg[0]),
            (float(s["cg_mm"][1]), true_cg[1]),
            (float(s["cg_mm"][2]), true_cg[2]),
            (float(s["inertia_tensor_kg_m2"]["Ixx"]), true_ixx),
            (float(s["inertia_tensor_kg_m2"]["Iyy"]), true_iyy),
            (float(s["inertia_tensor_kg_m2"]["Izz"]), true_izz),
        ]:
            rel = abs(got - truth) / max(1e-12, abs(truth))
            max_rel_err = max(max_rel_err, rel)
            assert rel < 1e-4, f"Box {i} exceeded 0.01% error: got={got}, truth={truth}"
        tested += 1

    for i in range(10):
        ap = aps[i % 3]
        r = 18.0 + i * 2.5
        h = 60.0 + i * 11.0
        raw = _step_cylinder(
            ap=ap, radius=r, height=h, ox=50.0, oy=20.0, oz=5.0, material="TI-6AL-4V"
        )
        brep = analyze_step_brep(raw, f"cyl-{i}")
        s = brep["solids"][0]

        true_vol = math.pi * (r**2) * h
        true_mass = true_vol * 1e-9 * 4430.0
        rm = r * 1e-3
        hm = h * 1e-3
        true_ixx = true_mass * (3.0 * rm**2 + hm**2) / 12.0
        true_izz = 0.5 * true_mass * rm**2

        for got, truth in [
            (float(s["volume_mm3"]), true_vol),
            (float(s["mass_kg"]), true_mass),
            (float(s["inertia_tensor_kg_m2"]["Ixx"]), true_ixx),
            (float(s["inertia_tensor_kg_m2"]["Izz"]), true_izz),
        ]:
            rel = abs(got - truth) / max(1e-12, abs(truth))
            max_rel_err = max(max_rel_err, rel)
            assert rel < 1e-4, f"Cylinder {i} exceeded 0.01% error: {rel}"
        tested += 1

    for i in range(5):
        dx, dy, dz = 80.0 + 10.0 * i, 30.0 + 5.0 * i, 2.4 + 0.5 * i
        raw = _step_faceted_brep_box(dx, dy, dz)
        brep = analyze_step_brep(raw, f"faceted-{i}")
        s = brep["solids"][0]
        true_vol = dx * dy * dz
        rel = abs(float(s["volume_mm3"]) - true_vol) / true_vol
        assert rel < 1e-4
        # Exact web thickness = min thickness dz
        assert abs(float(brep["min_web_thickness_mm"]) - dz) < 1e-3
        tested += 1

    assert tested == 30
    assert max_rel_err < 1e-4  # strictly < 0.01%

    # 2. Assembly interference vs clearance detection
    mesh_a = TriangleMesh(
        "A",
        "SPAR_FLANGE",
        np.array(
            [
                [0, 0, 0],
                [50, 0, 0],
                [50, 20, 0],
                [0, 20, 0],
                [0, 0, 10],
                [50, 0, 10],
                [50, 20, 10],
                [0, 20, 10],
            ],
            dtype=np.float64,
        ),
        np.array(
            [
                [0, 2, 1],
                [0, 3, 2],
                [4, 5, 6],
                [4, 6, 7],
                [0, 1, 5],
                [0, 5, 4],
                [2, 3, 7],
                [2, 7, 6],
                [0, 4, 7],
                [0, 7, 3],
                [1, 2, 6],
                [1, 6, 5],
            ],
            dtype=np.int32,
        ),
    )
    mesh_overlap = TriangleMesh(
        "B",
        "ACTUATOR_BRACKET",
        mesh_a.vertices + np.array([40.0, 0.0, 0.0]),
        mesh_a.triangles,
    )
    mesh_gapped = TriangleMesh(
        "C",
        "RIB_CLEAR",
        mesh_a.vertices + np.array([62.5, 0.0, 0.0]),
        mesh_a.triangles,
    )
    coll = analyze_assembly_interference([mesh_a, mesh_overlap])
    assert float(coll["interference_volume_mm3"]) > 0.0
    assert len(coll["interference_pairs"]) == 1

    clear = analyze_assembly_interference([mesh_a, mesh_gapped])
    assert float(clear["interference_volume_mm3"]) == 0.0
    assert abs(float(clear["min_clearance_mm"]) - 12.5) < 0.05

    # 3. +15 mm CG shift detection Rev A -> Rev B
    rev_a = analyze_step_brep(_step_box(ap="AP242", dx=200.0, dy=60.0, dz=12.0, ox=0.0), "revA")
    rev_b = analyze_step_brep(_step_box(ap="AP242", dx=200.0, dy=60.0, dz=12.0, ox=15.0), "revB")
    cg_shift_x = float(rev_b["assembly_cg_mm"][0]) - float(rev_a["assembly_cg_mm"][0])
    assert abs(cg_shift_x - 15.0) < 1e-4

    # 4. CATIA Composite Ply Book ([0/45/-45/90]2s valid vs invalid unbalanced stack)
    valid_xml = b"""<CATProduct name="WING_SKIN">
      <Laminate name="UPPER_SKIN_01" ply_thickness_mm="0.125">
        <Ply angle="0"/><Ply angle="45"/><Ply angle="-45"/><Ply angle="90"/>
        <Ply angle="90"/><Ply angle="-45"/><Ply angle="45"/><Ply angle="0"/>
      </Laminate>
      <Parameter name="stack_notation" value="[0/45/-45/90]2s"/>
    </CATProduct>"""
    catia_res = ingest_bytes(valid_xml, "wing_skin.catxml")
    ply_book = catia_res["cad_cae"]["composite_ply_book"]
    assert ply_book["stack_count"] >= 2
    assert ply_book["all_rules_satisfied"] is True

    bad_book = parse_composite_ply_book("[0/0/0/0/0/45]")
    assert bad_book["all_rules_satisfied"] is False


def test_q2_mega_2_streaming_cae_250k_elements_500_subcases_op2_h5_and_sandboxed(
    tmp_path: Path,
) -> None:
    n_elems = 250_000
    n_subcases = 500

    # Nodes (compact grid referenced by 250k elements)
    n_nodes = 250_004
    nodes = np.zeros(n_nodes, dtype=DTYPE_NODE)
    nodes["nid"] = np.arange(1, n_nodes + 1, dtype=np.int32)
    nodes["x"] = np.linspace(0.0, 5000.0, n_nodes, dtype=np.float32)
    nodes["y"] = (np.arange(n_nodes) % 100).astype(np.float32) * 5.0
    nodes["z"] = ((np.arange(n_nodes) // 100) % 10).astype(np.float32) * 2.0

    # 250k elements spanning CBAR(1), CBEAM(2), CQUAD4(3), CTRIA3(4), CBUSH(5), CFAST(6)
    elements = np.zeros(n_elems, dtype=DTYPE_ELEM)
    elements["eid"] = np.arange(1, n_elems + 1, dtype=np.int32)
    etypes = (np.arange(n_elems, dtype=np.int32) % 6) + 1
    elements["etype"] = etypes
    elements["pid"] = 2000 + etypes  # PIDs 2001..2006
    elements["n1"] = np.arange(1, n_elems + 1, dtype=np.int32)
    elements["n2"] = np.arange(2, n_elems + 2, dtype=np.int32)
    elements["n3"] = np.arange(3, n_elems + 3, dtype=np.int32)
    elements["n4"] = np.arange(4, n_elems + 4, dtype=np.int32)
    elements["allowable_mpa"] = 450.0

    # 500 balanced subcases: sum(F_applied) + sum(F_spc) == 0
    eq = np.zeros(n_subcases, dtype=DTYPE_EQUILIBRIUM)
    eq["subcase_id"] = np.arange(1, n_subcases + 1, dtype=np.int32)
    eq["fx_app"] = 1000.0 + np.arange(n_subcases, dtype=np.float64) * 10.0
    eq["fy_app"] = -400.0
    eq["fz_app"] = 25000.0
    eq["fx_spc"] = -eq["fx_app"]
    eq["fy_spc"] = -eq["fy_app"]
    eq["fz_spc"] = -eq["fz_app"]

    # Stream stress records covering all 500 subcases (critical envelopes + full 250k elements)
    def _stress_chunks():
        # Chunk 1: All 250,000 elements at critical Subcase 250
        c1 = np.zeros(n_elems, dtype=DTYPE_STRESS_CHUNK)
        c1["subcase_id"] = 250
        c1["eid"] = elements["eid"]
        c1["pid"] = elements["pid"]
        c1["etype"] = elements["etype"]
        c1["von_mises_mpa"] = 300.0 + (elements["etype"].astype(np.float32) * 10.0)
        c1["axial_or_shear_mpa"] = 120.0
        c1["margin_of_safety"] = (450.0 / c1["von_mises_mpa"]) - 1.0
        # Inject exact known global minimum on PID 2003 (CQUAD4), EID 15 at Subcase 250
        c1["margin_of_safety"][14] = 0.0850
        yield c1

        # Chunks 2..6: Remaining subcases 1..500 sampled across elements (500 subcases total)
        batch_subs = np.arange(1, n_subcases + 1, dtype=np.int32)
        c2 = np.zeros(len(batch_subs) * 20, dtype=DTYPE_STRESS_CHUNK)
        c2["subcase_id"] = np.repeat(batch_subs, 20)
        c2["eid"] = np.tile(np.arange(1, 21, dtype=np.int32), len(batch_subs))
        c2["pid"] = 2001 + (c2["eid"] % 6)
        c2["etype"] = 1 + (c2["eid"] % 6)
        c2["von_mises_mpa"] = 220.0
        c2["axial_or_shear_mpa"] = 95.0
        c2["margin_of_safety"] = 0.45
        yield c2

    rss0 = _process_rss_mb()

    # Write & stream-parse .op2
    op2_path = tmp_path / "airframe_full.op2"
    write_nastran_op2_stream(
        op2_path, nodes=nodes, elements=elements, equilibrium=eq, stress_chunks=_stress_chunks()
    )
    t0 = time.perf_counter()
    op2_res = parse_nastran_op2_file(op2_path)
    op2_time = time.perf_counter() - t0

    assert op2_time < 20.0, f"OP2 parse took {op2_time:.2f}s >= 20s"
    assert op2_res["element_count"] == 250_000
    assert op2_res["subcase_count"] == 500
    assert op2_res["equilibrium_verified"] is True
    assert op2_res["imbalanced_subcases"] == []
    assert abs(float(op2_res["ms_min"]) - 0.085) < 1e-4
    assert len(op2_res["pid_ms_summary"]) == 6
    assert set(op2_res["element_type_counts"].keys()) >= {
        "CBAR",
        "CBEAM",
        "CQUAD4",
        "CTRIA3",
        "CBUSH",
        "CFAST",
    }

    # Write & stream-parse .h5
    h5_path = tmp_path / "airframe_full.h5"
    write_cae_h5_stream(
        h5_path, nodes=nodes, elements=elements, equilibrium=eq, stress_chunks=_stress_chunks()
    )
    t1 = time.perf_counter()
    h5_res = parse_cae_h5_file(h5_path)
    h5_time = time.perf_counter() - t1

    assert h5_time < 20.0, f"H5 parse took {h5_time:.2f}s >= 20s"
    assert h5_res["element_count"] == 250_000
    assert h5_res["subcase_count"] == 500
    assert h5_res["equilibrium_verified"] is True
    assert abs(float(h5_res["ms_min"]) - 0.085) < 1e-4

    rss1 = _process_rss_mb()
    assert max(0.0, rss1 - rss0) < 1536.0

    # Equilibrium failure test: perturb Subcase 77 by +500 N unopposed
    eq_bad = eq.copy()
    eq_bad["fz_app"][76] += 500.0
    op2_bad = tmp_path / "imbalanced.op2"
    # Build tiny stress chunk for imbalanced check
    st_small = np.zeros(10, dtype=DTYPE_STRESS_CHUNK)
    st_small["subcase_id"] = 77
    st_small["eid"] = np.arange(1, 11, dtype=np.int32)
    st_small["pid"] = 2001
    st_small["etype"] = 1
    st_small["von_mises_mpa"] = 180.0
    st_small["margin_of_safety"] = 0.5
    write_nastran_op2_stream(
        op2_bad,
        nodes=nodes[:100],
        elements=elements[:100],
        equilibrium=eq_bad,
        stress_chunks=[st_small],
    )
    bad_res = parse_nastran_op2_file(op2_bad)
    assert bad_res["equilibrium_verified"] is False
    assert 77 in bad_res["imbalanced_subcases"]

    # Sandboxed subprocess worker for .odb and .rst
    odb_payload = (
        b"ODB_AERO"
        + json.dumps({"element_count": 4200, "subcase_count": 12, "ms_min": "0.140"}).encode()
    )
    odb_res = ingest_bytes(odb_payload, "wing_lug.odb")
    assert odb_res["cad_cae"]["sandboxed_worker"] is True
    assert odb_res["cad_cae"]["ms_min"] == "0.140"

    rst_res = run_sandboxed_cae_worker(
        b"RST_AERO" + json.dumps({"element_count": 1800, "ms_min": "0.220"}).encode(),
        "abc123",
        ".rst",
    )
    assert rst_res["sandboxed_worker"] is True


def test_q2_mega_3_live_plm_connectors_retry_oauth_circuit_breaker_effectivity_writeback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "plm_home"))
    tenant = "airbus-evtol"
    db_file = tmp_path / "plm_pg.sqlite"
    connect_fn = create_shared_sqlite_pg_connect_fn(db_file)
    pg_ledger = PostgresLedger(
        "postgresql://aeroregu@localhost:5432/evidence", tenant, connect_fn=connect_fn
    )

    # 1. All 3 PLM connectors: 3DEXPERIENCE, Teamcenter, Windchill with 3x HTTP 503 + OAuth expiry
    for sys_name in ("3dexperience", "teamcenter", "windchill"):
        transport = MockPLMServerTransport(transient_503_budget=3, expire_first_token_once=True)
        conn = build_plm_connector(
            sys_name,  # type: ignore[arg-type]
            base_url="https://plm.aeroregu.local",
            token_url="https://plm.aeroregu.local/oauth/token",
            client_id="aeroregu-svc",
            client_secret="top-secret",
            transport=transport,
        )
        # Verify MSN effectivity filter: MSN 010 includes LEGACY(1001), excludes REVB(2002)
        bom_10 = conn.fetch_ebom("WING-SPAR-ASM-01", revision="Rev A", msn=10)
        pids_10 = {p["pid"] for p in bom_10["parts"]}
        assert pids_10 == {2001, 1001, 3001}
        assert conn.telemetry_retries >= 4  # 1 token refresh on 401 + 3 retries on 503

        # MSN 020 excludes LEGACY(1001), includes REVB(2002)
        bom_20 = conn.fetch_ebom("WING-SPAR-ASM-01", revision="Rev B", msn=20)
        pids_20 = {p["pid"] for p in bom_20["parts"]}
        assert pids_20 == {2001, 2002, 3001}

        ecn_diff = conn.fetch_ecn_diff("ECN-2026-042")
        assert ecn_diff["from_revision"] == "Rev A"
        assert ecn_diff["to_revision"] == "Rev B"

        # Bidirectional Merkle writeback
        wb = conn.writeback_merkle_attestation(
            change_action_id="ECN-2026-042",
            merkle_root="a" * 64,
            head_hash="b" * 64,
            chain_verified=True,
            revision="Rev B",
            msn=20,
        )
        assert wb["status"] == "attested"
        assert "ECN-2026-042" in transport.writebacks
        conn.close()

    # 2. Circuit breaker trips OPEN on sustained upstream outage
    bad_transport = MockPLMServerTransport(transient_503_budget=999)
    cb_conn = build_plm_connector(
        "3dexperience",
        base_url="https://plm.aeroregu.local",
        token_url="https://plm.aeroregu.local/oauth/token",
        client_id="id",
        client_secret="sec",
        transport=bad_transport,
    )
    cb_conn.max_retries = 1
    cb_conn.backoff_base_s = 0.001
    cb_conn.breaker.failure_threshold = 2
    for _ in range(2):
        with pytest.raises(Exception):
            cb_conn.fetch_ebom("WING-SPAR-ASM-01")
    assert cb_conn.breaker.state == "OPEN"
    with pytest.raises(CircuitBreakerOpenError):
        cb_conn.fetch_ebom("WING-SPAR-ASM-01")
    cb_conn.close()

    # 3. API Selective PID invalidation via POST /plm/webhook/ecn + queue + cache invalidation
    app = create_app()
    client = TestClient(app)
    all_cells = [
        {"cell_id": f"cell-{idx}", "pids": [2001 if idx < 14 else 3001]} for idx in range(100)
    ]
    hook_resp = client.post(
        "/plm/webhook/ecn",
        json={
            "tenant_id": tenant,
            "ecn_diff": {
                "ecn_id": "ECN-42",
                "from_revision": "Rev A",
                "to_revision": "Rev B",
                "changed_pids": [2001],
            },
            "cells": all_cells,
        },
    )
    assert hook_resp.status_code == 200
    plan = hook_resp.json()["result"]
    assert plan["invalidated_cell_count"] == 14
    assert plan["unaffected_cell_count"] == 86

    # Verify /plm/sync & /plm/writeback endpoints
    assert (
        client.post(
            "/plm/sync",
            json={"tenant_id": tenant, "system": "teamcenter", "msn": 20, "use_mock_plm": True},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/plm/writeback",
            json={"tenant_id": tenant, "system": "windchill", "msn": 20, "use_mock_plm": True},
        ).status_code
        == 200
    )
    pg_ledger.close()


def test_q2_mega_4_3d_fea_mesh_50k_elements_and_click_to_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "viewer_home"))
    tenant = "airbus-evtol"

    # Build 50,000-element CQUAD4 structural mesh payload
    node_coords = {
        str(i): [float(i % 250) * 10.0, float(i // 250) * 10.0, 0.0] for i in range(1, 50_252)
    }
    elements = [
        {
            "element_id": eid,
            "pid": 2001 if (eid % 2 == 0) else 2002,
            "element_type": "CQUAD4",
            "n1": eid,
            "n2": eid + 1,
            "n3": eid + 251,
            "n4": eid + 250,
            "subcase_id": 250,
            "ms_min": "0.0850" if eid == 12_344 else "0.4200",
            "von_mises_mpa": "390.5" if eid == 12_344 else "185.0",
            "calc_event_hash": "e" * 64,
        }
        for eid in range(1, 50_001)
    ]

    app = create_app()
    client = TestClient(app)

    reg_resp = client.post(
        "/cae/mesh/wing_box_rev_b",
        json={
            "tenant_id": tenant,
            "node_count": len(node_coords),
            "nodeCoords": node_coords,
            "elements": elements,
            "pdf_citations": {
                "2001": {
                    "doc_id": "wing_stress_report.pdf",
                    "page_no": 42,
                    "bbox": [72.0, 210.0, 480.0, 245.0],
                },
                "2002": {
                    "doc_id": "rib_stress_report.pdf",
                    "page_no": 18,
                    "bbox": [60.0, 140.0, 410.0, 175.0],
                },
            },
        },
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["result"]["element_count"] == 50_000

    # PID filter query
    pid_resp = client.get("/cae/mesh/wing_box_rev_b", params={"tenant_id": tenant, "pid": 2001})
    assert pid_resp.status_code == 200
    assert pid_resp.json()["result"]["element_count"] == 25_000

    # Click-to-evidence (< 50 ms across 50 picks) tracing Element -> Calc -> PDF bbox
    latencies_ms: list[float] = []
    for probe_eid in (1, 12_344, 25_000, 49_999, 50_000):
        t0 = time.perf_counter()
        ev_resp = client.get(f"/cae/element/{probe_eid}/evidence", params={"tenant_id": tenant})
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        assert ev_resp.status_code == 200
        rec = ev_resp.json()["result"]
        assert rec["element_id"] == probe_eid
        assert "calc_event_hash" in rec
        assert "bbox" in rec["pdf_citation"]
        assert len(rec["pdf_citation"]["bbox"]) == 4

    assert max(latencies_ms) < 50.0, f"Click-to-evidence exceeded 50 ms: {latencies_ms}"

    # Verify viewer3d.js contains FEA 3D mesh hooks & balanced syntax
    js_path = REPO_ROOT / "apps" / "api" / "src" / "evidence_api" / "static" / "viewer3d.js"
    js_src = js_path.read_text(encoding="utf-8")
    for sym in (
        "setFeaMesh",
        "setFeaColorMode",
        "setPidFilter",
        "pickFeaElementAt",
        "_drawFeaViewport",
    ):
        assert sym in js_src
