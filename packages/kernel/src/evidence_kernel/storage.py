"""Content-addressed object blob storage (local FS and SigV4 S3/MinIO with WORM & SSE-KMS)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol
from urllib.parse import parse_qs, quote, urlparse

import httpx

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

WORMRetentionMode = Literal["COMPLIANCE", "GOVERNANCE"]


class BlobStoreError(ValueError):
    """Raised when blob validation, integrity verification, or remote transport fails."""


class StorageAccessDeniedError(PermissionError):
    """Raised on 403 AccessDenied when mutating or deleting WORM Object Lock protected blobs."""


@dataclass(frozen=True)
class S3ObjectLockPolicy:
    """S3 Object Lock (WORM) and SSE-KMS policy metadata."""

    mode: WORMRetentionMode = "COMPLIANCE"
    retain_until_iso: str = "2036-12-31T23:59:59Z"
    kms_key_id: str | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        ref = now or datetime.now(UTC)
        try:
            until = datetime.fromisoformat(self.retain_until_iso.replace("Z", "+00:00"))
        except ValueError:
            return True
        return until > ref


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


def _iter_stream_chunks(
    stream: Iterable[bytes] | BinaryIO | Path, chunk_size: int
) -> Iterable[bytes]:
    if isinstance(stream, Path):
        with stream.open("rb") as fh:
            while True:
                buf = fh.read(chunk_size)
                if not buf:
                    break
                yield buf
        return
    if hasattr(stream, "read"):
        reader = stream  # type: ignore[assignment]
        while True:
            buf = reader.read(chunk_size)
            if not buf:
                break
            yield bytes(buf)
        return
    buf_acc = bytearray()
    for chunk in stream:
        if not chunk:
            continue
        buf_acc.extend(chunk)
        while len(buf_acc) >= chunk_size:
            out = bytes(buf_acc[:chunk_size])
            del buf_acc[:chunk_size]
            yield out
    if buf_acc:
        yield bytes(buf_acc)


def _check_worm_lock(meta: dict[str, Any] | None, *, bypass_governance: bool = False) -> None:
    if not meta:
        return
    mode = str(meta.get("object_lock_mode") or "").upper()
    retain_until = str(meta.get("retain_until") or "")
    if not mode:
        return
    policy = S3ObjectLockPolicy(
        mode="GOVERNANCE" if mode == "GOVERNANCE" else "COMPLIANCE",
        retain_until_iso=retain_until or "2099-01-01T00:00:00Z",
    )
    if not policy.is_active():
        return
    if policy.mode == "GOVERNANCE" and bypass_governance:
        return
    raise StorageAccessDeniedError(
        f"403 AccessDenied: Object locked under {policy.mode} WORM retention until {retain_until}"
    )


@dataclass
class LocalFilesystemBlobStore:
    """Content-addressed SHA-256 local disk blob store with WORM & streaming multipart support."""

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
        retention: S3ObjectLockPolicy | None = None,
        kms_key_id: str | None = None,
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
        meta: dict[str, Any] = {
            "sha256": digest,
            "size_bytes": len(raw),
            "content_type": str(content_type or "application/octet-stream"),
            "filename": _clean_filename(filename),
            "backend": self.backend_name,
            "uri": f"blob://local/{digest}",
            "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        effective_kms = kms_key_id or (retention.kms_key_id if retention else None)
        if effective_kms:
            meta["sse_algorithm"] = "aws:kms"
            meta["kms_key_id"] = effective_kms
        if retention is not None:
            meta["object_lock_mode"] = retention.mode
            meta["retain_until"] = retention.retain_until_iso
        meta_path = self._meta_path(digest)
        if not meta_path.is_file():
            meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        else:
            existing = dict(json.loads(meta_path.read_text(encoding="utf-8")))
            if retention is not None and "object_lock_mode" not in existing:
                existing["object_lock_mode"] = retention.mode
                existing["retain_until"] = retention.retain_until_iso
                meta_path.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")
            meta = existing
        return meta

    def put_blob_multipart(
        self,
        stream: Iterable[bytes] | BinaryIO | Path,
        *,
        chunk_size: int = 8 * 1024 * 1024,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
        retention: S3ObjectLockPolicy | None = None,
        kms_key_id: str | None = None,
    ) -> dict[str, Any]:
        """Stream chunks to temporary storage, verify part SHA-256 checksums, and commit WORM."""
        tmp_dir = self.root / ".multipart"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        upload_id = secrets.token_hex(12)
        staging = tmp_dir / f"{upload_id}.part"
        total_hasher = hashlib.sha256()
        total_bytes = 0
        part_checksums: list[dict[str, Any]] = []
        part_no = 0
        try:
            with staging.open("wb") as fh:
                for chunk in _iter_stream_chunks(stream, max(65536, int(chunk_size))):
                    part_no += 1
                    part_sha = hashlib.sha256(chunk).hexdigest()
                    part_checksums.append(
                        {"part_number": part_no, "sha256": part_sha, "size_bytes": len(chunk)}
                    )
                    total_hasher.update(chunk)
                    fh.write(chunk)
                    total_bytes += len(chunk)
            digest = total_hasher.hexdigest()
            target = self._blob_path(digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                staging.replace(target)
            else:
                staging.unlink(missing_ok=True)
            effective_kms = kms_key_id or (retention.kms_key_id if retention else None)
            meta: dict[str, Any] = {
                "sha256": digest,
                "size_bytes": total_bytes,
                "content_type": str(content_type or "application/octet-stream"),
                "filename": _clean_filename(filename),
                "backend": self.backend_name,
                "uri": f"blob://local/{digest}",
                "upload_id": upload_id,
                "multipart": True,
                "part_count": len(part_checksums),
                "part_checksums": part_checksums,
                "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            if effective_kms:
                meta["sse_algorithm"] = "aws:kms"
                meta["kms_key_id"] = effective_kms
            if retention is not None:
                meta["object_lock_mode"] = retention.mode
                meta["retain_until"] = retention.retain_until_iso
            meta_path = self._meta_path(digest)
            if not meta_path.is_file():
                meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
            else:
                meta = dict(json.loads(meta_path.read_text(encoding="utf-8")))
            return meta
        finally:
            staging.unlink(missing_ok=True)

    def get_blob(self, sha256_hex: str) -> bytes:
        digest = _validate_sha256(sha256_hex)
        target = self._blob_path(digest)
        if not target.is_file():
            raise FileNotFoundError(f"blob_not_found:{digest}")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise BlobStoreError("blob_integrity_mismatch")
        return raw

    def verify_blob_stream(self, sha256_hex: str, *, chunk_size: int = 8 * 1024 * 1024) -> bool:
        digest = _validate_sha256(sha256_hex)
        target = self._blob_path(digest)
        if not target.is_file():
            raise FileNotFoundError(f"blob_not_found:{digest}")
        hasher = hashlib.sha256()
        with target.open("rb") as fh:
            while True:
                buf = fh.read(chunk_size)
                if not buf:
                    break
                hasher.update(buf)
        return hasher.hexdigest() == digest

    def delete_blob(self, sha256_hex: str, *, bypass_governance: bool = False) -> bool:
        digest = _validate_sha256(sha256_hex)
        meta = self.head_blob(digest)
        if meta is None:
            return False
        _check_worm_lock(meta, bypass_governance=bypass_governance)
        self._blob_path(digest).unlink(missing_ok=True)
        self._meta_path(digest).unlink(missing_ok=True)
        return True

    def overwrite_blob(
        self,
        sha256_hex: str,
        new_data: bytes,
        *,
        bypass_governance: bool = False,
    ) -> dict[str, Any]:
        digest = _validate_sha256(sha256_hex)
        meta = self.head_blob(digest)
        _check_worm_lock(meta, bypass_governance=bypass_governance)
        target = self._blob_path(digest)
        target.write_bytes(new_data)
        return meta or {}

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


class LocalS3WORMTransport(httpx.BaseTransport):
    """Disk-backed S3/MinIO HTTP transport supporting Multipart, SSE-KMS & Object Lock WORM."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._uploads: dict[str, dict[str, Any]] = {}
        self.request_log: list[dict[str, str]] = []

    def _safe_key_dir(self, path_str: str) -> Path:
        clean = path_str.strip("/").replace("..", "_")
        target = (self.root / "objects" / clean).resolve()
        obj_root = (self.root / "objects").resolve()
        if obj_root not in target.parents and obj_root != target:
            raise BlobStoreError("invalid_s3_key")
        return target

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("AWS4-HMAC-SHA256 "):
            return httpx.Response(403, json={"code": "AccessDenied", "message": "Missing SigV4"})

        parsed = urlparse(str(request.url))
        qs = parse_qs(parsed.query, keep_blank_values=True)
        key = parsed.path
        self.request_log.append({"method": request.method, "path": key, "query": parsed.query})

        # 1) Multipart initiate: POST /{bucket}/{key}?uploads
        if request.method == "POST" and "uploads" in qs:
            uid = secrets.token_hex(12)
            up_dir = self.root / "uploads" / uid
            up_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._uploads[uid] = {
                    "key": key,
                    "headers": dict(request.headers),
                    "parts": {},
                    "dir": up_dir,
                }
            return httpx.Response(200, json={"upload_id": uid})

        # 2) Multipart part upload: PUT /{bucket}/{key}?partNumber=N&uploadId=UID
        if request.method == "PUT" and "partNumber" in qs and "uploadId" in qs:
            uid = qs["uploadId"][0]
            part_no = int(qs["partNumber"][0])
            with self._lock:
                up = self._uploads.get(uid)
            if up is None:
                return httpx.Response(404, json={"code": "NoSuchUpload"})
            chunk = request.content
            actual_sha = hashlib.sha256(chunk).hexdigest()
            expected_sha = request.headers.get("x-amz-checksum-sha256")
            if expected_sha and actual_sha != expected_sha.lower():
                return httpx.Response(400, json={"code": "BadDigest"})
            part_path = Path(up["dir"]) / f"part_{part_no:05d}"
            part_path.write_bytes(chunk)
            with self._lock:
                up["parts"][part_no] = {
                    "path": part_path,
                    "sha256": actual_sha,
                    "size_bytes": len(chunk),
                }
            return httpx.Response(200, headers={"ETag": f'"{actual_sha}"'})

        # 3) Multipart complete: POST /{bucket}/{key}?uploadId=UID
        if request.method == "POST" and "uploadId" in qs and "uploads" not in qs:
            uid = qs["uploadId"][0]
            with self._lock:
                up = self._uploads.pop(uid, None)
            if up is None:
                return httpx.Response(404, json={"code": "NoSuchUpload"})
            body_info = json.loads(request.content.decode("utf-8")) if request.content else {}
            final_key = str(body_info.get("final_path") or up["key"])
            obj_file = self._safe_key_dir(final_key)
            meta_file = Path(f"{obj_file}.meta.json")
            if meta_file.is_file():
                existing_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                try:
                    _check_worm_lock(existing_meta, bypass_governance=False)
                except StorageAccessDeniedError as exc:
                    shutil.rmtree(up["dir"], ignore_errors=True)
                    return httpx.Response(403, json={"code": "AccessDenied", "message": str(exc)})

            obj_file.parent.mkdir(parents=True, exist_ok=True)
            hasher = hashlib.sha256()
            total_size = 0
            part_records: list[dict[str, Any]] = []
            tmp_out = obj_file.with_suffix(".tmp")
            with tmp_out.open("wb") as out_fh:
                for pno in sorted(up["parts"]):
                    pinfo = up["parts"][pno]
                    with Path(pinfo["path"]).open("rb") as in_fh:
                        while True:
                            buf = in_fh.read(1024 * 1024)
                            if not buf:
                                break
                            hasher.update(buf)
                            out_fh.write(buf)
                            total_size += len(buf)
                    part_records.append(
                        {
                            "part_number": pno,
                            "sha256": pinfo["sha256"],
                            "size_bytes": pinfo["size_bytes"],
                        }
                    )
            tmp_out.replace(obj_file)
            shutil.rmtree(up["dir"], ignore_errors=True)
            final_sha = hasher.hexdigest()
            hdrs = up["headers"]
            meta = {
                "sha256": final_sha,
                "size_bytes": total_size,
                "content-type": hdrs.get("content-type", "application/octet-stream"),
                "x-amz-meta-filename": hdrs.get("x-amz-meta-filename", "artifact.bin"),
                "object_lock_mode": request.headers.get("x-amz-object-lock-mode")
                or hdrs.get("x-amz-object-lock-mode", ""),
                "retain_until": request.headers.get("x-amz-object-lock-retain-until-date")
                or hdrs.get("x-amz-object-lock-retain-until-date", ""),
                "sse_algorithm": request.headers.get("x-amz-server-side-encryption")
                or hdrs.get("x-amz-server-side-encryption", ""),
                "kms_key_id": request.headers.get("x-amz-server-side-encryption-aws-kms-key-id")
                or hdrs.get("x-amz-server-side-encryption-aws-kms-key-id", ""),
                "part_checksums": part_records,
                "upload_id": uid,
            }
            meta_file.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
            return httpx.Response(
                200,
                json={
                    "sha256": final_sha,
                    "size_bytes": total_size,
                    "part_count": len(part_records),
                },
            )

        obj_file = self._safe_key_dir(key)
        meta_file = Path(f"{obj_file}.meta.json")

        if request.method == "PUT":
            if meta_file.is_file():
                existing_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                try:
                    _check_worm_lock(existing_meta, bypass_governance=False)
                except StorageAccessDeniedError as exc:
                    return httpx.Response(403, json={"code": "AccessDenied", "message": str(exc)})
            obj_file.parent.mkdir(parents=True, exist_ok=True)
            raw = request.content
            obj_file.write_bytes(raw)
            meta = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "content-type": request.headers.get("content-type", "application/octet-stream"),
                "x-amz-meta-filename": request.headers.get("x-amz-meta-filename", "artifact.bin"),
                "object_lock_mode": request.headers.get("x-amz-object-lock-mode", ""),
                "retain_until": request.headers.get("x-amz-object-lock-retain-until-date", ""),
                "sse_algorithm": request.headers.get("x-amz-server-side-encryption", ""),
                "kms_key_id": request.headers.get(
                    "x-amz-server-side-encryption-aws-kms-key-id", ""
                ),
            }
            meta_file.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
            return httpx.Response(200)

        if request.method == "GET":
            if not obj_file.is_file():
                return httpx.Response(404)
            return httpx.Response(200, content=obj_file.read_bytes())

        if request.method == "HEAD":
            if not obj_file.is_file():
                return httpx.Response(404)
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            resp_headers = {
                "content-length": str(obj_file.stat().st_size),
                "content-type": meta.get("content-type", "application/octet-stream"),
                "x-amz-meta-filename": meta.get("x-amz-meta-filename", "artifact.bin"),
            }
            if meta.get("object_lock_mode"):
                resp_headers["x-amz-object-lock-mode"] = meta["object_lock_mode"]
            if meta.get("retain_until"):
                resp_headers["x-amz-object-lock-retain-until-date"] = meta["retain_until"]
            if meta.get("sse_algorithm"):
                resp_headers["x-amz-server-side-encryption"] = meta["sse_algorithm"]
            if meta.get("kms_key_id"):
                resp_headers["x-amz-server-side-encryption-aws-kms-key-id"] = meta["kms_key_id"]
            return httpx.Response(200, headers=resp_headers)

        if request.method == "DELETE":
            if not obj_file.is_file():
                return httpx.Response(404)
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            bypass = request.headers.get("x-amz-bypass-governance-retention", "").lower() == "true"
            try:
                _check_worm_lock(meta, bypass_governance=bypass)
            except StorageAccessDeniedError as exc:
                return httpx.Response(403, json={"code": "AccessDenied", "message": str(exc)})
            obj_file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            return httpx.Response(204)

        return httpx.Response(405)


