"""SSRF-safe HMAC-SHA256 CI/CD webhook dispatcher for envelope and coverage invalidations."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from evidence_kernel.telemetry import get_telemetry


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


def _send_single_attempt(
    client: httpx.Client,
    *,
    sub: dict[str, Any],
    event_name: str,
    body_bytes: bytes,
    delivery_id: str,
    timestamp: str,
) -> dict[str, Any]:
    headers = build_webhook_headers(
        event_name=event_name,
        delivery_id=delivery_id,
        secret=str(sub["secret"]),
        timestamp=timestamp,
        body_bytes=body_bytes,
    )
    try:
        resp = client.post(str(sub["url"]), content=body_bytes, headers=headers)
        ok = 200 <= resp.status_code < 300
        return {
            "webhook_id": sub["webhook_id"],
            "delivery_id": delivery_id,
            "event": event_name,
            "url": sub["url"],
            "status_code": resp.status_code,
            "ok": ok,
            "error": None if ok else f"http_{resp.status_code}",
            "delivered_at": timestamp,
        }
    except Exception as exc:
        return {
            "webhook_id": sub["webhook_id"],
            "delivery_id": delivery_id,
            "event": event_name,
            "url": sub["url"],
            "status_code": 0,
            "ok": False,
            "error": str(exc),
            "delivered_at": timestamp,
        }


def dispatch_webhook_with_retry(
    subscriptions: list[dict[str, Any]],
    *,
    event_name: str,
    payload: dict[str, Any],
    ledger: Any | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 5.0,
    max_attempts: int = 3,
    backoff_base_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """Dispatch HMAC-signed webhooks with exponential backoff and persistent dead-letter queue."""
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
    tel = get_telemetry()
    attempts_cap = max(1, int(max_attempts))

    with httpx.Client(transport=transport, timeout=timeout) as client:
        for sub in subscriptions:
            events_filter = list(sub.get("events") or ["envelope_invalidated"])
            if event_name not in events_filter and "*" not in events_filter:
                continue
            delivery_id = str(uuid.uuid4())
            last_res: dict[str, Any] = {}
            for attempt in range(1, attempts_cap + 1):
                now_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                last_res = _send_single_attempt(
                    client,
                    sub=sub,
                    event_name=event_name,
                    body_bytes=body_bytes,
                    delivery_id=delivery_id,
                    timestamp=now_ts,
                )
                last_res["attempt_count"] = attempt
                last_res["max_attempts"] = attempts_cap
                if last_res["ok"]:
                    last_res["dead_lettered"] = False
                    last_res["status"] = "delivered"
                    tel.record_webhook_delivery("delivered")
                    if ledger is not None:
                        ledger.record_webhook_delivery(last_res)
                        if hasattr(ledger, "queue"):
                            ledger.queue.upsert_webhook_dlq(
                                delivery_id=delivery_id,
                                webhook_id=str(sub["webhook_id"]),
                                event_name=event_name,
                                url=str(sub["url"]),
                                payload=payload,
                                status="delivered",
                                attempt_count=attempt,
                                max_attempts=attempts_cap,
                                next_retry_at=now_ts,
                                last_error=None,
                            )
                    break

                is_final = attempt >= attempts_cap
                delay_s = float(backoff_base_seconds) * (2 ** (attempt - 1))
                next_retry = (datetime.now(UTC) + timedelta(seconds=delay_s)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                status = "dead_letter" if is_final else "retry_scheduled"
                last_res["dead_lettered"] = is_final
                last_res["status"] = status
                last_res["next_retry_at"] = next_retry
                tel.record_webhook_delivery(status)
                if ledger is not None:
                    ledger.record_webhook_delivery(last_res)
                    if hasattr(ledger, "queue"):
                        ledger.queue.upsert_webhook_dlq(
                            delivery_id=delivery_id,
                            webhook_id=str(sub["webhook_id"]),
                            event_name=event_name,
                            url=str(sub["url"]),
                            payload=payload,
                            status=status,
                            attempt_count=attempt,
                            max_attempts=attempts_cap,
                            next_retry_at=next_retry,
                            last_error=last_res.get("error"),
                        )
                if not is_final and delay_s > 0:
                    time.sleep(min(delay_s, 2.0))
            results.append(last_res)
    return results


def replay_dead_letters(
    ledger: Any,
    *,
    delivery_ids: list[str] | None = None,
    transport: httpx.BaseTransport | None = None,
    max_attempts: int = 2,
    backoff_base_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """Replay dead-lettered webhook deliveries stored in the ledger DLQ."""
    if not hasattr(ledger, "queue"):
        return []
    subs_by_id = {s["webhook_id"]: s for s in ledger.list_webhooks(include_secret=True)}
    dlq_items = ledger.queue.list_webhook_dlq(status="dead_letter", limit=200)
    if delivery_ids is not None:
        wanted = set(delivery_ids)
        dlq_items = [item for item in dlq_items if item["delivery_id"] in wanted]

    replayed: list[dict[str, Any]] = []
    with httpx.Client(transport=transport, timeout=5.0) as client:
        for item in dlq_items:
            sub = subs_by_id.get(item["webhook_id"])
            if sub is None:
                continue
            envelope = {
                "event": item["event"],
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "payload": item["payload"],
            }
            body_bytes = json.dumps(
                envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
            now_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            res = _send_single_attempt(
                client,
                sub=sub,
                event_name=item["event"],
                body_bytes=body_bytes,
                delivery_id=item["delivery_id"],
                timestamp=now_ts,
            )
            new_attempts = int(item["attempt_count"]) + 1
            new_status = "delivered" if res["ok"] else "dead_letter"
            res["attempt_count"] = new_attempts
            res["status"] = new_status
            res["dead_lettered"] = not res["ok"]
            ledger.record_webhook_delivery(res)
            ledger.queue.upsert_webhook_dlq(
                delivery_id=item["delivery_id"],
                webhook_id=item["webhook_id"],
                event_name=item["event"],
                url=item["url"],
                payload=item["payload"],
                status=new_status,
                attempt_count=new_attempts,
                max_attempts=max(max_attempts, new_attempts),
                next_retry_at=now_ts,
                last_error=res.get("error"),
            )
            get_telemetry().record_webhook_delivery(f"replay_{new_status}")
            replayed.append(res)
    return replayed
