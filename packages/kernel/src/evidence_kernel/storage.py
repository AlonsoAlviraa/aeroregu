"""Content-addressed object blob storage (local filesystem and AWS SigV4 S3/Blob)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class BlobStoreError(ValueError):
    """Raised when blob validation, integrity verification, or remote transport fails."""


class ObjectBlobStore(Protocol):
    backend_name: str

    def put_blob(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
    ) -> dict[str, Any]: ...

    def get_blob(self, sha256_hex: str) -> bytes: ...

    def head_blob(self, sha256_hex: str) -> dict[str, Any] | None: ...

    def list_blobs(self, *, limit: int = 100) -> list[dict[str, Any]]: ...


def _validate_sha256(sha256_hex: str) -> str:
    cleaned = str(sha256_hex).strip().lower()
    if not _SHA256_RE.fullmatch(cleaned):
        raise BlobStoreError("invalid_sha256_digest")
    return cleaned


def _clean_filename(filename: str) -> str:
    leaf = Path(str(filename or "artifact.bin")).name
    cleaned = _SAFE_FILENAME_RE.sub("_", leaf).strip("._")
    return cleaned[:120] or "artifact.bin"


@dataclass
class LocalFilesystemBlobStore:
    """Content-addressed SHA-256 local disk blob store (development and fallback)."""

    root: Path
    backend_name: str = "local_fs"

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        digest = _validate_sha256(digest)
        shard_dir = self.root / digest[:2]
        candidate = (shard_dir / digest).resolve()
        if self.root not in candidate.parents:
            raise BlobStoreError("path_traversal_rejected")
        return candidate

    def _meta_path(self, digest: str) -> Path:
        return self._blob_path(digest).with_suffix(".meta.json")

    def put_blob(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
    ) -> dict[str, Any]:
        if not isinstance(data, (bytes, bytearray)):
            raise BlobStoreError("blob_must_be_bytes")
        raw = bytes(data)
        digest = hashlib.sha256(raw).hexdigest()
        target = self._blob_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            tmp_path = target.with_suffix(".tmp")
            tmp_path.write_bytes(raw)
            tmp_path.replace(target)
        meta = {
            "sha256": digest,
            "size_bytes": len(raw),
            "content_type": str(content_type or "application/octet-stream"),
            "filename": _clean_filename(filename),
            "backend": self.backend_name,
            "uri": f"blob://local/{digest}",
            "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        meta_path = self._meta_path(digest)
        if not meta_path.is_file():
            meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        else:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta

    def get_blob(self, sha256_hex: str) -> bytes:
        digest = _validate_sha256(sha256_hex)
        target = self._blob_path(digest)
        if not target.is_file():
            raise FileNotFoundError(f"blob_not_found:{digest}")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise BlobStoreError("blob_integrity_mismatch")
        return raw

    def head_blob(self, sha256_hex: str) -> dict[str, Any] | None:
        digest = _validate_sha256(sha256_hex)
        target = self._blob_path(digest)
        if not target.is_file():
            return None
        meta_path = self._meta_path(digest)
        if meta_path.is_file():
            return dict(json.loads(meta_path.read_text(encoding="utf-8")))
        return {
            "sha256": digest,
            "size_bytes": target.stat().st_size,
            "content_type": "application/octet-stream",
            "filename": "artifact.bin",
            "backend": self.backend_name,
            "uri": f"blob://local/{digest}",
        }

    def list_blobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        items: list[dict[str, Any]] = []
        for meta_file in sorted(self.root.rglob("*.meta.json")):
            try:
                items.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except Exception:
                continue
            if len(items) >= capped:
                break
        return items


def _sign_hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sigv4_headers(
    *,
    method: str,
    url: str,
    region: str,
    access_key: str,
    secret_key: str,
    payload: bytes,
    extra_headers: dict[str, str] | None = None,
    service: str = "s3",
    now: datetime | None = None,
) -> dict[str, str]:
    """Generate AWS Signature Version 4 authorization headers."""
    ts = now or datetime.now(UTC)
    amz_date = ts.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = ts.strftime("%Y%m%d")
    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = quote(parsed.path or "/", safe="/-_.~")
    payload_hash = hashlib.sha256(payload).hexdigest()

    headers: dict[str, str] = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    for k, v in (extra_headers or {}).items():
        headers[k.lower().strip()] = str(v).strip()

    signed_keys = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed_keys)
    signed_headers = ";".join(signed_keys)
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            parsed.query or "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    k_date = _sign_hmac(f"AWS4{secret_key}".encode(), date_stamp)
    k_region = _sign_hmac(k_date, region)
    k_service = _sign_hmac(k_region, service)
    k_signing = _sign_hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        **{k: v for k, v in headers.items() if k != "host"},
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }


class S3CompatibleBlobStore:
    """S3 / Azure Blob Gateway compatible store signed via AWS SigV4 over HTTP."""

    backend_name: str = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "eu-west-1",
        prefix: str = "evidence-blobs",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        cleaned_endpoint = str(endpoint).rstrip("/")
        parsed = urlparse(cleaned_endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BlobStoreError("invalid_s3_endpoint")
        cleaned_bucket = re.sub(r"[^a-z0-9.-]", "", str(bucket).strip().lower())
        if not cleaned_bucket:
            raise BlobStoreError("invalid_s3_bucket")
        if not access_key or not secret_key:
            raise BlobStoreError("missing_s3_credentials")
        self.endpoint = cleaned_endpoint
        self.bucket = cleaned_bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.prefix = prefix.strip("/")
        self._client = httpx.Client(transport=transport, timeout=timeout)

    def _object_url(self, digest: str) -> str:
        digest = _validate_sha256(digest)
        key = f"{self.prefix}/{digest[:2]}/{digest}" if self.prefix else f"{digest[:2]}/{digest}"
        return f"{self.endpoint}/{self.bucket}/{key}"

    def put_blob(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
    ) -> dict[str, Any]:
        raw = bytes(data)
        digest = hashlib.sha256(raw).hexdigest()
        url = self._object_url(digest)
        clean_name = _clean_filename(filename)
        extra = {
            "content-type": str(content_type or "application/octet-stream"),
            "x-amz-meta-filename": clean_name,
            "x-amz-meta-sha256": digest,
        }
        headers = _sigv4_headers(
            method="PUT",
            url=url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=raw,
            extra_headers=extra,
        )
        resp = self._client.put(url, content=raw, headers=headers)
        if resp.status_code not in {200, 201, 204}:
            raise BlobStoreError(f"s3_put_failed:{resp.status_code}")
        return {
            "sha256": digest,
            "size_bytes": len(raw),
            "content_type": extra["content-type"],
            "filename": clean_name,
            "backend": self.backend_name,
            "uri": f"s3://{self.bucket}/{self.prefix}/{digest[:2]}/{digest}"
            if self.prefix
            else f"s3://{self.bucket}/{digest[:2]}/{digest}",
            "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def get_blob(self, sha256_hex: str) -> bytes:
        digest = _validate_sha256(sha256_hex)
        url = self._object_url(digest)
        headers = _sigv4_headers(
            method="GET",
            url=url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=b"",
        )
        resp = self._client.get(url, headers=headers)
        if resp.status_code == 404:
            raise FileNotFoundError(f"blob_not_found:{digest}")
        if resp.status_code != 200:
            raise BlobStoreError(f"s3_get_failed:{resp.status_code}")
        raw = resp.content
        if hashlib.sha256(raw).hexdigest() != digest:
            raise BlobStoreError("blob_integrity_mismatch")
        return raw

    def head_blob(self, sha256_hex: str) -> dict[str, Any] | None:
        digest = _validate_sha256(sha256_hex)
        url = self._object_url(digest)
        headers = _sigv4_headers(
            method="HEAD",
            url=url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=b"",
        )
        resp = self._client.head(url, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BlobStoreError(f"s3_head_failed:{resp.status_code}")
        return {
            "sha256": digest,
            "size_bytes": int(resp.headers.get("content-length") or 0),
            "content_type": resp.headers.get("content-type") or "application/octet-stream",
            "filename": resp.headers.get("x-amz-meta-filename") or "artifact.bin",
            "backend": self.backend_name,
            "uri": f"s3://{self.bucket}/{self.prefix}/{digest[:2]}/{digest}",
        }

    def list_blobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []


def open_blob_store(home: Path | None = None) -> ObjectBlobStore:
    """Open configured S3/Blob store or local content-addressed blob directory."""
    s3_endpoint = os.environ.get("EVIDENCE_S3_ENDPOINT", "").strip()
    s3_bucket = os.environ.get("EVIDENCE_S3_BUCKET", "").strip()
    s3_key = os.environ.get("EVIDENCE_S3_ACCESS_KEY", "").strip()
    s3_secret = os.environ.get("EVIDENCE_S3_SECRET_KEY", "").strip()
    if s3_endpoint and s3_bucket and s3_key and s3_secret:
        return S3CompatibleBlobStore(
            endpoint=s3_endpoint,
            bucket=s3_bucket,
            access_key=s3_key,
            secret_key=s3_secret,
            region=os.environ.get("EVIDENCE_S3_REGION", "eu-west-1").strip() or "eu-west-1",
            prefix=os.environ.get("EVIDENCE_S3_PREFIX", "evidence-blobs").strip(),
        )
    env_home = os.environ.get("EVIDENCE_HOME", "").strip()
    base = (
        Path(env_home)
        if env_home
        else (Path(home) if home is not None else Path.cwd() / ".evidence_home")
    )
    return LocalFilesystemBlobStore(base / "blobs")
