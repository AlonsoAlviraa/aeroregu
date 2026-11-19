"""Q4 Mega-Tests: Full Metallic & Composite Program + Visual ECN Diff + Review Threads,
Concurrent Soak & Chaos Fault Injection (Zero Corruption), and Qualification Aid Pack (ADR-018),
Standalone Offline Verifier, Air-Gapped K8s/OCI/MSIX, & M&A Technical Closure (ADR-020).
"""

from __future__ import annotations

import io
import json
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from evidence_api.app import create_app
from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_coverage.collaboration_ecn import (
    ReviewThreadStore,
    compute_ecn_revision_diff,
)
from evidence_coverage.ma_readiness import evaluate_ma_technical_readiness
from evidence_coverage.qualification_aid import (
    ASSISTANCE_DISCLAIMER,
    run_iq_oq_qualification_suite,
    verify_standalone_dossier_offline,
)
from evidence_ingest.cad_brep import (
    _make_box_mesh,
    analyze_step_brep,
    compute_exact_mass_properties,
)
from evidence_ingest.cae_binary import (
    DTYPE_ELEM,
    DTYPE_EQUILIBRIUM,
    DTYPE_NODE,
    DTYPE_STRESS_CHUNK,
    parse_nastran_op2_file,
    write_nastran_op2_stream,
)
from evidence_kernel.ledger import Ledger, LedgerError
from fastapi.testclient import TestClient

