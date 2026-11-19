"""Q3 Mega-Tests: 25 Stress Office Methods, MMPDS/CMH-17 Allowables, Units AST,
flint.arb Intervals, HSM/KMS + eIDAS QES + WebAuthn + SCIM 2.0 + SBOM,
and On-Prem Constrained Extraction + Frozen External B1 (156 cases / 12 cats) + B2-B4 Gates.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from evidence_api.app import create_app
from evidence_calc.allowables import (
    allowable_catalog_sha256,
    list_materials,
    lookup_allowable,
)
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import validate_plugin_card
from evidence_calc.registry import list_method_ids, run_method
from evidence_calc.stress_manual import STRESS_MANUAL_RUNNERS
from evidence_calc.units import check_expression_dimensional_homogeneity
from evidence_eval.onprem_holdout_suite import (
    B1_FAULT_CATEGORIES,
    ConstrainedJSONSchemaExtractor,
    evaluate_external_b1_holdout,
    generate_external_b1_holdout,
    run_b2_b3_b4_benchmarks,
)
from evidence_kernel.hsm_eidas_scim import (
    HSMKMSSigner,
    get_webauthn_verifier,
    verify_sbom_and_dependencies,
)
from fastapi.testclient import TestClient

_ALL_25_STRESS_SAMPLE_INPUTS: dict[str, dict[str, Any]] = {
    "adhesive_single_lap_volkersen": {
        "tensile_load_n": "12000",
        "overlap_width_mm": "50",
        "overlap_length_mm": "40",
        "adhesive_shear_modulus_mpa": "950",
        "adhesive_thickness_mm": "0.25",
        "adherend_modulus_mpa": "71700",
        "adherend_thickness_mm": "2.5",
        "adhesive_shear_allowable_mpa": "28",
    },
    "bearing_bypass_interaction": {
        "bearing_load_n": "9500",
        "bypass_load_n": "18000",
        "hole_diameter_mm": "6.35",
        "strip_width_mm": "38.1",
        "thickness_mm": "3.2",
        "bearing_allowable_mpa": "745",
        "bypass_oht_allowable_mpa": "360",
    },
    "bolt_preload_thermal_relaxation": {
        "initial_preload_n": "32000",
        "embedment_loss_n": "1500",
        "bolt_cte_per_c": "0.000011",
        "plate_cte_per_c": "0.000023",
        "delta_temp_c": "-75",
        "bolt_stiffness_n_per_mm": "220000",
        "joint_stiffness_n_per_mm": "680000",
        "grip_length_mm": "24",
        "external_tensile_load_n": "8500",
    },
    "compression_after_impact_cai": {
        "applied_compressive_mpa": "165",
        "cai_allowable_bvid_mpa": "285",
        "impact_energy_j": "25",
        "reference_bvid_j": "30",
        "environmental_knockdown": "0.90",
    },
    "curved_panel_compression_shear": {
        "compressive_stress_mpa": "65",
        "shear_stress_mpa": "40",
        "arc_width_mm": "160",
        "skin_thickness_mm": "2.4",
        "radius_curvature_mm": "1800",
        "modulus_mpa": "71700",
        "poisson_nu": "0.33",
    },
    "eccentric_bolt_group_cg": {
        "shear_vx_n": "4200",
        "shear_vy_n": "9600",
        "moment_mz_nmm": "280000",
        "half_spacing_x_mm": "35",
        "half_spacing_y_mm": "25",
        "bolt_shear_allowable_n": "16500",
    },
    "fastener_pull_through_composite": {
        "tensile_load_n": "2800",
        "head_diameter_mm": "12.5",
        "laminate_thickness_mm": "3.6",
        "ilss_allowable_mpa": "62",
        "countersink_knockdown": "0.85",
    },
    "goodman_haigh_mean_stress": {
        "alternating_stress_mpa": "95",
        "mean_stress_mpa": "110",
        "endurance_limit_mpa": "210",
        "ultimate_tensile_mpa": "510",
    },
    "hashin_composite_modes": {
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
    "huth_fastener_flexibility": {
        "fastener_diameter_mm": "6.35",
        "plate1_thickness_mm": "3.2",
        "plate2_thickness_mm": "4.0",
        "plate1_modulus_mpa": "71700",
        "plate2_modulus_mpa": "71700",
        "fastener_modulus_mpa": "110300",
        "huth_a_exp": "0.6667",
        "huth_b_coef": "4.2",
        "shear_planes_n": "1",
    },
    "inter_rivet_buckling": {
        "compressive_stress_mpa": "185",
        "rivet_pitch_mm": "22",
        "skin_thickness_mm": "2.2",
        "rivet_head_fixity_c": "2.5",
        "tangent_modulus_mpa": "68000",
    },
    "johnson_euler_column": {
        "compressive_load_n": "48000",
        "section_area_mm2": "620",
        "min_inertia_mm4": "190000",
        "column_length_mm": "380",
        "end_fixity_c": "1.0",
        "modulus_mpa": "71700",
        "compressive_yield_mpa": "441",
    },
    "lug_axial_transverse_interaction": {
        "axial_load_n": "14000",
        "transverse_load_n": "5200",
        "axial_allowable_n": "42000",
        "transverse_allowable_n": "28000",
    },
    "nasgro_paris_crack_growth": {
        "initial_crack_mm": "1.27",
        "delta_sigma_mpa": "75",
        "geometry_factor_y": "1.12",
        "fracture_toughness_mpa_sqrt_m": "36",
        "paris_c": "1.8e-10",
        "paris_m": "3.1",
        "required_cycles": "25000",
    },
    "needham_crippling_section": {
        "compressive_load_n": "34000",
        "flange_width_mm": "30",
        "flange_thickness_mm": "2.4",
        "web_width_mm": "55",
        "web_thickness_mm": "2.4",
        "modulus_mpa": "71700",
        "compressive_yield_mpa": "434",
    },
    "net_section_yielding_fracture": {
        "applied_load_n": "68000",
        "plate_width_mm": "140",
        "thickness_mm": "4.0",
        "half_crack_mm": "6.0",
        "yield_strength_mpa": "441",
        "fracture_toughness_mpa_sqrt_m": "36",
    },
    "neuber_notch_plasticity": {
        "nominal_stress_mpa": "195",
        "kt_concentration": "2.4",
        "modulus_mpa": "71700",
        "cyclic_strength_coeff_mpa": "890",
        "cyclic_hardening_exp": "0.11",
        "cyclic_yield_mpa": "460",
    },
    "open_hole_compression_ohc": {
        "applied_compressive_mpa": "190",
        "ohc_allowable_rtd_mpa": "320",
        "etw_knockdown": "0.85",
        "hole_diameter_mm": "6.35",
    },
    "open_hole_tension_oht": {
        "applied_far_field_mpa": "210",
        "oht_allowable_rtd_mpa": "410",
        "hole_diameter_mm": "6.35",
        "strip_width_mm": "38.1",
        "environmental_knockdown": "0.92",
    },
    "puck_interfiber_fracture": {
        "sigma_2_mpa": "18",
        "tau_12_mpa": "28",
        "yt_mpa": "62",
        "yc_mpa": "250",
        "sl_mpa": "92",
    },
    "rainflow_spectrum_damage": {
        "cycles_band1": "40000",
        "allowable_cycles_band1": "1000000",
        "cycles_band2": "12000",
        "allowable_cycles_band2": "250000",
        "cycles_band3": "1500",
        "allowable_cycles_band3": "50000",
        "scatter_factor": "4.0",
    },
    "sandwich_core_shear_wrinkling": {
        "facesheet_stress_mpa": "240",
        "transverse_shear_n_per_mm": "14",
        "facesheet_thickness_mm": "1.2",
        "core_thickness_mm": "18",
        "facesheet_modulus_mpa": "68000",
        "core_compression_modulus_mpa": "310",
        "core_shear_modulus_mpa": "165",
        "core_shear_allowable_mpa": "2.1",
    },
    "shear_web_diagonal_tension": {
        "applied_shear_n": "19500",
        "web_depth_mm": "220",
        "web_thickness_mm": "1.6",
        "stiffener_pitch_mm": "180",
        "modulus_mpa": "72400",
        "web_shear_ultimate_mpa": "269",
    },
    "thin_walled_bredt_batho_torsion": {
        "torque_nmm": "3200000",
        "enclosed_area_mm2": "24000",
        "perimeter_mm": "680",
        "min_wall_thickness_mm": "1.8",
        "shear_modulus_mpa": "27000",
        "shear_allowable_mpa": "269",
    },
    "tsai_wu_ply_failure": {
        "sigma_1_mpa": "450",
        "sigma_2_mpa": "22",
        "tau_12_mpa": "28",
        "xt_mpa": "2500",
        "xc_mpa": "1500",
        "yt_mpa": "62",
        "yc_mpa": "250",
        "s12_mpa": "92",
    },
}


def test_q3_mega_1_all_25_stress_methods_allowables_units_and_arb_intervals(
    tmp_path: Path,
) -> None:
    """Q3-1: Verify all 25 Stress Office methods, MMPDS/CMH-17, AST units & Arb bounds."""
    assert len(STRESS_MANUAL_RUNNERS) == 25
    assert set(_ALL_25_STRESS_SAMPLE_INPUTS.keys()) == set(STRESS_MANUAL_RUNNERS.keys())
    all_ids = list_method_ids()
    assert len(all_ids) >= 32

    max_drift_seen = Decimal("0")
    for method_id, inputs in sorted(_ALL_25_STRESS_SAMPLE_INPUTS.items()):
        outcome = run_method(
            method_id,
            inputs,
            include_intervals=True,
            normalize_units=True,
        )
        assert outcome["method_id"] == method_id
        assert len(outcome["outputs"]) >= 2
        intervals = outcome["exact_intervals"]
        assert len(intervals) >= 1
        for field_name, iv in intervals.items():
            assert Decimal(str(iv["lower"])) <= Decimal(str(iv["upper"])), (
                f"{method_id}.{field_name} invalid interval"
            )
            drift = Decimal(str(iv["quantization_drift"]))
            if drift > max_drift_seen:
                max_drift_seen = drift
            staged_text = str(iv["staged"])
            decimals = len(staged_text.split(".", 1)[1]) if "." in staged_text else 0
            half_ulp = Decimal("10") ** (-decimals) * Decimal("0.51")
            assert drift <= half_ulp, (
                f"{method_id}.{field_name} drift exceeded half-ULP ({half_ulp}): {drift}"
            )

    # MMPDS-16 & CMH-17 A-Basis / B-Basis + knockdowns & catalog hash provenance
    mats = list_materials()
    for required_mat in ("AL-7075-T651", "AL-2024-T3", "TI-6AL-4V", "IM7-8552-UD", "15-5PH-H1025"):
        assert required_mat in mats

    al_a_rtd = lookup_allowable(
        "AL-7075-T651", basis="A", property_name="fty_mpa", environment="RTD"
    )
    al_b_rtd = lookup_allowable(
        "AL-7075-T651", basis="B", property_name="fty_mpa", environment="RTD"
    )
    al_a_etw_hot = lookup_allowable(
        "AL-7075-T651",
        basis="A",
        property_name="fty_mpa",
        thickness_mm="60",
        temp_c="120",
        environment="ETW",
    )
    assert Decimal(al_b_rtd["allowable_value_mpa"]) > Decimal(al_a_rtd["allowable_value_mpa"])
    assert Decimal(al_a_etw_hot["allowable_value_mpa"]) < Decimal(al_a_rtd["allowable_value_mpa"])
    assert al_a_rtd["catalog_sha256"] == allowable_catalog_sha256()

    cmh_a = lookup_allowable("IM7-8552-UD", basis="A", property_name="ohc_mpa", environment="ETW")
    assert cmh_a["standard"] == "CMH-17 Rev H"

    with pytest.raises(AbstainError, match="allowable_outside_temp_range"):
        lookup_allowable("AL-7075-T651", temp_c="250")

    # End-to-end method resolution with material_lookup
    mat_calc = run_method(
        "bearing_bypass_interaction",
        {
            "bearing_load_n": "9500",
            "bypass_load_n": "18000",
            "hole_diameter_mm": "6.35",
            "strip_width_mm": "38.1",
            "thickness_mm": "3.2",
            "bypass_oht_allowable_mpa": "360",
            "material_lookup": {
                "target_field": "bearing_allowable_mpa",
                "material_id": "AL-7075-T651",
                "basis": "A",
                "property_name": "fbru_e15_mpa",
                "environment": "ETW",
                "temp_c": "85",
            },
        },
        include_intervals=True,
    )
    assert "bearing_allowable_mpa" in mat_calc["allowable_provenance"]
    assert mat_calc["allowable_provenance"]["bearing_allowable_mpa"]["catalog_sha256"] == (
        allowable_catalog_sha256()
    )

    # Static AST dimensional homogeneity checker & plugin rejection
    assert check_expression_dimensional_homogeneity(
        "force / area", {"force": "newton", "area": "millimeter ** 2"}
    ) == {"M": 1, "L": -1, "T": -2}

    with pytest.raises(AbstainError, match="dimensional_inhomogeneity"):
        check_expression_dimensional_homogeneity(
            "force + length", {"force": "newton", "length": "millimeter"}
        )

    with pytest.raises(AbstainError, match="dimensional_inhomogeneity"):
        check_expression_dimensional_homogeneity(
            "stress + area", {"stress": "megapascal", "area": "millimeter ** 2"}
        )

    with pytest.raises(AbstainError, match="dimensional_inhomogeneity"):
        check_expression_dimensional_homogeneity("length ** 0.5", {"length": "millimeter"})

    bad_plugin = {
        "method_id": "bad_dim_plugin",
        "method_version": "bad_dim_plugin@1.0.0",
        "title": "Incompatible Sum",
        "label": "bad",
        "quantum": "0.001",
        "plugin": True,
        "required": ["force", "length"],
        "input_units": {"force": "newton", "length": "millimeter"},
        "limits": {"force": {"min": "0", "max": "1000"}, "length": {"min": "0", "max": "1000"}},
        "formulas": [{"output": "bad_out", "expr": "force + length", "unit": "newton"}],
        "sources": [{"source_id": "src-1", "title": "Test", "locator": "Sec 1"}],
    }
    with pytest.raises(AbstainError, match="dimensional_inhomogeneity"):
        validate_plugin_card(bad_plugin)


def test_q3_mega_2_hsm_qes_webauthn_stepup_and_scim_revocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q3-2: Verify HSM off-disk signing, eIDAS QES LTV, WebAuthn step-up, SCIM 2.0 & SBOM."""
    evidence_dir = tmp_path / "evidence_home"
    hsm_deploy_dir = tmp_path / "hsm_deploy_root"
    hsm_deploy_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVIDENCE_HOME", str(evidence_dir))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "mega-q3-test-session-secret-0123456789")

    # 1. HSM/KMS in-memory keys (Ed25519 + ES256), never touching filesystem
    hsm = HSMKMSSigner(key_uri="pkcs11:token=q3-hsm;object=signoff-key", algorithm="Ed25519")
    sample_digest = b"evidence-dossier-merkle-root-sha256"
    sig_ed = hsm.sign_digest(sample_digest)
    assert sig_ed["hsm_backed"] is True
    assert sig_ed["extractable"] is False
    assert HSMKMSSigner.verify_signature(sample_digest, sig_ed) is True
    assert HSMKMSSigner.verify_signature(sample_digest + b"tamper", sig_ed) is False

    hsm_es256 = HSMKMSSigner(key_uri="kms://aeroregu/es256-slot", algorithm="ES256")
    sig_es = hsm_es256.sign_digest(sample_digest)
    assert HSMKMSSigner.verify_signature(sample_digest, sig_es) is True

    (hsm_deploy_dir / "pubkey.pem").write_text(hsm.export_public_key_pem(), encoding="utf-8")
    disk_audit = HSMKMSSigner.verify_no_private_keys_on_disk(hsm_deploy_dir)
    assert disk_audit["private_keys_found_on_disk"] == 0
    assert disk_audit["clean"] is True

    # Seed ledger events via FastAPI endpoints
    tenant_id = "megaq3sec"
    app = create_app()
    client = TestClient(app)

    login_author = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": tenant_id},
    )
    assert login_author.status_code == 200
    author_token = login_author.json()["result"]["session_token"]

    ing = client.post(
        "/ingest/document",
        json={
            "filename": "req_q3.txt",
            "content_text": (
                "REQ-Q3-001: Primary lug shall sustain 14 kN axial + 5.2 kN transverse."
            ),
            "record": True,
            "tenant_id": tenant_id,
        },
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert ing.status_code == 200

    calc_resp = client.post(
        "/calc/run",
        json={
            "method_id": "lug_axial_transverse_interaction",
            "inputs": _ALL_25_STRESS_SAMPLE_INPUTS["lug_axial_transverse_interaction"],
            "record": True,
            "tenant_id": tenant_id,
        },
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert calc_resp.status_code == 200
    verify_res = client.get("/ledger/verify", params={"tenant_id": tenant_id})
    assert verify_res.status_code == 200
    target_hash = verify_res.json()["result"]["head_hash"]

    # 2. Switch to CVE reviewer & test eIDAS QES (CAdES-B-LT & PAdES-B-LT) + WebAuthn step-up
    login_cve = client.post(
        "/auth/login",
        json={"actor_id": "reviewer", "password": "reviewer-local", "tenant_id": tenant_id},
    )
    assert login_cve.status_code == 200
    cve_token = login_cve.json()["result"]["session_token"]
    cve_headers = {"Authorization": f"Bearer {cve_token}"}

    for qes_profile in ("CAdES-B-LT", "PAdES-B-LT"):
        qes_res = client.post(
            "/export/bundle/qes",
            json={"tenant_id": tenant_id, "profile": qes_profile},
            headers=cve_headers,
        )
        assert qes_res.status_code == 200
        qes_data = qes_res.json()["result"]
        assert qes_data["qes_envelope"]["profile"] == qes_profile
        assert qes_data["verification"]["verified"] is True
        assert qes_data["verification"]["signature_valid"] is True
        assert qes_data["verification"]["tsa_rfc3161_valid"] is True
        assert qes_data["verification"]["ocsp_crl_ltv_valid"] is True
        assert qes_data["verification"]["hsm_backed"] is True

    # Require WebAuthn: must fail without assertion
    missing_wa = client.post(
        "/coverage/signoff",
        json={
            "tenant_id": tenant_id,
            "target_event_hash": target_hash,
            "require_webauthn": True,
        },
        headers=cve_headers,
    )
    assert missing_wa.status_code == 403
    assert missing_wa.json()["abstain"]["reason"] == "webauthn_step_up_required"

    # Issue single-use challenge, sign with FIDO2 authenticator, complete signoff once
    ch_res = client.post(
        "/auth/webauthn/challenge",
        json={"tenant_id": tenant_id, "action": "coverage_signoff"},
        headers=cve_headers,
    )
    assert ch_res.status_code == 200
    challenge_payload = ch_res.json()["result"]
    assertion = get_webauthn_verifier().build_signed_assertion(challenge_payload)

    signoff_ok = client.post(
        "/coverage/signoff",
        json={
            "tenant_id": tenant_id,
            "target_event_hash": target_hash,
            "require_webauthn": True,
            "webauthn_assertion": assertion,
            "review_duration_ms": 1200,
        },
        headers=cve_headers,
    )
    assert signoff_ok.status_code == 200
    assert signoff_ok.json()["result"]["webauthn_verified"] is True

    # Replay of same FIDO2 assertion must be rejected
    signoff_replay = client.post(
        "/coverage/signoff",
        json={
            "tenant_id": tenant_id,
            "target_event_hash": target_hash,
            "require_webauthn": True,
            "webauthn_assertion": assertion,
        },
        headers=cve_headers,
    )
    assert signoff_replay.status_code == 403
    assert signoff_replay.json()["abstain"]["reason"] == "webauthn_challenge_replay"

    # 3. SCIM 2.0 instant revocation (< 10ms)
    scim_create = client.post(
        "/scim/v2/Users",
        json={
            "tenant_id": tenant_id,
            "userName": "reviewer",
            "displayName": "CVE Reviewer",
            "roles": ["cve"],
            "active": True,
        },
    )
    assert scim_create.status_code == 201
    scim_uid = scim_create.json()["id"]

    me_before = client.get("/auth/me", params={"tenant_id": tenant_id}, headers=cve_headers)
    assert me_before.status_code == 200

    t0 = time.perf_counter()
    scim_patch = client.patch(
        f"/scim/v2/Users/{scim_uid}",
        params={"tenant_id": tenant_id},
        json={
            "tenant_id": tenant_id,
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
    )
    revoke_wall_ms = (time.perf_counter() - t0) * 1000.0
    assert scim_patch.status_code == 200
    assert scim_patch.json()["active"] is False
    assert scim_patch.json()["meta"]["revocation_latency_ms"] < 10.0
    assert revoke_wall_ms < 250.0

    me_after = client.get("/auth/me", params={"tenant_id": tenant_id}, headers=cve_headers)
    assert me_after.status_code == 401

    # 4. CycloneDX 1.5 SBOM & CVE gate
    repo_root = Path(__file__).resolve().parents[1]
    sbom = verify_sbom_and_dependencies(repo_root)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert sbom["component_count"] > 10
    assert sbom["cve_gate_passed"] is True
    assert len(sbom["sbom_sha256"]) == 64


def test_q3_mega_3_onprem_constrained_extractor_and_b1_b4_holdout_gates(
    tmp_path: Path,
) -> None:
    """Q3-3: Verify local constrained extraction (10/10 deterministic, 0 bbox hallucination),
    external frozen B1 holdout (>=150 cases / 12 fault categories, recall >=0.99, 0 FN),
    and B2-B4 benchmark gates.
    """
    extractor = ConstrainedJSONSchemaExtractor(temperature=0.0, seed=42)
    blocks = [
        {
            "block_id": "mmpds-tbl-321",
            "page": 14,
            "bbox": [48.0, 112.0, 520.0, 148.0],
            "text": "ftu_mpa = 510.0 fty_mpa = 441.0 thickness_mm = 12.7",
        }
    ]
    schema = {
        "required": ["ftu_mpa", "fty_mpa", "thickness_mm"],
        "properties": {
            "ftu_mpa": {"type": "string"},
            "fty_mpa": {"type": "string"},
            "thickness_mm": {"type": "string"},
        },
    }

    hashes = []
    for _ in range(10):
        res = extractor.extract(blocks=blocks, schema=schema)
        assert res["status"] == "extracted"
        assert res["hallucinated_bbox_count"] == 0
        hashes.append(res["output_sha256"])
    assert len(set(hashes)) == 1

    # Fabricated bbox citation must abstain
    bad_cit = extractor.extract(
        blocks=blocks,
        schema=schema,
        candidate_output={
            "ftu_mpa": "510.0",
            "fty_mpa": "441.0",
            "thickness_mm": "12.7",
            "citations": [{"block_id": "mmpds-tbl-321", "page": 99, "bbox": [0.0, 0.0, 1.0, 1.0]}],
        },
    )
    assert bad_cit["status"] == "abstain"
    assert bad_cit["reason"] == "ungrounded_citation_abstain"
    assert bad_cit["hallucinated_bbox_count"] > 0

    # Missing required field must abstain rather than fabricate
    missing_field = extractor.extract(
        blocks=[
            {
                "block_id": "b1",
                "page": 1,
                "bbox": [10.0, 10.0, 50.0, 30.0],
                "text": "ftu_mpa = 510.0",
            }
        ],
        schema=schema,
    )
    assert missing_field["status"] == "abstain"
    assert missing_field["reason"] == "low_confidence_abstain"

    # External frozen B1 holdout (>=150 cases, all 12 fault categories) in tmp_path
    ext_b1_dir = tmp_path / "external_frozen_b1"
    gen_meta = generate_external_b1_holdout(ext_b1_dir, count=156)
    assert gen_meta["cases_written"] == 156
    assert set(B1_FAULT_CATEGORIES).issubset(set(gen_meta["fault_categories"]))

    b1_report = evaluate_external_b1_holdout(ext_b1_dir)
    assert b1_report["total_cases"] >= 150
    assert b1_report["categories_covered"] == 12
    assert b1_report["recall"] >= 0.99
    assert b1_report["fn"] == 0
    assert b1_report["false_positive_rate"] <= 0.05
    # Every seeded ungrounded citation fault was caught, with zero hallucinated bboxes
    assert b1_report["by_category"]["ungrounded_citation"]["fn"] == 0
    assert (
        b1_report["hallucinated_bbox_count"]
        == b1_report["by_category"]["ungrounded_citation"]["tp"]
    )
    assert b1_report["reproducible_10_of_10"] is True

    # Verify B2-B4 benchmarks pass
    bench = run_b2_b3_b4_benchmarks()
    assert bench["b2"]["status"] == "PASS"
    assert bench["b3"]["status"] == "PASS"
    assert bench["b4"]["status"] == "PASS"
    assert bench["b3"]["hallucinated_bbox_count"] == 0
    assert bench["b4"]["seeded_fault_catch_rate"] == 1.0
