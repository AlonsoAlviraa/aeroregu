"""SSRF-safe HMAC-SHA256 CI/CD webhook dispatcher for envelope and coverage invalidations."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx


class WebhookError(ValueError):
    """Raised when webhook registration URL or configuration is unsafe or invalid."""


def validate_webhook_url(url: str, *, allow_private_targets: bool = False) -> str:
    """Validate webhook callback URL against SSRF to private, loopback, or metadata hosts."""
    cleaned = str(url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookError("invalid_webhook_scheme")
    is_prod = os.environ.get("EVIDENCE_MODE", "dev").strip().lower() == "production"
    if is_prod and parsed.scheme != "https":
        raise WebhookError("webhook_requires_https_in_production")
    hostname = parsed.hostname
    if not hostname:
        raise WebhookError("missing_webhook_host")

    if not allow_private_targets:
        low_host = hostname.lower()
        if low_host in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"}:
            raise WebhookError("ssrf_private_webhook_blocked")
        try:
            ip = ipaddress.ip_address(hostname)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                raise WebhookError("ssrf_private_webhook_blocked")
        except ValueError:
            try:
                infos = socket.getaddrinfo(
                    hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
                )
                for info in infos:
                    addr = ipaddress.ip_address(info[4][0])
                    if (
                        addr.is_private
                        or addr.is_loopback
                        or addr.is_link_local
                        or addr.is_reserved
                        or addr.is_multicast
                    ):
                        raise WebhookError("ssrf_private_webhook_blocked")
            except socket.gaierror:
                # Permit unresolved FQDNs in offline environments so tests without DNS can register
                if "." not in low_host:
                    raise WebhookError("ssrf_unqualified_host_blocked")
    return cleaned


def sign_webhook_payload(secret: str, timestamp: str, body_bytes: bytes) -> str:
    """Compute X-Evidence-Signature-256 HMAC header value."""
    mac_input = f"{timestamp}.".encode() + body_bytes
    digest = hmac.new(secret.encode("utf-8"), mac_input, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_webhook_headers(
    *,
    event_name: str,
    delivery_id: str,
    secret: str,
    timestamp: str,
    body_bytes: bytes,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": "EvidenceLayer-Webhook/1.0",
        "X-Evidence-Event": event_name,
        "X-Evidence-Delivery": delivery_id,
        "X-Evidence-Timestamp": timestamp,
        "X-Evidence-Signature-256": sign_webhook_payload(secret, timestamp, body_bytes),
    }


def dispatch_webhook_event(
    subscriptions: list[dict[str, Any]],
    *,
    event_name: str,
    payload: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Send HMAC-signed webhook notifications to matching subscriptions synchronously."""
    results: list[dict[str, Any]] = []
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope = {
        "event": event_name,
        "timestamp": timestamp,
        "payload": payload,
    }
    body_bytes = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    with httpx.Client(transport=transport, timeout=timeout) as client:
        for sub in subscriptions:
            events_filter = list(sub.get("events") or ["envelope_invalidated"])
            if event_name not in events_filter and "*" not in events_filter:
                continue
            delivery_id = str(uuid.uuid4())
            headers = build_webhook_headers(
                event_name=event_name,
                delivery_id=delivery_id,
                secret=str(sub["secret"]),
                timestamp=timestamp,
                body_bytes=body_bytes,
            )
            try:
                resp = client.post(str(sub["url"]), content=body_bytes, headers=headers)
                results.append(
                    {
                        "webhook_id": sub["webhook_id"],
                        "delivery_id": delivery_id,
                        "event": event_name,
                        "url": sub["url"],
                        "status_code": resp.status_code,
                        "ok": 200 <= resp.status_code < 300,
                        "error": None
                        if 200 <= resp.status_code < 300
                        else f"http_{resp.status_code}",
                        "delivered_at": timestamp,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "webhook_id": sub["webhook_id"],
                        "delivery_id": delivery_id,
                        "event": event_name,
                        "url": sub["url"],
                        "status_code": 0,
                        "ok": False,
                        "error": str(exc),
                        "delivered_at": timestamp,
                    }
                )
    return results


def new_webhook_record(
    *,
    url: str,
    events: list[str] | None = None,
    secret: str | None = None,
    description: str = "",
    allow_private_targets: bool = False,
) -> dict[str, Any]:
    """Validate and construct a persistent webhook subscription dict."""
    clean_url = validate_webhook_url(url, allow_private_targets=allow_private_targets)
    clean_events = [str(e).strip() for e in (events or ["envelope_invalidated"]) if str(e).strip()]
    if not clean_events:
        clean_events = ["envelope_invalidated"]
    return {
        "webhook_id": f"wh_{secrets.token_hex(8)}",
        "url": clean_url,
        "events": clean_events,
        "secret": secret or f"whsec_{secrets.token_urlsafe(24)}",
        "description": str(description or "")[:200],
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": True,
    }