_SAMPLE_STEP_WITH_PLY_BOOK = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Wing Rib Assembly'),'2;1');
FILE_NAME('rib_q4.stp','2026-11-14T10:00:00',('Author'),('Aeroregu'),'','','');
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#10 = SI_UNIT(*,.MILLI.,.METRE.);
#20 = CARTESIAN_POINT('',(0.0,0.0,0.0));
#21 = CARTESIAN_POINT('',(200.0,0.0,0.0));
#22 = CARTESIAN_POINT('',(0.0,100.0,0.0));
#23 = CARTESIAN_POINT('',(0.0,0.0,10.0));
/* CATIA_PLY_BOOK: WING_SKIN_LAMINATE [45/-45/0/90]s */
ENDSEC;
END-ISO-10303-21;
"""


def _build_minimal_valid_op2(op2_path: Path) -> dict[str, object]:
    nodes = np.array(
        [
            (1, 0.0, 0.0, 0.0),
            (2, 100.0, 0.0, 0.0),
            (3, 100.0, 100.0, 0.0),
            (4, 0.0, 100.0, 0.0),
        ],
        dtype=DTYPE_NODE,
    )
    elems = np.array(
        [(101, 10, 4, 1, 2, 3, 4, 441.0), (102, 11, 4, 1, 2, 3, 4, 265.0)],
        dtype=DTYPE_ELEM,
    )
    eq = np.array(
        [(1, 1000.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1000.0, 0.0, 0.0, 0.0, 0.0, 0.0)],
        dtype=DTYPE_EQUILIBRIUM,
    )
    stress = np.array(
        [
            (1, 101, 10, 4, 210.0, 110.0, 1.10),
            (1, 102, 11, 4, 240.0, 120.0, 0.104),
        ],
        dtype=DTYPE_STRESS_CHUNK,
    )
    write_nastran_op2_stream(
        op2_path, nodes=nodes, elements=elems, equilibrium=eq, stress_chunks=[stress]
    )
    return parse_nastran_op2_file(op2_path, source_hash="op2-q4-mega")


def test_q4_mega_1_full_metallic_and_composite_program_ecn_and_review_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q4-1: End-to-end metallic & composite program with ECN diff, Excel/CATIA & review lock."""
    evidence_dir = tmp_path / "evidence_home"
    monkeypatch.setenv("EVIDENCE_HOME", str(evidence_dir))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "mega-q4-program-session-secret-012345")

    # CAD B-Rep mass props + CATIA Ply Book + Binary OP2 FEM
    mesh = _make_box_mesh(
        "RIB-WEB-AL7075",
        "RIB-WEB-AL7075",
        200.0,
        100.0,
        10.0,
        np.eye(4, dtype=np.float64),
        2810.0,
        "AL-7075",
    )
    mass_props = compute_exact_mass_properties(mesh)
    step_info = analyze_step_brep(_SAMPLE_STEP_WITH_PLY_BOOK.encode("utf-8"), "step-q4-hash")
    assert step_info["composite_ply_book"]["stack_count"] >= 1
    assert step_info["composite_ply_book"]["all_rules_satisfied"] is True
    op2_res = _build_minimal_valid_op2(tmp_path / "wing_rib.op2")
    assert op2_res["equilibrium_verified"] is True

    app = create_app()
    client = TestClient(app)
    tenant_id = "megaq4prog"

    # Author & CVE logins
    tok_author = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": tenant_id},
    ).json()["result"]["session_token"]
    tok_cve = client.post(
        "/auth/login",
        json={"actor_id": "reviewer", "password": "reviewer-local", "tenant_id": tenant_id},
    ).json()["result"]["session_token"]
    h_author = {"Authorization": f"Bearer {tok_author}"}
    h_cve = {"Authorization": f"Bearer {tok_cve}"}

    # Ingest requirement & run metallic + composite methods
    ing = client.post(
        "/ingest/document",
        json={
            "filename": "wing_rib_spec.txt",
            "content_text": (
                "REQ-Q4-01: Rib lug & CFRP facesheet shall keep positive MS under ultimate load."
            ),
            "record": True,
            "tenant_id": tenant_id,
        },
        headers=h_author,
    )
    assert ing.status_code == 200

    lug_calc = client.post(
        "/calc/run",
        json={
            "method_id": "lug_axial_transverse_interaction",
            "inputs": {
                "axial_load_n": "14000",
                "transverse_load_n": "5200",
                "axial_allowable_n": "42000",
                "transverse_allowable_n": "28000",
            },
            "record": True,
            "tenant_id": tenant_id,
        },
        headers=h_author,
    )
    assert lug_calc.status_code == 200

    comp_calc = client.post(
        "/calc/run",
        json={
            "method_id": "hashin_composite_modes",
            "inputs": {
                "sigma_1_mpa": "420",
                "sigma_2_mpa": "24",
                "tau_12_mpa": "32",
                "xt_mpa": "2500",
                "xc_mpa": "1500",
                "yt_mpa": "62",
                "yc_mpa": "250",
                "sl_mpa": "92",
                "st_mpa": "75",
            },
            "record": True,
            "tenant_id": tenant_id,
        },
        headers=h_author,
    )
    assert comp_calc.status_code == 200

    target_hash = client.get("/ledger/verify", params={"tenant_id": tenant_id}).json()["result"][
        "head_hash"
    ]

    # Excel Stress Sheet Bridge
    excel_res = client.post(
        "/integrations/excel/sync",
        json={
            "tenant_id": tenant_id,
            "workbook_id": "RIB-STRESS-WK-09",
            "sheet_name": "LugSizing",
            "method_id": "lug_axial_transverse_interaction",
            "named_ranges": {
                "axial_load_n": {"cell": "B4", "value": "14000"},
                "transverse_load_n": {"cell": "B5", "value": "5200"},
                "axial_allowable_n": {"cell": "B6", "value": "42000"},
                "transverse_allowable_n": {"cell": "B7", "value": "28000"},
            },
        },
    )
    assert excel_res.status_code == 200
    stamp = excel_res.json()["result"]["stamp"]
    assert stamp["written_named_ranges"]["AEROREGU_STATUS"] == "VERIFIED"
    assert len(stamp["written_named_ranges"]["AEROREGU_MERKLE_ROOT"]) == 64

    # CATIA Inspector Bridge
    catia_res = client.post(
        "/integrations/catia/selection",
        json={
            "part_number": "RIB-WEB-AL7075",
            "feature_id": "POCKET_3",
            "ply_id": "PLY_01_45DEG",
            "element_id": 102,
            "cad_result": mass_props,
            "margins_by_part": {
                "RIB-WEB-AL7075": {"ms": op2_res["ms_min"], "method_id": "hashin_composite_modes"}
            },
        },
    )
    assert catia_res.status_code == 200
    assert catia_res.json()["result"]["verification_status"] == "VERIFIED"
    assert catia_res.json()["result"]["click_to_evidence_ms"] < 50.0

    # ECN Rev A vs Rev B visual diff highlighting degraded margin
    ecn_res = client.post(
        "/ecn/diff",
        json={
            "ecn_id": "ECN-RIB-2026-42",
            "rev_a": {
                "requirements": [{"id": "REQ-Q4-01", "load_kn": "14.0"}],
                "cad": {
                    "mass_kg": mass_props["mass_kg"],
                    "cg_mm": [100, 50, 5],
                    "min_thickness_mm": "2.4",
                },
                "fem": {"peak_von_mises_mpa": "210", "critical_elements": [101]},
                "margins": {"lug_ms": "1.18", "cai_ms": "0.42"},
            },
            "rev_b": {
                "requirements": [{"id": "REQ-Q4-01", "load_kn": "18.5"}],
                "cad": {"mass_kg": "0.510", "cg_mm": [115, 50, 5], "min_thickness_mm": "2.0"},
                "fem": {"peak_von_mises_mpa": "318", "critical_elements": [101, 102]},
                "margins": {"lug_ms": "0.62", "cai_ms": "-0.04"},
            },
        },
    )
    assert ecn_res.status_code == 200
    ecn_data = ecn_res.json()["result"]
    assert ecn_data["impact_summary"]["degraded_count"] == 2
    assert ecn_data["impact_summary"]["negative_ms_count"] == 1
    assert ecn_data["impact_summary"]["signoff_reverification_required"] is True

    # Author <-> CVE Review Threads blocking signoff & locking upon resolution+signoff
    thr_create = client.post(
        "/reviews/threads",
        json={
            "tenant_id": tenant_id,
            "target_event_hash": target_hash,
            "category": "margin_degradation",
            "initial_status": "CHANGES_REQUESTED",
            "anchor": {"ecn_id": "ECN-RIB-2026-42", "item_id": "cai_ms"},
            "body": "Rev B CAI MS turned -0.04 after pocket depth increase; reinforce ply drop.",
        },
        headers=h_cve,
    )
    assert thr_create.status_code == 200
    thread_id = thr_create.json()["result"]["thread_id"]

    # Signoff must be blocked (409) while review thread is unresolved
    blocked_signoff = client.post(
        "/coverage/signoff",
        json={"tenant_id": tenant_id, "target_event_hash": target_hash},
        headers=h_cve,
    )
    assert blocked_signoff.status_code == 409
    assert blocked_signoff.json()["abstain"]["reason"] == "unresolved_review_threads"

    # Author replies, then CVE resolves
    reply_ok = client.post(
        f"/reviews/threads/{thread_id}/reply",
        json={"tenant_id": tenant_id, "body": "Added +2x 0-deg plies; CAI MS raised to +0.28."},
        headers=h_author,
    )
    assert reply_ok.status_code == 200

    resolve_ok = client.post(
        f"/reviews/threads/{thread_id}/resolve",
        json={"tenant_id": tenant_id, "resolution_note": "Verified updated ply stack."},
        headers=h_cve,
    )
    assert resolve_ok.status_code == 200
    assert resolve_ok.json()["result"]["status"] == "RESOLVED"

    # Signoff succeeds & locks thread permanently
    signoff_ok = client.post(
        "/coverage/signoff",
        json={"tenant_id": tenant_id, "target_event_hash": target_hash, "review_duration_ms": 950},
        headers=h_cve,
    )
    assert signoff_ok.status_code == 200
    assert thread_id in signoff_ok.json()["result"]["locked_review_threads"]

    listed = client.get("/reviews/threads", params={"tenant_id": tenant_id}).json()["result"][
        "threads"
    ]
    assert listed[0]["status"] == "LOCKED_ON_SIGNOFF"

    locked_reply = client.post(
        f"/reviews/threads/{thread_id}/reply",
        json={"tenant_id": tenant_id, "body": "Attempted post-signoff edit"},
        headers=h_author,
    )
    assert locked_reply.status_code == 409
    assert locked_reply.json()["abstain"]["reason"] == "thread_locked"

    # Export QES signed bundle
    qes = client.post(
        "/export/bundle/qes",
        json={"tenant_id": tenant_id, "profile": "CAdES-B-LT"},
        headers=h_cve,
    )
    assert qes.status_code == 200
    assert qes.json()["result"]["verification"]["verified"] is True


