"""Corporate SSO verification (OIDC JWT/JWKS & SAML 2.0 XML via defusedxml) and RBAC."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import xml.etree.ElementTree as stdlib_et
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import defusedxml.ElementTree as SafeET
import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

VALID_ROLES = frozenset({"author", "cve", "admin", "human"})
_ROLE_PRIORITY = {"admin": 3, "cve": 2, "author": 1, "human": 0}


class SSOValidationError(ValueError):
    """Raised when an OIDC ID token or SAML assertion fails verification."""


def _b64url_decode(data: str) -> bytes:
    rem = len(data) % 4
    if rem:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def normalize_roles(claims_or_groups: list[str] | tuple[str, ...] | str | None) -> str:
    """Map corporate IdP groups/roles strictly to canonical platform roles (least privilege)."""
    if not claims_or_groups:
        return "author"
    items = (
        [claims_or_groups]
        if isinstance(claims_or_groups, str)
        else [str(x) for x in claims_or_groups]
    )
    mapped: list[str] = []
    for raw in items:
        low = raw.strip().lower()
        if low in {"admin", "evidence-admin", "platform-admin", "role:admin"}:
            mapped.append("admin")
        elif low in {
            "cve",
            "evidence-cve",
            "verification-engineer",
            "reviewer",
            "role:cve",
        }:
            mapped.append("cve")
        elif low in {"author", "evidence-author", "engineer", "role:author"}:
            mapped.append("author")
        elif low == "human":
            mapped.append("human")
    if not mapped:
        return "author"
    return max(mapped, key=lambda r: _ROLE_PRIORITY.get(r, 0))


def _jwk_to_public_key(jwk: dict[str, Any]) -> Any:
    kty = str(jwk.get("kty") or "").upper()
    if kty == "RSA":
        n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if kty == "EC" and str(jwk.get("crv") or "") == "P-256":
        x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    if kty == "OKP" and str(jwk.get("crv") or "") == "Ed25519":
        raw = _b64url_decode(jwk["x"])
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)
    if "x5c" in jwk and isinstance(jwk["x5c"], list) and jwk["x5c"]:
        cert_der = base64.b64decode(jwk["x5c"][0])
        cert = x509.load_der_x509_certificate(cert_der)
        return cert.public_key()
    raise SSOValidationError("unsupported_jwk_key_type")


def _jose_ec_sig_to_der(raw_sig: bytes) -> bytes:
    if len(raw_sig) != 64:
        raise SSOValidationError("invalid_es256_signature_length")
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    r = int.from_bytes(raw_sig[:32], "big")
    s = int.from_bytes(raw_sig[32:], "big")
    return encode_dss_signature(r, s)


@dataclass
class OIDCConfig:
    provider_name: str  # e.g. "entra_id" or "okta"
    issuer: str
    audience: str
    jwks: dict[str, Any] | None = None
    jwks_uri: str | None = None
    hs256_secret: str | None = None
    clock_skew_seconds: int = 60
    group_role_map: dict[str, str] | None = None


class OIDCVerifier:
    """Stateless OIDC ID Token verifier supporting RS256, ES256, EdDSA, and HS256."""

    def __init__(
        self,
        config: OIDCConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    def _load_jwks(self) -> list[dict[str, Any]]:
        if self.config.jwks is not None:
            return list(self.config.jwks.get("keys") or [])
        if not self.config.jwks_uri:
            return []
        with httpx.Client(transport=self._transport, timeout=8.0) as client:
            resp = client.get(self.config.jwks_uri)
            if resp.status_code != 200:
                raise SSOValidationError(f"jwks_fetch_failed:{resp.status_code}")
            return list(resp.json().get("keys") or [])

    def verify_id_token(
        self,
        id_token: str,
        *,
        expected_nonce: str | None = None,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        parts = str(id_token or "").split(".")
        if len(parts) != 3:
            raise SSOValidationError("malformed_jwt")
        hdr_b64, pay_b64, sig_b64 = parts
        try:
            header = json.loads(_b64url_decode(hdr_b64))
            claims = json.loads(_b64url_decode(pay_b64))
            signature = _b64url_decode(sig_b64)
        except Exception as exc:
            raise SSOValidationError("invalid_jwt_encoding") from exc

        alg = str(header.get("alg") or "")
        if alg in {"none", ""}:
            raise SSOValidationError("unsigned_jwt_rejected")
        signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")

        if alg == "HS256":
            if not self.config.hs256_secret:
                raise SSOValidationError("hs256_not_configured")
            expected_mac = hmac.new(
                self.config.hs256_secret.encode("utf-8"), signing_input, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(expected_mac, signature):
                raise SSOValidationError("invalid_jwt_signature")
        elif alg in {"RS256", "ES256", "EdDSA"}:
            keys = self._load_jwks()
            kid = header.get("kid")
            candidates = [k for k in keys if not kid or k.get("kid") == kid]
            if not candidates:
                raise SSOValidationError("matching_jwk_not_found")
            verified = False
            for jwk in candidates:
                try:
                    pub = _jwk_to_public_key(jwk)
                    if alg == "RS256":
                        pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
                    elif alg == "ES256":
                        pub.verify(
                            _jose_ec_sig_to_der(signature),
                            signing_input,
                            ec.ECDSA(hashes.SHA256()),
                        )
                    elif alg == "EdDSA":
                        pub.verify(signature, signing_input)
                    verified = True
                    break
                except (InvalidSignature, SSOValidationError, TypeError, ValueError):
                    continue
            if not verified:
                raise SSOValidationError("invalid_jwt_signature")
        else:
            raise SSOValidationError(f"unsupported_jwt_alg:{alg}")

        now = int(now_ts if now_ts is not None else time.time())
        skew = self.config.clock_skew_seconds
        if str(claims.get("iss") or "").rstrip("/") != self.config.issuer.rstrip("/"):
            raise SSOValidationError("issuer_mismatch")
        aud = claims.get("aud")
        if isinstance(aud, list):
            if self.config.audience not in aud:
                raise SSOValidationError("audience_mismatch")
        elif aud != self.config.audience:
            raise SSOValidationError("audience_mismatch")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or int(exp) + skew < now:
            raise SSOValidationError("token_expired")
        nbf = claims.get("nbf")
        if isinstance(nbf, (int, float)) and int(nbf) - skew > now:
            raise SSOValidationError("token_not_yet_valid")
        if expected_nonce is not None and claims.get("nonce") != expected_nonce:
            raise SSOValidationError("nonce_mismatch")

        actor_id = str(
            claims.get("preferred_username") or claims.get("email") or claims.get("sub") or ""
        ).strip()
        if not actor_id:
            raise SSOValidationError("missing_subject")

        raw_roles: list[str] = []
        for field in ("roles", "groups", "role"):
            val = claims.get(field)
            if isinstance(val, list):
                raw_roles.extend(str(x) for x in val)
            elif isinstance(val, str) and val.strip():
                raw_roles.append(val)
        if self.config.group_role_map:
            mapped_from_cfg = [
                self.config.group_role_map[r] for r in raw_roles if r in self.config.group_role_map
            ]
            raw_roles.extend(mapped_from_cfg)

        role = normalize_roles(raw_roles)
        return {
            "provider": self.config.provider_name,
            "protocol": "oidc",
            "actor_id": actor_id,
            "role": role,
            "raw_roles": raw_roles,
            "sub": str(claims.get("sub") or actor_id),
            "email": str(claims.get("email") or ""),
            "claims": claims,
        }


_SAML_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


def _parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_xml_bytes(elem: stdlib_et.Element) -> bytes:
    xml_text = stdlib_et.tostring(elem, encoding="unicode")
    canon = stdlib_et.canonicalize(xml_text, with_comments=False)
    return canon.encode("utf-8")


@dataclass
class SAMLConfig:
    provider_name: str  # e.g. "okta_saml" or "entra_saml"
    idp_entity_id: str
    sp_entity_id: str
    idp_certificate_pem: str
    clock_skew_seconds: int = 60


class SAML2Verifier:
    """XXE-safe SAML 2.0 Response/Assertion verifier using defusedxml and cryptography."""

    def __init__(self, config: SAMLConfig) -> None:
        self.config = config
        self._cert = x509.load_pem_x509_certificate(config.idp_certificate_pem.encode("utf-8"))

    def _verify_enveloped_signature(self, assertion: stdlib_et.Element) -> None:
        sig_el = assertion.find("ds:Signature", _SAML_NS)
        if sig_el is None:
            raise SSOValidationError("missing_saml_signature")
        signed_info = sig_el.find("ds:SignedInfo", _SAML_NS)
        sig_val_el = sig_el.find("ds:SignatureValue", _SAML_NS)
        if signed_info is None or sig_val_el is None or not (sig_val_el.text or "").strip():
            raise SSOValidationError("malformed_saml_signature")
        ref_el = signed_info.find("ds:Reference", _SAML_NS)
        digest_val_el = ref_el.find("ds:DigestValue", _SAML_NS) if ref_el is not None else None
        if digest_val_el is None or not (digest_val_el.text or "").strip():
            raise SSOValidationError("missing_saml_digest")

        # Verify assertion digest with ds:Signature temporarily detached
        idx = list(assertion).index(sig_el)
        assertion.remove(sig_el)
        try:
            canon_assertion = _canonical_xml_bytes(assertion)
        finally:
            assertion.insert(idx, sig_el)

        expected_digest = base64.b64encode(hashlib.sha256(canon_assertion).digest()).decode("ascii")
        if not hmac.compare_digest(expected_digest, digest_val_el.text.strip()):
            raise SSOValidationError("saml_digest_mismatch")

        # Verify X.509 RSA-SHA256 signature over canonicalized SignedInfo
        canon_signed_info = _canonical_xml_bytes(signed_info)
        raw_sig = base64.b64decode("".join(sig_val_el.text.split()))
        pub_key = self._cert.public_key()
        try:
            if isinstance(pub_key, rsa.RSAPublicKey):
                pub_key.verify(raw_sig, canon_signed_info, padding.PKCS1v15(), hashes.SHA256())
            elif isinstance(pub_key, ec.EllipticCurvePublicKey):
                pub_key.verify(raw_sig, canon_signed_info, ec.ECDSA(hashes.SHA256()))
            else:
                raise SSOValidationError("unsupported_saml_cert_key")
        except InvalidSignature as exc:
            raise SSOValidationError("invalid_saml_signature") from exc

    def verify_saml_response(
        self,
        saml_response_b64: str,
        *,
        now_dt: datetime | None = None,
    ) -> dict[str, Any]:
        try:
            xml_bytes = base64.b64decode(saml_response_b64.encode("ascii"))
            root = SafeET.fromstring(xml_bytes)
        except Exception as exc:
            raise SSOValidationError("invalid_saml_xml") from exc

        status_code = root.find("samlp:Status/samlp:StatusCode", _SAML_NS)
        if (
            status_code is None
            or status_code.attrib.get("Value") != "urn:oasis:names:tc:SAML:2.0:status:Success"
        ):
            raise SSOValidationError("saml_status_not_success")

        assertion = root.find("saml:Assertion", _SAML_NS)
        if assertion is None:
            raise SSOValidationError("missing_saml_assertion")

        self._verify_enveloped_signature(assertion)

        issuer_el = assertion.find("saml:Issuer", _SAML_NS)
        if issuer_el is None:
            issuer_el = root.find("saml:Issuer", _SAML_NS)
        if issuer_el is None or (issuer_el.text or "").strip() != self.config.idp_entity_id:
            raise SSOValidationError("saml_issuer_mismatch")

        now = now_dt or datetime.now(UTC)
        cond_el = assertion.find("saml:Conditions", _SAML_NS)
        if cond_el is not None:
            nb_raw = cond_el.attrib.get("NotBefore")
            noa_raw = cond_el.attrib.get("NotOnOrAfter")
            if (
                nb_raw
                and _parse_iso_utc(nb_raw).timestamp() - self.config.clock_skew_seconds
                > now.timestamp()
            ):
                raise SSOValidationError("saml_not_yet_valid")
            if (
                noa_raw
                and _parse_iso_utc(noa_raw).timestamp() + self.config.clock_skew_seconds
                <= now.timestamp()
            ):
                raise SSOValidationError("saml_assertion_expired")
            aud_els = cond_el.findall("saml:AudienceRestriction/saml:Audience", _SAML_NS)
            if aud_els:
                audiences = {(a.text or "").strip() for a in aud_els}
                if self.config.sp_entity_id not in audiences:
                    raise SSOValidationError("saml_audience_mismatch")

        name_id_el = assertion.find("saml:Subject/saml:NameID", _SAML_NS)
        actor_id = (name_id_el.text or "").strip() if name_id_el is not None else ""
        if not actor_id:
            raise SSOValidationError("missing_saml_name_id")

        raw_roles: list[str] = []
        for attr in assertion.findall("saml:AttributeStatement/saml:Attribute", _SAML_NS):
            attr_name = str(attr.attrib.get("Name") or "").lower()
            if "role" in attr_name or "group" in attr_name:
                for val_el in attr.findall("saml:AttributeValue", _SAML_NS):
                    if (val_el.text or "").strip():
                        raw_roles.append(val_el.text.strip())

        role = normalize_roles(raw_roles)
        return {
            "provider": self.config.provider_name,
            "protocol": "saml2",
            "actor_id": actor_id,
            "role": role,
            "raw_roles": raw_roles,
        }


def sign_saml_assertion_for_test(
    *,
    idp_entity_id: str,
    sp_entity_id: str,
    name_id: str,
    roles: list[str],
    private_key: rsa.RSAPrivateKey,
    not_before: str = "2026-01-01T00:00:00Z",
    not_on_or_after: str = "2027-01-01T00:00:00Z",
) -> str:
    """Build and sign a Base64-encoded SAML 2.0 Response XML for integration testing."""
    ns_samlp = _SAML_NS["samlp"]
    ns_saml = _SAML_NS["saml"]
    ns_ds = _SAML_NS["ds"]

    stdlib_et.register_namespace("samlp", ns_samlp)
    stdlib_et.register_namespace("saml", ns_saml)
    stdlib_et.register_namespace("ds", ns_ds)

    resp = stdlib_et.Element(f"{{{ns_samlp}}}Response", {"ID": "_resp1", "Version": "2.0"})
    status = stdlib_et.SubElement(resp, f"{{{ns_samlp}}}Status")
    stdlib_et.SubElement(
        status,
        f"{{{ns_samlp}}}StatusCode",
        {"Value": "urn:oasis:names:tc:SAML:2.0:status:Success"},
    )
    assertion = stdlib_et.SubElement(
        resp, f"{{{ns_saml}}}Assertion", {"ID": "_assert1", "Version": "2.0"}
    )
    issuer = stdlib_et.SubElement(assertion, f"{{{ns_saml}}}Issuer")
    issuer.text = idp_entity_id
    subj = stdlib_et.SubElement(assertion, f"{{{ns_saml}}}Subject")
    nid = stdlib_et.SubElement(subj, f"{{{ns_saml}}}NameID")
    nid.text = name_id
    cond = stdlib_et.SubElement(
        assertion,
        f"{{{ns_saml}}}Conditions",
        {"NotBefore": not_before, "NotOnOrAfter": not_on_or_after},
    )
    ar = stdlib_et.SubElement(cond, f"{{{ns_saml}}}AudienceRestriction")
    aud = stdlib_et.SubElement(ar, f"{{{ns_saml}}}Audience")
    aud.text = sp_entity_id

    attr_stmt = stdlib_et.SubElement(assertion, f"{{{ns_saml}}}AttributeStatement")
    role_attr = stdlib_et.SubElement(attr_stmt, f"{{{ns_saml}}}Attribute", {"Name": "roles"})
    for role in roles:
        av = stdlib_et.SubElement(role_attr, f"{{{ns_saml}}}AttributeValue")
        av.text = role

    digest_b64 = base64.b64encode(hashlib.sha256(_canonical_xml_bytes(assertion)).digest()).decode(
        "ascii"
    )
    sig_el = stdlib_et.SubElement(assertion, f"{{{ns_ds}}}Signature")
    si_el = stdlib_et.SubElement(sig_el, f"{{{ns_ds}}}SignedInfo")
    stdlib_et.SubElement(
        si_el,
        f"{{{ns_ds}}}CanonicalizationMethod",
        {"Algorithm": "http://www.w3.org/2001/10/xml-exc-c14n#"},
    )
    stdlib_et.SubElement(
        si_el,
        f"{{{ns_ds}}}SignatureMethod",
        {"Algorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"},
    )
    ref_el = stdlib_et.SubElement(si_el, f"{{{ns_ds}}}Reference", {"URI": "#_assert1"})
    stdlib_et.SubElement(
        ref_el,
        f"{{{ns_ds}}}DigestMethod",
        {"Algorithm": "http://www.w3.org/2001/04/xmlenc#sha256"},
    )
    dv_el = stdlib_et.SubElement(ref_el, f"{{{ns_ds}}}DigestValue")
    dv_el.text = digest_b64

    sig_bytes = private_key.sign(_canonical_xml_bytes(si_el), padding.PKCS1v15(), hashes.SHA256())
    sv_el = stdlib_et.SubElement(sig_el, f"{{{ns_ds}}}SignatureValue")
    sv_el.text = base64.b64encode(sig_bytes).decode("ascii")

    xml_bytes = stdlib_et.tostring(resp, encoding="utf-8", xml_declaration=True)
    return base64.b64encode(xml_bytes).decode("ascii")
