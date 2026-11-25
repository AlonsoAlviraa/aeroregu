"""Live Bidirectional Enterprise PLM Connectors (3DEXPERIENCE/ENOVIA, Teamcenter, Windchill).

Provides:
- OAuth2 / OIDC automatic token acquisition & expiry refresh (401 retry)
- Exponential backoff retry on transient HTTP 503/429/502/504 + Circuit Breaker
- EBOM / MBOM / BOP tree resolution with Rev A -> Rev B and MSN/Effectivity filtering
- Selective PID-level invalidation on ECN events (queue + DistributedCacheCoordinator)
- Bidirectional Merkle Root & compliance dossier writeback into PLM objects
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

PLMSystemType = Literal["3dexperience", "teamcenter", "windchill"]


class PLMConnectorError(RuntimeError):
    """Raised when a PLM connector fails or the circuit breaker trips."""


class CircuitBreakerOpenError(PLMConnectorError):
    """Raised immediately while circuit breaker is OPEN."""


@dataclass
class CircuitBreaker:
    """Thread-safe three-state circuit breaker (CLOSED -> OPEN -> HALF_OPEN)."""

    failure_threshold: int = 5
    recovery_timeout_s: float = 15.0
    state: str = "CLOSED"
    failure_count: int = 0
    opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def before_call(self) -> None:
        with self._lock:
            if self.state == "OPEN":
                assert self.opened_at is not None
                if (time.monotonic() - self.opened_at) >= self.recovery_timeout_s:
                    self.state = "HALF_OPEN"
                else:
                    raise CircuitBreakerOpenError("plm_circuit_breaker_open")

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0
            self.state = "CLOSED"
            self.opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                self.opened_at = time.monotonic()


@dataclass
class OAuth2TokenManager:
    """OAuth2 / OIDC client-credentials & refresh-token lifecycle manager."""

    token_url: str
    client_id: str
    client_secret: str
    scope: str = "plm.read plm.write"
    client: httpx.Client | None = None
    _access_token: str | None = None
    _expires_at: float = 0.0
    _refresh_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def force_expire(self) -> None:
        with self._lock:
            self._expires_at = 0.0

    def get_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._access_token is not None
                and now < (self._expires_at - 5.0)
            ):
                return self._access_token
            if self.client is None:
                raise PLMConnectorError("oauth_http_client_missing")
            resp = self.client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": self.scope,
                },
            )
            if resp.status_code != 200:
                raise PLMConnectorError(f"oauth_token_failed:{resp.status_code}")
            body = resp.json()
            self._access_token = str(body["access_token"])
            ttl = float(body.get("expires_in", 3600))
            self._expires_at = time.monotonic() + ttl
            self._refresh_count += 1
            return self._access_token


def effectivity_matches(msn: int, effectivity_expr: str) -> bool:
    """Evaluate aircraft MSN effectivity such as 'MSN 001-015', 'MSN 016+', or 'ALL'."""
    expr = str(effectivity_expr or "ALL").strip().upper()
    if not expr or expr in {"ALL", "*"}:
        return True
    cleaned = expr.replace("MSN", "").strip()
    for token in cleaned.split(","):
        tok = token.strip()
        if not tok:
            continue
        if tok.endswith("+"):
            start = int(tok[:-1])
            if msn >= start:
                return True
        elif "-" in tok:
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo <= msn <= hi:
                return True
        else:
            if msn == int(tok):
                return True
    return False


class _BasePLMConnector:
    """Shared resilient HTTP/OAuth2/Circuit-Breaker transport layer for enterprise PLMs."""

    system_name: PLMSystemType

    def __init__(
        self,
        *,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 5,
        backoff_base_s: float = 0.01,
        circuit_failure_threshold: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(transport=transport, timeout=15.0)
        self.auth = OAuth2TokenManager(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            client=self._client,
        )
        self.breaker = CircuitBreaker(failure_threshold=circuit_failure_threshold)
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.telemetry_retries = 0

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.breaker.before_call()
        url = f"{self.base_url}/{path.lstrip('/')}"
        refreshed_after_401 = False
        last_err: Exception | None = None

        for attempt in range(self.max_retries + 1):
            token = self.auth.get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-PLM-System": self.system_name,
            }
            try:
                resp = self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:
                last_err = exc
                self.breaker.record_failure()
                if attempt < self.max_retries:
                    self.telemetry_retries += 1
                    time.sleep(self.backoff_base_s * (2**attempt))
                    continue
                raise PLMConnectorError(f"plm_transport_error:{exc}") from exc

            if resp.status_code == 401 and not refreshed_after_401:
                refreshed_after_401 = True
                self.auth.get_token(force_refresh=True)
                self.telemetry_retries += 1
                continue

            if resp.status_code in {429, 502, 503, 504}:
                last_err = PLMConnectorError(f"http_{resp.status_code}")
                if attempt < self.max_retries:
                    self.telemetry_retries += 1
                    time.sleep(self.backoff_base_s * (2**attempt))
                    continue
                self.breaker.record_failure()
                raise last_err

            if resp.status_code >= 400:
                self.breaker.record_failure()
                raise PLMConnectorError(f"plm_http_error:{resp.status_code}:{resp.text[:200]}")

            self.breaker.record_success()
            return dict(resp.json())

        raise PLMConnectorError(f"plm_retries_exhausted:{last_err}")

    def close(self) -> None:
        self._client.close()


class ThreeDExperienceConnector(_BasePLMConnector):
    """Dassault 3DEXPERIENCE / ENOVIA 3DSpace REST connector."""

    system_name: PLMSystemType = "3dexperience"

    def fetch_ebom(self, item_id: str, *, revision: str = "Rev A", msn: int = 1) -> dict[str, Any]:
        raw = self._request_json(
            "GET",
            f"/resources/v1/modeler/dseng/dseng:EngItem/{item_id}/expand",
            params={"revision": revision, "msn": msn},
        )
        return _filter_bom_by_msn(self.system_name, raw, msn=msn)

    def fetch_ecn_diff(self, ecn_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/resources/v1/modeler/dseno/ChangeAction/{ecn_id}")

    def writeback_merkle_attestation(
        self,
        *,
        change_action_id: str,
        merkle_root: str,
        head_hash: str,
        chain_verified: bool,
        revision: str,
        msn: int,
    ) -> dict[str, Any]:
        payload = {
            "change_action_id": change_action_id,
            "merkle_root": merkle_root,
            "head_hash": head_hash,
            "chain_verified": chain_verified,
            "revision": revision,
            "msn": msn,
            "attested_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return self._request_json(
            "PATCH",
            f"/resources/v1/modeler/dseno/ChangeAction/{change_action_id}/attestation",
            json_body=payload,
        )


class TeamcenterConnector(_BasePLMConnector):
    """Siemens Teamcenter SOA / Active Workspace REST connector."""

    system_name: PLMSystemType = "teamcenter"

    def fetch_ebom(self, item_id: str, *, revision: str = "Rev A", msn: int = 1) -> dict[str, Any]:
        raw = self._request_json(
            "GET",
            f"/JsonRestServices/Core-2011-06-DataManagement/bom/{item_id}",
            params={"revision": revision, "msn": msn},
        )
        return _filter_bom_by_msn(self.system_name, raw, msn=msn)

    def fetch_ecn_diff(self, ecn_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET", f"/JsonRestServices/Cm-2014-12-ChangeManagement/ChangeNotice/{ecn_id}"
        )

    def writeback_merkle_attestation(
        self,
        *,
        change_action_id: str,
        merkle_root: str,
        head_hash: str,
        chain_verified: bool,
        revision: str,
        msn: int,
    ) -> dict[str, Any]:
        payload = {
            "change_notice_id": change_action_id,
            "merkle_root": merkle_root,
            "head_hash": head_hash,
            "chain_verified": chain_verified,
            "revision": revision,
            "msn": msn,
        }
        return self._request_json(
            "POST",
            f"/JsonRestServices/Cm-2014-12-ChangeManagement/ChangeNotice/{change_action_id}/attestation",
            json_body=payload,
        )


class WindchillConnector(_BasePLMConnector):
    """PTC Windchill OData REST API connector."""

    system_name: PLMSystemType = "windchill"

    def fetch_ebom(self, item_id: str, *, revision: str = "Rev A", msn: int = 1) -> dict[str, Any]:
        raw = self._request_json(
            "GET",
            f"/Windchill/servlet/odata/ProdMgmt/Parts('{item_id}')/Uses",
            params={"revision": revision, "msn": msn},
        )
        return _filter_bom_by_msn(self.system_name, raw, msn=msn)

    def fetch_ecn_diff(self, ecn_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET", f"/Windchill/servlet/odata/ChangeMgmt/ChangeNotices('{ecn_id}')"
        )

    def writeback_merkle_attestation(
        self,
        *,
        change_action_id: str,
        merkle_root: str,
        head_hash: str,
        chain_verified: bool,
        revision: str,
        msn: int,
    ) -> dict[str, Any]:
        payload = {
            "ecn_id": change_action_id,
            "merkle_root": merkle_root,
            "head_hash": head_hash,
            "chain_verified": chain_verified,
            "revision": revision,
            "msn": msn,
        }
        return self._request_json(
            "PATCH",
            f"/Windchill/servlet/odata/ChangeMgmt/ChangeNotices('{change_action_id}')",
            json_body=payload,
        )


def _filter_bom_by_msn(system_name: str, raw: dict[str, Any], *, msn: int) -> dict[str, Any]:
    parts = list(raw.get("parts") or [])
    active_parts = [p for p in parts if effectivity_matches(msn, str(p.get("effectivity", "ALL")))]
    return {
        "system": system_name,
        "item_id": raw.get("item_id"),
        "revision": raw.get("revision"),
        "msn": msn,
        "total_part_count": len(parts),
        "active_part_count": len(active_parts),
        "parts": active_parts,
        "bom_types": raw.get("bom_types", ["EBOM", "MBOM", "BOP"]),
    }


def compute_selective_pid_invalidation(
    *,
    ecn_diff: dict[str, Any],
    all_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute selective PID & cell invalidation without resetting unaffected components."""
    changed_pids = {int(p) for p in ecn_diff.get("changed_pids", [])}
    invalidated: list[str] = []
    unaffected: list[str] = []
    for cell in all_cells:
        cid = str(cell.get("cell_id") or cell.get("id") or "")
        cell_pids = {int(x) for x in cell.get("pids", [])}
        if cell_pids & changed_pids:
            invalidated.append(cid)
        else:
            unaffected.append(cid)

    return {
        "ecn_id": ecn_diff.get("ecn_id"),
        "from_revision": ecn_diff.get("from_revision", "Rev A"),
        "to_revision": ecn_diff.get("to_revision", "Rev B"),
        "changed_pids": sorted(changed_pids),
        "invalidated_cell_count": len(invalidated),
        "unaffected_cell_count": len(unaffected),
        "invalidated_cells": invalidated,
        "unaffected_cells": unaffected,
    }


