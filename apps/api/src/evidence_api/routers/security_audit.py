"""Security, WebAuthn FIDO2 step-up reauthentication, and air-gapped SBOM audit routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from evidence_coverage.enterprise_kms_airgap import (
    PKCS11HSMBridge,
    WebAuthnStepUpManager,
    generate_cyclonedx_sbom_from_uv_lock,
)
from fastapi import APIRouter
from fastapi.responses import JSONResponse


def build_security_audit_router(
    *,
    ok_fn: Callable[[str, Any, Any], dict[str, Any]],
    abstain_fn: Callable[[str, Any, str], dict[str, Any]],
) -> APIRouter:
    """Create APIRouter for WebAuthn step-up reauth and CycloneDX air-gap SBOM audit."""
    router = APIRouter(tags=["security-audit"])
    webauthn_mgr = WebAuthnStepUpManager()

    @router.post("/auth/webauthn/reauth/options")
    def webauthn_reauth_options_endpoint(body: dict[str, Any]) -> JSONResponse:
        user_id = str(body.get("user_id") or "cve-reviewer").strip()
        reg = body.get("register_credential")
        if isinstance(reg, dict) and reg.get("credential_id") and reg.get("public_key_pem"):
            webauthn_mgr.register_user_credential(
                user_id=str(reg.get("user_id") or user_id),
                credential_id=str(reg["credential_id"]),
                public_key_pem=str(reg["public_key_pem"]),
                transports=tuple(reg.get("transports") or ("internal",)),
            )
        try:
            opts = webauthn_mgr.generate_reauth_options(
                user_id=user_id, rp_id=str(body.get("rp_id") or "aeroregu.local")
            )
        except ValueError as exc:
            return JSONResponse(
                abstain_fn("webauthn_reauth@1.0.0", {"user_id": user_id}, str(exc)),
                status_code=404,
            )
        return JSONResponse(ok_fn("webauthn_reauth@1.0.0", {"user_id": user_id}, opts))

    @router.post("/auth/webauthn/reauth/verify")
    def webauthn_reauth_verify_endpoint(body: dict[str, Any]) -> JSONResponse:
        active_user = str(body.get("user_id") or "cve-reviewer").strip()
        cred_id = str(body.get("id") or body.get("credential_id") or "").strip()
        challenge = str(body.get("challenge") or "").strip()
        sig_b64 = str(
            body.get("signature_b64") or (body.get("response") or {}).get("signature") or ""
        ).strip()
        ver = webauthn_mgr.verify_reauth_assertion(
            active_user_id=active_user,
            credential_id=cred_id,
            challenge=challenge,
            signature_b64=sig_b64,
        )
        if not ver.get("verified"):
            return JSONResponse(
                abstain_fn(
                    "webauthn_reauth@1.0.0",
                    {"user_id": active_user, "rpId": ver.get("rpId")},
                    str(ver.get("reason")),
                ),
                status_code=int(ver.get("status_code") or 401),
            )
        return JSONResponse(ok_fn("webauthn_reauth@1.0.0", {"user_id": active_user}, ver))

    @router.post("/security/sbom-airgap-audit")
    def security_sbom_airgap_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_coverage.cluster_readiness import verify_cluster_infra_manifests
        from evidence_kernel.paths import repo_root as _repo_root

        root = _repo_root()
        signer = PKCS11HSMBridge() if bool(body.get("sign_with_hsm", True)) else None
        sbom_res = generate_cyclonedx_sbom_from_uv_lock(
            root,
            offline_cve_advisories=body.get("offline_cve_advisories"),
            sign_backend=signer,
        )
        cluster_res = verify_cluster_infra_manifests(root)
        return JSONResponse(
            ok_fn(
                "sbom_airgap_audit@1.0.0",
                {},
                {
                    "bom_format": sbom_res["bom_format"],
                    "spec_version": sbom_res["spec_version"],
                    "component_count": sbom_res["component_count"],
                    "cve_finding_count": sbom_res["cve_finding_count"],
                    "cve_findings": sbom_res["cve_findings"],
                    "airgap_clean": sbom_res["airgap_clean"],
                    "sbom_sha256": sbom_res["sbom_sha256"],
                    "dsse_signed": sbom_res["dsse_envelope"] is not None,
                    "backend_mode": signer.backend_mode if signer is not None else "unsigned",
                    "cluster_verified": cluster_res["verified"],
                    "cluster_checks": cluster_res["checks"],
                },
            )
        )

    return router