def test_q4_mega_2_concurrent_soak_chaos_fault_injection_zero_corruption(
    tmp_path: Path,
) -> None:
    """Q4-2: Concurrent multi-worker soak + chaos fault injection with zero ledger corruption."""
    ledger = Ledger(tmp_path / "soak_ledger.sqlite3", tenant_id="soak-q4")
    store = ReviewThreadStore()

    valid_envelope = {
        "sources": [
            {
                "source_id": "src-soak-01",
                "uri": "evidence://soak/spec.txt",
                "content_hash": "a" * 64,
                "label": "VERIFIED",
            }
        ],
        "method_version": "johnson_euler_column@1.0.0",
        "inputs_hash": "b" * 64,
        "confidence": "deterministic",
        "result": {"margin_of_safety": "0.304"},
        "abstain": None,
    }
    seed_hashes: list[str] = []
    for i in range(40):
        ev_h = ledger.append(
            {
                "event_type": "calc",
                "tenant_id": "soak-q4",
                "actor_id": "author",
                "created_at": "2026-11-14T12:00:00Z",
                "payload": {"iter": i, "margin_of_safety": "0.304"},
                "envelope": valid_envelope,
            }
        )
        seed_hashes.append(ev_h)

    def _worker(idx: int) -> dict[str, int]:
        ok = 0
        expected_abstains = 0
        # Valid deterministic calculation + ECN diff
        res = run_method(
            "johnson_euler_column",
            {
                "compressive_load_n": str(42000 + idx * 50),
                "section_area_mm2": "620",
                "min_inertia_mm4": "190000",
                "column_length_mm": "380",
                "end_fixity_c": "1.0",
                "modulus_mpa": "71700",
                "compressive_yield_mpa": "441",
            },
            include_intervals=True,
        )
        assert "margin_of_safety" in res["outputs"]
        ok += 1

        diff = compute_ecn_revision_diff(
            {"margins": {"m1": "0.45"}},
            {"margins": {"m1": "0.18"}},
            ecn_id=f"SOAK-{idx}",
        )
        assert diff["impact_summary"]["degraded_count"] == 1
        ok += 1

        # Concurrent review thread create + resolve + lock + post-lock mutation fault test
        thr = store.create_thread(
            "soak-q4",
            target_event_hash=seed_hashes[idx % len(seed_hashes)],
            author_id=f"cve-{idx % 4}",
            body=f"Soak thread {idx}",
        )
        store.resolve_thread("soak-q4", thr["thread_id"], resolver_id="cve-lead")
        ok += 1

        # Chaos Fault 1: Out-of-validity calculation must raise AbstainError cleanly
        try:
            run_method(
                "margin_of_safety",
                {
                    "applied_load_n": "-999",
                    "allowable_load_n": "10000",
                    "reserve_factor": "1.0",
                    "fitting_factor": "1.15",
                },
            )
            raise AssertionError("Negative load should have abstained")
        except AbstainError:
            expected_abstains += 1

        # Chaos Fault 2: Float injection into hash-chained ledger must fail safely
        try:
            ledger.append(
                {
                    "event_type": "calc",
                    "tenant_id": "soak-q4",
                    "actor_id": "chaos",
                    "created_at": "2026-11-14T12:00:00Z",
                    "payload": {"unsafe_float": 1.234},
                    "envelope": valid_envelope,
                }
            )
            raise AssertionError("Float payload should have been rejected")
        except (TypeError, LedgerError):
            expected_abstains += 1

        return {"ok": ok, "expected_abstains": expected_abstains}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_worker, range(60)))
    elapsed = time.perf_counter() - t0

    assert sum(r["ok"] for r in results) == 180
    assert sum(r["expected_abstains"] for r in results) == 120
    assert elapsed < 30.0
    assert ledger.verify() is True
    assert len(ledger.events()) == 40
    # Offline verifier confirms zero corruption across concurrent chaos
    offline = verify_standalone_dossier_offline(
        ledger.events(), expected_merkle_root=ledger.merkle_root()
    )
    assert offline["verified"] is True
    assert offline["inclusion_proofs_verified"] is True