def apply_ecn_selective_invalidation_to_ledger(
    ledger: Any,
    *,
    ecn_diff: dict[str, Any],
    all_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist selective PID invalidation jobs to ledger queue and bump distributed cache epoch."""
    plan = compute_selective_pid_invalidation(ecn_diff=ecn_diff, all_cells=all_cells)
    if hasattr(ledger, "queue"):
        for cid in plan["invalidated_cells"]:
            jid = f"ecn-{plan['ecn_id']}-{cid}"
            ledger.queue.enqueue_daemon_job(
                idempotency_key=jid,
                job_type="plm_ecn_invalidate",
                payload={"cell_id": cid, "ecn_id": plan["ecn_id"], "pids": plan["changed_pids"]},
            )
    epoch = 0
    if hasattr(ledger, "cache"):
        epoch = ledger.cache.invalidate(
            "coverage_summary",
            {
                "ecn_id": plan["ecn_id"],
                "changed_pids": plan["changed_pids"],
                "invalidated_cells": plan["invalidated_cells"],
            },
        )
    return {**plan, "cache_epoch": epoch}


def build_plm_connector(
    system: PLMSystemType,
    *,
    base_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    transport: httpx.BaseTransport | None = None,
) -> _BasePLMConnector:
    mapping: dict[PLMSystemType, type[_BasePLMConnector]] = {
        "3dexperience": ThreeDExperienceConnector,
        "teamcenter": TeamcenterConnector,
        "windchill": WindchillConnector,
    }
    cls = mapping[system]
    return cls(
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        transport=transport,
    )


class MockPLMServerTransport(httpx.BaseTransport):
    """Realistic multi-PLM HTTP mock supporting OAuth2 expiry, 503 storms & writebacks."""

    def __init__(
        self,
        *,
        transient_503_budget: int = 0,
        expire_first_token_once: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self.transient_503_budget = transient_503_budget
        self.expire_first_token_once = expire_first_token_once
        self._token_seq = 0
        self._active_token: str | None = None
        self._rejected_expired_once = False
        self.writebacks: dict[str, dict[str, Any]] = {}
        self.request_history: list[tuple[str, str, int]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()
        with self._lock:
            if path.endswith("/oauth/token"):
                self._token_seq += 1
                self._active_token = f"plm-oauth-token-{self._token_seq}"
                resp_body = {"access_token": self._active_token, "expires_in": 3600}
                self.request_history.append((method, path, 200))
                return httpx.Response(200, json=resp_body)

            auth_hdr = request.headers.get("authorization", "")
            expected = f"Bearer {self._active_token}" if self._active_token else ""
            if not self._active_token or auth_hdr != expected:
                self.request_history.append((method, path, 401))
                return httpx.Response(401, json={"error": "invalid_token"})

            if self.expire_first_token_once and not self._rejected_expired_once:
                self._rejected_expired_once = True
                self._active_token = "expired-force-refresh"
                self.request_history.append((method, path, 401))
                return httpx.Response(401, json={"error": "token_expired"})

            if self.transient_503_budget > 0:
                self.transient_503_budget -= 1
                self.request_history.append((method, path, 503))
                return httpx.Response(503, json={"error": "plm_upstream_busy"})

            rev = request.url.params.get("revision", "Rev A")

            if "attestation" in path or (method == "PATCH" and "ChangeNotices" in path):
                body = json.loads(request.content.decode("utf-8") or "{}")
                key = str(
                    body.get("change_action_id")
                    or body.get("change_notice_id")
                    or body.get("ecn_id")
                    or path
                )
                self.writebacks[key] = body
                self.request_history.append((method, path, 200))
                return httpx.Response(200, json={"status": "attested", "writeback": body})

            if "ChangeAction" in path or "ChangeNotice" in path:
                ecn_id = (
                    path.rsplit("/", 1)[-1].split("'")[1]
                    if "'" in path
                    else path.rsplit("/", 1)[-1]
                )
                diff = {
                    "ecn_id": ecn_id,
                    "from_revision": "Rev A",
                    "to_revision": "Rev B",
                    "changed_pids": [2001, 2002],
                    "effectivity": "MSN 016+",
                    "cg_shift_x_mm": "+15.000",
                    "summary": "Rib web pocket +15mm CG shift & fastener pitch ECN",
                }
                self.request_history.append((method, path, 200))
                return httpx.Response(200, json=diff)

            bom = {
                "item_id": "WING-SPAR-ASM-01",
                "revision": rev,
                "bom_types": ["EBOM", "MBOM", "BOP"],
                "parts": [
                    {
                        "part_id": "SPAR-MAIN-2001",
                        "pid": 2001,
                        "effectivity": "ALL",
                        "mass_kg": "42.500",
                    },
                    {
                        "part_id": "RIB-01-LEGACY",
                        "pid": 1001,
                        "effectivity": "MSN 001-015",
                        "mass_kg": "6.100",
                    },
                    {
                        "part_id": "RIB-01-REVB",
                        "pid": 2002,
                        "effectivity": "MSN 016+",
                        "mass_kg": "6.850",
                    },
                    {
                        "part_id": "LUG-FIT-3001",
                        "pid": 3001,
                        "effectivity": "ALL",
                        "mass_kg": "3.200",
                    },
                ],
            }
            self.request_history.append((method, path, 200))
            return httpx.Response(200, json=bom)


def run_plm_ecn_resilience_probe(
    system: PLMSystemType = "3dexperience",
    *,
    inject_503_count: int = 2,
    expire_token_once: bool = True,
) -> dict[str, Any]:
    """Execute deterministic Rev A -> Rev B ECN drill under 503 storms & OAuth token expiry."""
    transport = MockPLMServerTransport(
        transient_503_budget=inject_503_count,
        expire_first_token_once=expire_token_once,
    )
    conn = build_plm_connector(
        system,
        base_url="https://plm.aeroregu.local",
        token_url="https://plm.aeroregu.local/oauth/token",
        client_id="aeroregu-sync",
        client_secret="mock-secret",
        transport=transport,
    )
    bom_rev_b = conn.fetch_ebom("WING-SPAR-ASM-01", revision="Rev B", msn=16)
    ecn_diff = conn.fetch_ecn_diff("ECN-2026-019")
    plan = compute_selective_pid_invalidation(
        ecn_diff=ecn_diff,
        all_cells=[
            {"cell_id": "cell-spar", "pids": [2001]},
            {"cell_id": "cell-rib-revb", "pids": [2002]},
            {"cell_id": "cell-lug-untouched", "pids": [3001]},
        ],
    )
    wb_res = conn.writeback_merkle_attestation(
        change_action_id="ECN-2026-019",
        merkle_root="a" * 64,
        head_hash="b" * 64,
        chain_verified=True,
        revision="Rev B",
        msn=16,
    )
    return {
        "system": system,
        "active_part_count": bom_rev_b["active_part_count"],
        "invalidated_cells": plan["invalidated_cells"],
        "unaffected_cells": plan["unaffected_cells"],
        "token_refreshes": conn.auth._refresh_count,
        "http_503_retries_observed": sum(
            1 for _, _, code in transport.request_history if code == 503
        ),
        "http_401_refreshes_observed": sum(
            1 for _, _, code in transport.request_history if code == 401
        ),
        "writeback_status": wb_res.get("status"),
    }
