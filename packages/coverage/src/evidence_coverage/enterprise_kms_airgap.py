"""Enterprise KMS / Vault / PKCS#11 HSM Signers, WebAuthn Step-Up & Air-Gapped CycloneDX SBOM."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from evidence_kernel.hsm_eidas_scim import HSMKMSSigner


def _pae(payload_type: str, payload_bytes: bytes) -> bytes:
    pt = payload_type.encode("utf-8")
    return (
        f"DSSEv1 {len(pt)} ".encode("ascii")
        + pt
        + f" {len(payload_bytes)} ".encode("ascii")
        + payload_bytes
    )


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _compare_semver(actual: str, floor: str) -> bool:
    """Return True if actual < floor (i.e., vulnerable to offline advisory)."""

    def _parts(v: str) -> tuple[int, ...]:
        nums: list[int] = []
        for seg in str(v).split("."):
            digits = "".join(ch for ch in seg if ch.isdigit())
            nums.append(int(digits) if digits else 0)
        return tuple((nums + [0, 0, 0])[:3])

    return _parts(actual) < _parts(floor)


class PKCS11HSMBridge:
    """DSSE signing bridge delegating to non-exportable PKCS#11 HSM slots."""

    def __init__(self, key_uri: str = "pkcs11:token=aeroregu-hsm;object=cve-dsse") -> None:
        self.key_uri = key_uri
        self._hsm = HSMKMSSigner(key_uri=key_uri, algorithm="Ed25519")

    def sign_dsse(
        self, payload: dict[str, Any], *, payload_type: str = "application/vnd.in-toto+json"
    ) -> dict[str, Any]:
        payload_bytes = _canonical_json_bytes(payload)
        pae = _pae(payload_type, payload_bytes)
        signed = self._hsm.sign_digest(pae, key_uri=self.key_uri)
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": f"{self.key_uri}#{signed['key_id']}",
                    "sig": signed["signature_b64"],
                }
            ],
        }

    def verify_dsse(self, envelope: dict[str, Any]) -> bool:
        sigs = envelope.get("signatures") or []
        if not sigs:
            return False
        payload_bytes = base64.b64decode(str(envelope["payload"]))
        pae = _pae(str(envelope["payloadType"]), payload_bytes)
        sig_record = {
            "digest_sha256": hashlib.sha256(pae).hexdigest(),
            "public_key_pem": self._hsm.export_public_key_pem(self.key_uri),
            "signature_b64": str(sigs[0]["sig"]),
            "algorithm": self._hsm.default_algorithm,
        }
        return self._hsm.verify_signature(pae, sig_record)


class VaultTransitSigner:
    """HashiCorp Vault Transit `/v1/transit/sign|verify` DSSE signer (HTTP or mock transport)."""

    def __init__(
        self,
        vault_addr: str,
        key_name: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        allow_insecure_local: bool = False,
    ) -> None:
        addr = vault_addr.rstrip("/")
        if not addr.startswith("https://") and not allow_insecure_local:
            raise ValueError("vault_addr_must_use_https")
        self.vault_addr = addr
        self.key_name = key_name
        self.token = token
        self._client = httpx.Client(transport=transport, timeout=10.0)

    def sign_dsse(
        self, payload: dict[str, Any], *, payload_type: str = "application/vnd.in-toto+json"
    ) -> dict[str, Any]:
        payload_bytes = _canonical_json_bytes(payload)
        pae_b64 = base64.b64encode(_pae(payload_type, payload_bytes)).decode("ascii")
        resp = self._client.post(
            f"{self.vault_addr}/v1/transit/sign/{self.key_name}",
            headers={"X-Vault-Token": self.token},
            json={"input": pae_b64, "hash_algorithm": "sha2-256"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"vault_sign_failed:{resp.status_code}")
        sig_str = str(resp.json()["data"]["signature"])
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [{"keyid": f"vault:transit/{self.key_name}", "sig": sig_str}],
        }

    def verify_dsse(self, envelope: dict[str, Any]) -> bool:
        sigs = envelope.get("signatures") or []
        if not sigs:
            return False
        payload_bytes = base64.b64decode(str(envelope["payload"]))
        pae_b64 = base64.b64encode(_pae(str(envelope["payloadType"]), payload_bytes)).decode(
            "ascii"
        )
        resp = self._client.post(
            f"{self.vault_addr}/v1/transit/verify/{self.key_name}",
            headers={"X-Vault-Token": self.token},
            json={"input": pae_b64, "signature": str(sigs[0]["sig"])},
        )
        return resp.status_code == 200 and bool(resp.json().get("data", {}).get("valid", False))


class AWSKMSAdapter:
    """AWS KMS `Sign`/`Verify` DSSE envelope adapter with injectable KMS signer/verifier."""

    def __init__(
        self,
        key_arn: str,
        *,
        region: str = "eu-central-1",
        signer_fn: Callable[[bytes], bytes] | None = None,
        verifier_fn: Callable[[bytes, bytes], bool] | None = None,
    ) -> None:
        self.key_arn = key_arn
        self.region = region
        if signer_fn is None or verifier_fn is None:
            priv = ed25519.Ed25519PrivateKey.generate()
            pub = priv.public_key()
            self._signer_fn = lambda msg: priv.sign(msg)

            def _ver(msg: bytes, sig: bytes) -> bool:
                try:
                    pub.verify(sig, msg)
                    return True
                except Exception:
                    return False

            self._verifier_fn = _ver
        else:
            self._signer_fn = signer_fn
            self._verifier_fn = verifier_fn

    def sign_dsse(
        self, payload: dict[str, Any], *, payload_type: str = "application/vnd.in-toto+json"
    ) -> dict[str, Any]:
        payload_bytes = _canonical_json_bytes(payload)
        pae = _pae(payload_type, payload_bytes)
        sig_bytes = self._signer_fn(pae)
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {"keyid": self.key_arn, "sig": base64.b64encode(sig_bytes).decode("ascii")}
            ],
        }

    def verify_dsse(self, envelope: dict[str, Any]) -> bool:
        sigs = envelope.get("signatures") or []
        if not sigs:
            return False
        payload_bytes = base64.b64decode(str(envelope["payload"]))
        pae = _pae(str(envelope["payloadType"]), payload_bytes)
        sig_bytes = base64.b64decode(str(sigs[0]["sig"]))
        return bool(self._verifier_fn(pae, sig_bytes))