def test_q4_mega_3_qualification_aid_iq_oq_standalone_verifier_airgap_and_ma_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q4-3: Verify Qualification Aid Pack (ADR-018), standalone offline ZIP verifier,
    air-gapped Helm/OCI/MSIX artifacts, and M&A Technical Closure (ADR-020).
    """
    evidence_dir = tmp_path / "evidence_home"
    monkeypatch.setenv("EVIDENCE_HOME", str(evidence_dir))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "mega-q4-qual-session-secret-9876543210")

    repo_root = Path(__file__).resolve().parents[1]

    # ADR-018: Qualification Aid folder exists without DO-330 cert claim or tools/pack
    assert not (repo_root / "tools" / "pack").exists()
    for fname in (
        "tool_operational_requirements_tor.md",
        "tool_qualification_plan_tqp.md",
        "requirement_trace_matrix_rtm.json",
    ):
        fpath = repo_root / "docs" / "qualification" / fname
        assert fpath.is_file()
        assert ASSISTANCE_DISCLAIMER in fpath.read_text(encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    # Run IQ/OQ via Python & HTTP
    iq_oq_direct = run_iq_oq_qualification_suite(repo_root=repo_root)
    iq_oq_http = client.post("/qualification/iq-oq/run", json={})
    assert iq_oq_http.status_code == 200
    iq_oq_data = iq_oq_http.json()["result"]
    assert iq_oq_direct["status"] == "PASS"
    assert iq_oq_data["status"] == "PASS"
    assert iq_oq_data["iq_passed"] is True
    assert iq_oq_data["oq_passed"] is True
    assert iq_oq_data["assistance_disclaimer"] == ASSISTANCE_DISCLAIMER

    # Seed tenant, export signed ZIP bundle, verify offline without server runtime DB
    tenant_id = "megaq4offline"
    tok_author = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": tenant_id},
    ).json()["result"]["session_token"]
    h_author = {"Authorization": f"Bearer {tok_author}"}
    client.post(
        "/calc/run",
        json={
            "method_id": "margin_of_safety",
            "inputs": {
                "applied_load_n": "10000",
                "allowable_load_n": "15000",
                "reserve_factor": "1.0",
                "fitting_factor": "1.15",
            },
            "record": True,
            "tenant_id": tenant_id,
        },
        headers=h_author,
    )

    zip_resp = client.post("/export/zip", params={"tenant_id": tenant_id}, headers=h_author)
    assert zip_resp.status_code == 200
    zip_bytes = zip_resp.content

    offline_ok = verify_standalone_dossier_offline(zip_bytes)
    assert offline_ok["verified"] is True
    assert offline_ok["chain_verified"] is True
    assert offline_ok["merkle_verified"] is True
    assert offline_ok["inclusion_proofs_verified"] is True
    assert offline_ok["signature_verified"] is True
    assert offline_ok["event_count"] >= 1

    # Tamper 1 event field inside exported zip -> offline verifier MUST reject
    tampered_buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zin,
        zipfile.ZipFile(tampered_buf, "w") as zout,
    ):
        for name in zin.namelist():
            data = zin.read(name)
            if name == "chain.json":
                events = json.loads(data.decode("utf-8"))
                events[0]["body"]["payload"]["tampered"] = "YES"
                data = json.dumps(events).encode("utf-8")
            zout.writestr(name, data)

    offline_tampered = verify_standalone_dossier_offline(tampered_buf.getvalue())
    assert offline_tampered["verified"] is False
    assert offline_tampered["chain_verified"] is False

    # Air-gapped K8s Helm, OCI bundle & Windows MSIX validation
    values_text = (repo_root / "infra" / "helm" / "aeroregu" / "values.yaml").read_text(
        encoding="utf-8"
    )
    deploy_text = (
        repo_root / "infra" / "helm" / "aeroregu" / "templates" / "deployment.yaml"
    ).read_text(encoding="utf-8")
    assert "allowOutboundInternetEgress: false" in values_text
    assert "pullPolicy: Never" in values_text
    assert "NetworkPolicy" in deploy_text

    oci_manifest = json.loads(
        (repo_root / "infra" / "airgap" / "oci-bundle-manifest.json").read_text(encoding="utf-8")
    )
    assert oci_manifest["airgap_verified"] is True
    assert oci_manifest["outbound_network_required"] is False
    assert all(str(img["digest"]).startswith("sha256:") for img in oci_manifest["images"])

    msix_root = ET.fromstring(
        (repo_root / "infra" / "installer" / "windows-msix-manifest.xml").read_text(
            encoding="utf-8"
        )
    )
    assert msix_root.tag.endswith("Package")

    # M&A Readiness (ADR-020) via direct call & HTTP, while preserving docs/legal/open_items.md
    ma_direct = evaluate_ma_technical_readiness(repo_root)
    ma_http = client.get("/legal/ma-readiness")
    assert ma_http.status_code == 200
    ma_data = ma_http.json()["result"]
    assert ma_direct["status"] == "READY"
    assert ma_data["status"] == "READY"
    assert ma_data["due_diligence_items_closed"] == 9
    assert ma_data["all_nine_items_closed"] is True
    assert ma_data["missing_evidence_paths"] == []
    assert ma_data["oss_license_audit"]["copyleft_violations"] == []
    assert ma_data["untracked_dual_licensed"] == []
    assert any(
        pkg["package"].lower() == "pymupdf"
        for pkg in ma_data["oss_license_audit"]["commercial_dual_licensed"]
    )
    assert "| OPEN |" in (repo_root / "docs" / "legal" / "open_items.md").read_text(
        encoding="utf-8"
    )