class S3CompatibleBlobStore:
    """S3 / MinIO compatible store signed via AWS SigV4 with WORM, SSE-KMS & multipart."""

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
        timeout: float = 30.0,
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

    def _object_key(self, digest: str) -> str:
        return f"{self.prefix}/{digest[:2]}/{digest}" if self.prefix else f"{digest[:2]}/{digest}"

    def _object_url(self, digest: str) -> str:
        digest = _validate_sha256(digest)
        return f"{self.endpoint}/{self.bucket}/{self._object_key(digest)}"

    def put_blob(
        self,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
        retention: S3ObjectLockPolicy | None = None,
        kms_key_id: str | None = None,
    ) -> dict[str, Any]:
        raw = bytes(data)
        digest = hashlib.sha256(raw).hexdigest()
        url = self._object_url(digest)
        clean_name = _clean_filename(filename)
        extra: dict[str, str] = {
            "content-type": str(content_type or "application/octet-stream"),
            "x-amz-meta-filename": clean_name,
            "x-amz-meta-sha256": digest,
        }
        effective_kms = kms_key_id or (retention.kms_key_id if retention else None)
        if effective_kms:
            extra["x-amz-server-side-encryption"] = "aws:kms"
            extra["x-amz-server-side-encryption-aws-kms-key-id"] = effective_kms
        if retention is not None:
            extra["x-amz-object-lock-mode"] = retention.mode
            extra["x-amz-object-lock-retain-until-date"] = retention.retain_until_iso

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
        if resp.status_code == 403:
            raise StorageAccessDeniedError(f"403 AccessDenied: {resp.text}")
        if resp.status_code not in {200, 201, 204}:
            raise BlobStoreError(f"s3_put_failed:{resp.status_code}")
        out: dict[str, Any] = {
            "sha256": digest,
            "size_bytes": len(raw),
            "content_type": extra["content-type"],
            "filename": clean_name,
            "backend": self.backend_name,
            "uri": f"s3://{self.bucket}/{self._object_key(digest)}",
            "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if effective_kms:
            out["sse_algorithm"] = "aws:kms"
            out["kms_key_id"] = effective_kms
        if retention is not None:
            out["object_lock_mode"] = retention.mode
            out["retain_until"] = retention.retain_until_iso
        return out

    def put_blob_multipart(
        self,
        stream: Iterable[bytes] | BinaryIO | Path,
        *,
        chunk_size: int = 8 * 1024 * 1024,
        content_type: str = "application/octet-stream",
        filename: str = "artifact.bin",
        retention: S3ObjectLockPolicy | None = None,
        kms_key_id: str | None = None,
    ) -> dict[str, Any]:
        """Streaming S3 multipart upload with per-part SHA-256 checksums, SSE-KMS & WORM lock."""
        clean_name = _clean_filename(filename)
        staging_key = f"{self.prefix}/multipart/{secrets.token_hex(8)}"
        init_url = f"{self.endpoint}/{self.bucket}/{staging_key}?uploads="
        effective_kms = kms_key_id or (retention.kms_key_id if retention else None)
        init_extra: dict[str, str] = {
            "content-type": str(content_type or "application/octet-stream"),
            "x-amz-meta-filename": clean_name,
        }
        if effective_kms:
            init_extra["x-amz-server-side-encryption"] = "aws:kms"
            init_extra["x-amz-server-side-encryption-aws-kms-key-id"] = effective_kms
        if retention is not None:
            init_extra["x-amz-object-lock-mode"] = retention.mode
            init_extra["x-amz-object-lock-retain-until-date"] = retention.retain_until_iso

        init_headers = _sigv4_headers(
            method="POST",
            url=init_url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=b"",
            extra_headers=init_extra,
        )
        init_resp = self._client.post(init_url, content=b"", headers=init_headers)
        if init_resp.status_code not in {200, 201}:
            raise BlobStoreError(f"s3_multipart_init_failed:{init_resp.status_code}")
        upload_id = str(init_resp.json()["upload_id"])

        total_hasher = hashlib.sha256()
        total_bytes = 0
        part_checksums: list[dict[str, Any]] = []
        part_no = 0
        for chunk in _iter_stream_chunks(stream, max(65536, int(chunk_size))):
            part_no += 1
            part_sha = hashlib.sha256(chunk).hexdigest()
            part_url = (
                f"{self.endpoint}/{self.bucket}/{staging_key}"
                f"?partNumber={part_no}&uploadId={upload_id}"
            )
            part_headers = _sigv4_headers(
                method="PUT",
                url=part_url,
                region=self.region,
                access_key=self.access_key,
                secret_key=self.secret_key,
                payload=chunk,
                extra_headers={"x-amz-checksum-sha256": part_sha},
            )
            part_resp = self._client.put(part_url, content=chunk, headers=part_headers)
            if part_resp.status_code not in {200, 201}:
                raise BlobStoreError(f"s3_multipart_part_failed:{part_no}:{part_resp.status_code}")
            part_checksums.append(
                {"part_number": part_no, "sha256": part_sha, "size_bytes": len(chunk)}
            )
            total_hasher.update(chunk)
            total_bytes += len(chunk)

        final_digest = total_hasher.hexdigest()
        final_key = self._object_key(final_digest)
        complete_url = f"{self.endpoint}/{self.bucket}/{staging_key}?uploadId={upload_id}"
        complete_body = json.dumps(
            {
                "sha256": final_digest,
                "final_path": f"/{self.bucket}/{final_key}",
                "parts": part_checksums,
            },
            sort_keys=True,
        ).encode("utf-8")
        comp_extra = {"content-type": "application/json", "x-amz-meta-sha256": final_digest}
        if effective_kms:
            comp_extra["x-amz-server-side-encryption"] = "aws:kms"
            comp_extra["x-amz-server-side-encryption-aws-kms-key-id"] = effective_kms
        if retention is not None:
            comp_extra["x-amz-object-lock-mode"] = retention.mode
            comp_extra["x-amz-object-lock-retain-until-date"] = retention.retain_until_iso
        comp_headers = _sigv4_headers(
            method="POST",
            url=complete_url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=complete_body,
            extra_headers=comp_extra,
        )
        comp_resp = self._client.post(complete_url, content=complete_body, headers=comp_headers)
        if comp_resp.status_code == 403:
            raise StorageAccessDeniedError(f"403 AccessDenied: {comp_resp.text}")
        if comp_resp.status_code not in {200, 201}:
            raise BlobStoreError(f"s3_multipart_complete_failed:{comp_resp.status_code}")

        out: dict[str, Any] = {
            "sha256": final_digest,
            "size_bytes": total_bytes,
            "content_type": init_extra["content-type"],
            "filename": clean_name,
            "backend": self.backend_name,
            "uri": f"s3://{self.bucket}/{final_key}",
            "upload_id": upload_id,
            "multipart": True,
            "part_count": len(part_checksums),
            "part_checksums": part_checksums,
            "stored_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if effective_kms:
            out["sse_algorithm"] = "aws:kms"
            out["kms_key_id"] = effective_kms
        if retention is not None:
            out["object_lock_mode"] = retention.mode
            out["retain_until"] = retention.retain_until_iso
        return out

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
        if resp.status_code == 403:
            raise StorageAccessDeniedError(f"403 AccessDenied: {resp.text}")
        if resp.status_code != 200:
            raise BlobStoreError(f"s3_get_failed:{resp.status_code}")
        raw = resp.content
        if hashlib.sha256(raw).hexdigest() != digest:
            raise BlobStoreError("blob_integrity_mismatch")
        return raw

    def delete_blob(self, sha256_hex: str, *, bypass_governance: bool = False) -> bool:
        digest = _validate_sha256(sha256_hex)
        url = self._object_url(digest)
        extra: dict[str, str] = {}
        if bypass_governance:
            extra["x-amz-bypass-governance-retention"] = "true"
        headers = _sigv4_headers(
            method="DELETE",
            url=url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=b"",
            extra_headers=extra,
        )
        resp = self._client.delete(url, headers=headers)
        if resp.status_code == 403:
            raise StorageAccessDeniedError(
                "403 AccessDenied: Object is protected under S3 Object Lock WORM retention"
            )
        if resp.status_code == 404:
            return False
        if resp.status_code not in {200, 204}:
            raise BlobStoreError(f"s3_delete_failed:{resp.status_code}")
        return True

    def overwrite_blob(self, sha256_hex: str, new_data: bytes) -> dict[str, Any]:
        digest = _validate_sha256(sha256_hex)
        url = self._object_url(digest)
        raw = bytes(new_data)
        headers = _sigv4_headers(
            method="PUT",
            url=url,
            region=self.region,
            access_key=self.access_key,
            secret_key=self.secret_key,
            payload=raw,
        )
        resp = self._client.put(url, content=raw, headers=headers)
        if resp.status_code == 403:
            raise StorageAccessDeniedError(
                "403 AccessDenied: Overwrite rejected due to active S3 Object Lock WORM policy"
            )
        if resp.status_code not in {200, 201, 204}:
            raise BlobStoreError(f"s3_overwrite_failed:{resp.status_code}")
        return {"sha256": digest, "size_bytes": len(raw)}

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
        out: dict[str, Any] = {
            "sha256": digest,
            "size_bytes": int(resp.headers.get("content-length") or 0),
            "content_type": resp.headers.get("content-type") or "application/octet-stream",
            "filename": resp.headers.get("x-amz-meta-filename") or "artifact.bin",
            "backend": self.backend_name,
            "uri": f"s3://{self.bucket}/{self._object_key(digest)}",
        }
        if resp.headers.get("x-amz-object-lock-mode"):
            out["object_lock_mode"] = resp.headers["x-amz-object-lock-mode"]
        if resp.headers.get("x-amz-object-lock-retain-until-date"):
            out["retain_until"] = resp.headers["x-amz-object-lock-retain-until-date"]
        if resp.headers.get("x-amz-server-side-encryption"):
            out["sse_algorithm"] = resp.headers["x-amz-server-side-encryption"]
        if resp.headers.get("x-amz-server-side-encryption-aws-kms-key-id"):
            out["kms_key_id"] = resp.headers["x-amz-server-side-encryption-aws-kms-key-id"]
        return out

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