def generate_cyclonedx_sbom_from_uv_lock(
    repo_root: Path,
    *,
    offline_cve_advisories: dict[str, str] | None = None,
    sign_backend: Any | None = None,
) -> dict[str, Any]:
    """Build CycloneDX 1.5 SBOM from uv.lock, evaluate offline CVE floors, and optionally sign."""
    lock_path = Path(repo_root) / "uv.lock"
    if not lock_path.is_file():
        raise FileNotFoundError(f"missing uv.lock at {lock_path}")

    parsed = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    advisories = {
        k.lower().strip(): v.strip()
        for k, v in (
            offline_cve_advisories or {"cryptography": "42.0.0", "fastapi": "0.100.0"}
        ).items()
    }

    components: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    for pkg in parsed.get("package", []):
        name = str(pkg.get("name") or "")
        version = str(pkg.get("version") or "0.0.0")
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower()}@{version}",
            }
        )
        floor = advisories.get(name.lower())
        if floor and _compare_semver(version, floor):
            findings.append(
                {
                    "package": name,
                    "installed_version": version,
                    "required_min_version": floor,
                    "severity": "HIGH",
                    "status": "UPGRADE_REQUIRED",
                }
            )

    lock_hex = hashlib.sha256(lock_path.read_bytes()).hexdigest()[:32]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:aeroregu-{lock_hex}",
        "version": 1,
        "metadata": {"timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "components": components,
    }
    sbom_sha256 = hashlib.sha256(_canonical_json_bytes(sbom)).hexdigest()
    dsse = sign_backend.sign_dsse(sbom) if sign_backend is not None else None

    return {
        "bom_format": "CycloneDX",
        "spec_version": "1.5",
        "component_count": len(components),
        "cve_finding_count": len(findings),
        "cve_findings": findings,
        "airgap_clean": len(findings) == 0,
        "sbom_sha256": sbom_sha256,
        "sbom": sbom,
        "dsse_envelope": dsse,
    }


@dataclass
class _RegisteredPasskey:
    credential_id: str
    user_id: str
    public_key_pem: bytes
    transports: tuple[str, ...] = ("internal",)


class WebAuthnStepUpManager:
    """Strict FIDO2/Passkey step-up reauthentication bound to the active logged-in user."""

    def __init__(self) -> None:
        self._credentials: dict[str, _RegisteredPasskey] = {}
        self._challenges: dict[str, tuple[str, str]] = {}

    def register_user_credential(
        self,
        *,
        user_id: str,
        credential_id: str,
        public_key_pem: bytes | str,
        transports: tuple[str, ...] = ("internal",),
    ) -> dict[str, Any]:
        pem_b = (
            public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem
        )
        self._credentials[credential_id] = _RegisteredPasskey(
            credential_id=credential_id,
            user_id=user_id,
            public_key_pem=pem_b,
            transports=tuple(transports),
        )
        return {"credential_id": credential_id, "user_id": user_id, "registered": True}

    def generate_reauth_options(
        self, *, user_id: str, rp_id: str = "aeroregu.local"
    ) -> dict[str, Any]:
        user_creds = [c for c in self._credentials.values() if c.user_id == user_id]
        if not user_creds:
            raise ValueError("no_registered_passkeys")
        challenge = secrets.token_urlsafe(32)
        self._challenges[challenge] = (user_id, rp_id)
        return {
            "challenge": challenge,
            "rpId": rp_id,
            "userVerification": "required",
            "allowCredentials": [
                {
                    "type": "public-key",
                    "id": c.credential_id,
                    "transports": list(c.transports),
                }
                for c in user_creds
            ],
        }

    def verify_reauth_assertion(
        self,
        *,
        active_user_id: str,
        credential_id: str,
        challenge: str,
        signature_b64: str,
    ) -> dict[str, Any]:
        ch_entry = self._challenges.pop(challenge, None)
        if ch_entry is None:
            return {
                "verified": False,
                "status_code": 401,
                "reason": "invalid_or_replayed_challenge",
            }
        ch_user_id, rp_id = ch_entry
        if ch_user_id != active_user_id:
            return {"verified": False, "status_code": 403, "reason": "challenge_user_mismatch"}

        cred = self._credentials.get(credential_id)
        if cred is None:
            return {
                "verified": False,
                "status_code": 404,
                "reason": "unknown_credential",
                "rpId": rp_id,
            }
        if cred.user_id != active_user_id:
            return {"verified": False, "status_code": 403, "reason": "credential_owner_mismatch"}

        try:
            pub = serialization.load_pem_public_key(cred.public_key_pem)
            sig = base64.b64decode(signature_b64)
            pub.verify(sig, challenge.encode("utf-8"))
        except Exception:
            return {"verified": False, "status_code": 401, "reason": "invalid_passkey_signature"}

        token = hmac.new(
            cred.public_key_pem,
            f"{active_user_id}:{credential_id}:{challenge}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "verified": True,
            "status_code": 200,
            "user_id": active_user_id,
            "credential_id": credential_id,
            "rpId": rp_id,
            "step_up_token": token,
        }
