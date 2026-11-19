"""Visual ECN Rev A vs Rev B diff, Author<->CVE review threads, and Excel/CATIA bridges."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_sha256(obj: Any) -> str:
    encoded = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _to_dec(val: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def compute_ecn_revision_diff(
    rev_a_dossier: dict[str, Any],
    rev_b_dossier: dict[str, Any],
    *,
    ecn_id: str = "ECN-2026-001",
) -> dict[str, Any]:
    """Compare Rev A vs Rev B engineering dossiers across requirements, CAD, FEM, and Margins."""
    req_a = {
        str(r.get("id")): r
        for r in (rev_a_dossier.get("requirements") or [])
        if isinstance(r, dict) and r.get("id")
    }
    req_b = {
        str(r.get("id")): r
        for r in (rev_b_dossier.get("requirements") or [])
        if isinstance(r, dict) and r.get("id")
    }
    added_reqs = sorted(set(req_b) - set(req_a))
    removed_reqs = sorted(set(req_a) - set(req_b))
    modified_reqs = [
        rid
        for rid in sorted(set(req_a) & set(req_b))
        if _canonical_sha256(req_a[rid]) != _canonical_sha256(req_b[rid])
    ]

    # CAD mass, CG & min thickness delta
    cad_a = dict(rev_a_dossier.get("cad") or {})
    cad_b = dict(rev_b_dossier.get("cad") or {})
    mass_a = _to_dec(cad_a.get("mass_kg", "0"))
    mass_b = _to_dec(cad_b.get("mass_kg", "0"))
    cg_a = list(cad_a.get("cg_mm") or [0, 0, 0])
    cg_b = list(cad_b.get("cg_mm") or [0, 0, 0])
    cg_delta = [
        str(_to_dec(cg_b[i] if i < len(cg_b) else 0) - _to_dec(cg_a[i] if i < len(cg_a) else 0))
        for i in range(3)
    ]
    thk_a = _to_dec(cad_a.get("min_thickness_mm", "0"))
    thk_b = _to_dec(cad_b.get("min_thickness_mm", "0"))

    # FEM peak stress & critical elements delta
    fem_a = dict(rev_a_dossier.get("fem") or {})
    fem_b = dict(rev_b_dossier.get("fem") or {})
    peak_a = _to_dec(fem_a.get("peak_von_mises_mpa", "0"))
    peak_b = _to_dec(fem_b.get("peak_von_mises_mpa", "0"))
    crit_a = set(fem_a.get("critical_elements") or [])
    crit_b = set(fem_b.get("critical_elements") or [])

    # Margin of Safety comparisons per check / part / method
    margins_a = dict(rev_a_dossier.get("margins") or {})
    margins_b = dict(rev_b_dossier.get("margins") or {})
    margin_deltas: list[dict[str, Any]] = []
    degraded_margins: list[dict[str, Any]] = []
    negative_margins: list[dict[str, Any]] = []
    for key in sorted(set(margins_a) | set(margins_b)):
        has_a = key in margins_a
        has_b = key in margins_b
        ms_a = _to_dec(margins_a[key]) if has_a else None
        ms_b = _to_dec(margins_b[key]) if has_b else None
        delta_ms = (ms_b - ms_a) if (ms_a is not None and ms_b is not None) else None
        degraded = bool((delta_ms is not None and delta_ms < 0) or (ms_b is not None and ms_b < 0))
        neg_now = bool(ms_b is not None and ms_b < 0)
        item = {
            "item_id": key,
            "ms_rev_a": str(ms_a) if ms_a is not None else None,
            "ms_rev_b": str(ms_b) if ms_b is not None else None,
            "delta_ms": str(delta_ms) if delta_ms is not None else None,
            "degraded": degraded,
            "negative_margin": neg_now,
        }
        margin_deltas.append(item)
        if degraded:
            degraded_margins.append(item)
        if neg_now:
            negative_margins.append(item)

    result: dict[str, Any] = {
        "ecn_id": ecn_id,
        "generated_at": _now_iso(),
        "requirements": {
            "added": added_reqs,
            "removed": removed_reqs,
            "modified": modified_reqs,
        },
        "cad_delta": {
            "mass_kg_rev_a": str(mass_a),
            "mass_kg_rev_b": str(mass_b),
            "mass_delta_kg": str(mass_b - mass_a),
            "cg_delta_mm": cg_delta,
            "min_thickness_delta_mm": str(thk_b - thk_a),
        },
        "fem_delta": {
            "peak_von_mises_rev_a_mpa": str(peak_a),
            "peak_von_mises_rev_b_mpa": str(peak_b),
            "peak_stress_delta_mpa": str(peak_b - peak_a),
            "new_critical_elements": sorted(crit_b - crit_a),
            "cleared_critical_elements": sorted(crit_a - crit_b),
        },
        "margin_deltas": margin_deltas,
        "degraded_margins": degraded_margins,
        "negative_margins": negative_margins,
        "impact_summary": {
            "total_requirement_changes": len(added_reqs) + len(removed_reqs) + len(modified_reqs),
            "total_margin_items": len(margin_deltas),
            "degraded_count": len(degraded_margins),
            "negative_ms_count": len(negative_margins),
            "signoff_reverification_required": bool(
                added_reqs or removed_reqs or modified_reqs or degraded_margins or negative_margins
            ),
        },
    }
    hashable = {k: v for k, v in result.items() if k != "generated_at"}
    result["diff_sha256"] = _canonical_sha256(hashable)
    return result


@dataclass
class _ReviewThread:
    thread_id: str
    tenant_id: str
    target_event_hash: str
    author_id: str
    category: str
    anchor: dict[str, Any]
    status: str  # OPEN | CHANGES_REQUESTED | RESOLVED | LOCKED_ON_SIGNOFF
    created_at: str
    updated_at: str
    comments: list[dict[str, Any]] = field(default_factory=list)
    resolved_by: str | None = None
    resolution_note: str | None = None
    signoff_event_hash: str | None = None
    locked_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "tenant_id": self.tenant_id,
            "target_event_hash": self.target_event_hash,
            "author_id": self.author_id,
            "category": self.category,
            "anchor": dict(self.anchor),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "comments": [dict(c) for c in self.comments],
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
            "signoff_event_hash": self.signoff_event_hash,
            "locked_at": self.locked_at,
        }


class ReviewThreadStore:
    """Author <-> CVE review thread workflow enforcing signoff blocking and locking."""

    BLOCKING_STATUSES = {"OPEN", "CHANGES_REQUESTED"}
    _TENANT_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

    def __init__(
        self,
        *,
        storage_dir: Path | None = None,
        persist: bool | None = None,
        use_default_home: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._threads: dict[tuple[str, str], _ReviewThread] = {}
        self._storage_dir = Path(storage_dir) if storage_dir is not None else None
        self._persist = persist
        self._use_default_home = use_default_home
        self._initialized_dbs: set[Path] = set()

    def _db_path_for(self, tenant_id: str) -> Path | None:
        if self._persist is False:
            return None
        safe_tenant = (
            tenant_id
            if self._TENANT_RE.fullmatch(tenant_id)
            else hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
        )
        if self._storage_dir is not None:
            return (self._storage_dir / f"{safe_tenant}.reviews.sqlite3").resolve()
        env_home = os.environ.get("EVIDENCE_HOME", "").strip()
        fname = f"{safe_tenant}.reviews.sqlite3"
        if env_home:
            return (Path(env_home).resolve() / "tenants" / fname).resolve()
        if self._persist is True or self._use_default_home:
            return (Path.home().resolve() / ".aeroregu" / "tenants" / fname).resolve()
        return None

    def _connect(self, db_path: Path) -> sqlite3.Connection:
        if db_path not in self._initialized_dbs:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=15.0)
        if db_path not in self._initialized_dbs:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_threads (
                    tenant_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    target_event_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, thread_id)
                )
                """
            )
            conn.commit()
            self._initialized_dbs.add(db_path)
        return conn

    @staticmethod
    def _thread_from_dict(data: dict[str, Any]) -> _ReviewThread:
        return _ReviewThread(
            thread_id=str(data["thread_id"]),
            tenant_id=str(data["tenant_id"]),
            target_event_hash=str(data["target_event_hash"]),
            author_id=str(data["author_id"]),
            category=str(data.get("category", "review_comment")),
            anchor=dict(data.get("anchor") or {}),
            status=str(data["status"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            comments=[dict(c) for c in (data.get("comments") or [])],
            resolved_by=data.get("resolved_by"),
            resolution_note=data.get("resolution_note"),
            signoff_event_hash=data.get("signoff_event_hash"),
            locked_at=data.get("locked_at"),
        )

    def _save_to_db(self, db_path: Path, thread: _ReviewThread) -> None:
        with self._connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_threads (
                    tenant_id, thread_id, target_event_hash, status,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, thread_id) DO UPDATE SET
                    target_event_hash=excluded.target_event_hash,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    thread.tenant_id,
                    thread.thread_id,
                    thread.target_event_hash,
                    thread.status,
                    thread.created_at,
                    thread.updated_at,
                    json.dumps(thread.as_dict(), ensure_ascii=True),
                ),
            )
            conn.commit()

    def _load_one_from_db(
        self, db_path: Path, tenant_id: str, thread_id: str
    ) -> _ReviewThread | None:
        if not db_path.is_file() and db_path not in self._initialized_dbs:
            return None
        with self._connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM review_threads WHERE tenant_id = ? AND thread_id = ?",
                (tenant_id, thread_id),
            ).fetchone()
        if row is None:
            return None
        return self._thread_from_dict(json.loads(str(row[0])))

    def _load_all_from_db(self, db_path: Path, tenant_id: str) -> list[_ReviewThread]:
        if not db_path.is_file() and db_path not in self._initialized_dbs:
            return []
        with self._connect(db_path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM review_threads "
                "WHERE tenant_id = ? ORDER BY created_at, thread_id",
                (tenant_id,),
            ).fetchall()
        return [self._thread_from_dict(json.loads(str(r[0]))) for r in rows]

    def create_thread(
        self,
        tenant_id: str,
        *,
        target_event_hash: str,
        author_id: str,
        body: str,
        anchor: dict[str, Any] | None = None,
        category: str = "review_comment",
        initial_status: str = "OPEN",
    ) -> dict[str, Any]:
        norm_status = initial_status.strip().upper()
        if norm_status not in {"OPEN", "CHANGES_REQUESTED"}:
            raise ValueError("invalid_initial_thread_status")
        if not str(body).strip():
            raise ValueError("empty_thread_body")
        tid = f"thr-{secrets.token_hex(6)}"
        now = _now_iso()
        thread = _ReviewThread(
            thread_id=tid,
            tenant_id=tenant_id,
            target_event_hash=str(target_event_hash),
            author_id=str(author_id),
            category=str(category),
            anchor=dict(anchor or {}),
            status=norm_status,
            created_at=now,
            updated_at=now,
            comments=[
                {
                    "comment_id": f"cmt-{secrets.token_hex(4)}",
                    "actor_id": str(author_id),
                    "body": str(body).strip(),
                    "action": norm_status.lower(),
                    "created_at": now,
                }
            ],
        )
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            if db_path is not None:
                self._save_to_db(db_path, thread)
            else:
                self._threads[(tenant_id, tid)] = thread
            return thread.as_dict()

    def reply_thread(
        self,
        tenant_id: str,
        thread_id: str,
        *,
        actor_id: str,
        body: str,
        request_changes: bool = False,
    ) -> dict[str, Any]:
        if not str(body).strip():
            raise ValueError("empty_reply_body")
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            thr = (
                self._load_one_from_db(db_path, tenant_id, thread_id)
                if db_path is not None
                else self._threads.get((tenant_id, thread_id))
            )
            if thr is None:
                raise KeyError("thread_not_found")
            if thr.status == "LOCKED_ON_SIGNOFF":
                raise ValueError("thread_locked")
            now = _now_iso()
            if request_changes:
                thr.status = "CHANGES_REQUESTED"
            elif thr.status == "RESOLVED":
                thr.status = "OPEN"
            thr.updated_at = now
            thr.comments.append(
                {
                    "comment_id": f"cmt-{secrets.token_hex(4)}",
                    "actor_id": str(actor_id),
                    "body": str(body).strip(),
                    "action": "changes_requested" if request_changes else "reply",
                    "created_at": now,
                }
            )
            if db_path is not None:
                self._save_to_db(db_path, thr)
            return thr.as_dict()

    def resolve_thread(
        self,
        tenant_id: str,
        thread_id: str,
        *,
        resolver_id: str,
        resolution_note: str = "Verified and resolved",
    ) -> dict[str, Any]:
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            thr = (
                self._load_one_from_db(db_path, tenant_id, thread_id)
                if db_path is not None
                else self._threads.get((tenant_id, thread_id))
            )
            if thr is None:
                raise KeyError("thread_not_found")
            if thr.status == "LOCKED_ON_SIGNOFF":
                raise ValueError("thread_locked")
            now = _now_iso()
            thr.status = "RESOLVED"
            thr.resolved_by = str(resolver_id)
            thr.resolution_note = str(resolution_note)
            thr.updated_at = now
            thr.comments.append(
                {
                    "comment_id": f"cmt-{secrets.token_hex(4)}",
                    "actor_id": str(resolver_id),
                    "body": str(resolution_note),
                    "action": "resolved",
                    "created_at": now,
                }
            )
            if db_path is not None:
                self._save_to_db(db_path, thr)
            return thr.as_dict()

    def list_threads(
        self,
        tenant_id: str,
        *,
        target_event_hash: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            items = (
                self._load_all_from_db(db_path, tenant_id)
                if db_path is not None
                else [thr for (t_id, _), thr in self._threads.items() if t_id == tenant_id]
            )
            out = [
                thr.as_dict()
                for thr in items
                if target_event_hash is None or thr.target_event_hash == target_event_hash
            ]
        return sorted(out, key=lambda item: (item["created_at"], item["thread_id"]))

    def unresolved_blocking_threads(
        self,
        tenant_id: str,
        *,
        target_event_hash: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            items = (
                self._load_all_from_db(db_path, tenant_id)
                if db_path is not None
                else [thr for (t_id, _), thr in self._threads.items() if t_id == tenant_id]
            )
            blocking: list[dict[str, Any]] = []
            for thr in items:
                if target_event_hash is not None and thr.target_event_hash != target_event_hash:
                    continue
                if thr.status in self.BLOCKING_STATUSES:
                    blocking.append(thr.as_dict())
            return sorted(blocking, key=lambda item: (item["created_at"], item["thread_id"]))

    def lock_threads_on_signoff(
        self,
        tenant_id: str,
        *,
        target_event_hash: str,
        signoff_event_hash: str,
        signed_by: str = "reviewer",
    ) -> list[dict[str, Any]]:
        with self._lock:
            db_path = self._db_path_for(tenant_id)
            items = (
                self._load_all_from_db(db_path, tenant_id)
                if db_path is not None
                else [thr for (t_id, _), thr in self._threads.items() if t_id == tenant_id]
            )
            locked: list[dict[str, Any]] = []
            now = _now_iso()
            for thr in items:
                if thr.target_event_hash == target_event_hash and thr.status == "RESOLVED":
                    thr.status = "LOCKED_ON_SIGNOFF"
                    thr.signoff_event_hash = str(signoff_event_hash)
                    thr.locked_at = now
                    thr.updated_at = now
                    thr.comments.append(
                        {
                            "comment_id": f"cmt-{secrets.token_hex(4)}",
                            "actor_id": str(signed_by),
                            "body": f"Locked on signoff {signoff_event_hash[:12]}",
                            "action": "locked_on_signoff",
                            "created_at": now,
                        }
                    )
                    if db_path is not None:
                        self._save_to_db(db_path, thr)
                    locked.append(thr.as_dict())
            return locked


class ExcelStressSheetBridge:
    """Bi-directional bridge for Excel Stress Sheet named-range inputs and verification stamps."""

    @staticmethod
    def import_named_ranges(workbook_payload: dict[str, Any]) -> dict[str, Any]:
        workbook_id = str(workbook_payload.get("workbook_id") or "stress-sheet-01")
        sheet_name = str(workbook_payload.get("sheet_name") or "StressSummary")
        method_id = str(workbook_payload.get("method_id") or "margin_of_safety")
        named_ranges = dict(workbook_payload.get("named_ranges") or {})
        clean_inputs: dict[str, str] = {}
        stated_outputs: dict[str, str] = {}
        range_map: dict[str, str] = {}
        for range_name, spec in named_ranges.items():
            if isinstance(spec, dict):
                val = str(spec.get("value", ""))
                cell_ref = str(spec.get("cell", range_name))
                role = str(spec.get("role", "input"))
            else:
                val = str(spec)
                cell_ref = str(range_name)
                role = "input"
            range_map[str(range_name)] = cell_ref
            if role == "stated_output":
                stated_outputs[str(range_name)] = val
            else:
                clean_inputs[str(range_name)] = val
        return {
            "workbook_id": workbook_id,
            "sheet_name": sheet_name,
            "method_id": method_id,
            "inputs": clean_inputs,
            "stated_outputs": stated_outputs,
            "range_map": range_map,
        }

    @staticmethod
    def export_verification_stamp(
        workbook_payload: dict[str, Any],
        *,
        calc_result: dict[str, Any],
        merkle_root: str,
        event_hash: str,
    ) -> dict[str, Any]:
        outputs = dict(calc_result.get("outputs") or {})
        ms_val = outputs.get("margin_of_safety", outputs.get("gapping_margin_of_safety", "N/A"))
        rf_val = outputs.get("reserve_factor_achieved", outputs.get("reserve_factor", "N/A"))
        stamp_cells = {
            "AEROREGU_METHOD": str(calc_result.get("method_id", "")),
            "AEROREGU_MS": str(ms_val),
            "AEROREGU_RF": str(rf_val),
            "AEROREGU_MERKLE_ROOT": str(merkle_root),
            "AEROREGU_EVENT_HASH": str(event_hash),
            "AEROREGU_STATUS": "VERIFIED",
            "AEROREGU_TIMESTAMP": _now_iso(),
        }
        return {
            "workbook_id": str(workbook_payload.get("workbook_id") or "stress-sheet-01"),
            "sheet_name": str(workbook_payload.get("sheet_name") or "StressSummary"),
            "written_named_ranges": stamp_cells,
            "stamp_sha256": _canonical_sha256(
                {k: v for k, v in stamp_cells.items() if k != "AEROREGU_TIMESTAMP"}
            ),
        }


class CatiaInspectorBridge:
    """Bi-directional CATIA 3DX inspector context resolver for parts, features, plies & FEM."""

    @staticmethod
    def resolve_selection_context(
        selection_payload: dict[str, Any],
        *,
        cad_result: dict[str, Any] | None = None,
        margins_by_part: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        part_number = str(selection_payload.get("part_number") or "UNKNOWN-PART")
        feature_id = selection_payload.get("feature_id")
        ply_id = selection_payload.get("ply_id")
        element_id = selection_payload.get("element_id")

        part_margin = (margins_by_part or {}).get(part_number)
        cad_features: dict[str, Any] = {}
        if isinstance(cad_result, dict):
            cad_features = {
                "volume_m3": cad_result.get("volume_m3"),
                "surface_area_m2": cad_result.get("surface_area_m2"),
                "bbox_mm": cad_result.get("bbox_mm"),
                "interference_count": cad_result.get("interference_count", 0),
            }

        status = "VERIFIED" if part_margin is not None else "UNLINKED"
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 4)
        return {
            "part_number": part_number,
            "feature_id": feature_id,
            "ply_id": ply_id,
            "element_id": element_id,
            "verification_status": status,
            "margin_record": part_margin,
            "cad_telemetry": cad_features,
            "click_to_evidence_ms": latency_ms,
        }


_GLOBAL_REVIEW_THREADS = ReviewThreadStore(use_default_home=True)


def get_review_thread_store() -> ReviewThreadStore:
    return _GLOBAL_REVIEW_THREADS
