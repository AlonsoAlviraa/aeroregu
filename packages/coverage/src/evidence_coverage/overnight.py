"""Overnight verification orchestrator, 08:00 AM Morning Briefing ranker & Batch Human Sign-Off."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from evidence_kernel.daemon import (
    DaemonRunner,
    FolderWatcher,
    GitWatcher,
    OvernightBudget,
)
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import SIGN_OFF_STATEMENT, LedgerError
from evidence_kernel.orchestrator import record
from evidence_kernel.telemetry import get_telemetry

from evidence_coverage.adversarial import run_bench_attacker, run_envelope_critic
from evidence_coverage.cross_artifact import audit_cross_artifact_consistency
from evidence_coverage.grid import generate_cells
from evidence_coverage.nafems_audit import run_full_nafems_audit
from evidence_coverage.status import list_cells_with_status


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _risk_score_for_item(category: str, severity: str, ms_val: str | None = None) -> int:
    base = {"CRITICAL": 900, "HIGH": 650, "MEDIUM": 400, "LOW": 200}.get(severity.upper(), 300)
    if ms_val is not None:
        try:
            ms_dec = Decimal(str(ms_val))
            if ms_dec < Decimal("0"):
                base += 100
        except Exception:
            pass
    if category in {"ms_negative", "cg_envelope_exceedance", "cross_artifact_mass_mismatch"}:
        base += 50
    elif category == "abstain":
        base += 30
    elif category == "stale_cell":
        base += 20
    return base


def default_showcase_artifacts() -> dict[str, Any]:
    """Realistic multi-department conflict fixture for interactive overnight briefing demos."""
    return {
        "requirements": {
            "program_id": "CS-27.625 / MR-27-MASS-CG",
            "mass_min_kg": "750.0",
            "mass_max_kg": "960.0",
            "cg_x_bounds_m": ["-0.200", "0.220"],
        },
        "cad": {
            "format": "step_ap242",
            "parameters": [
                {"name": "mass_kg", "value": "978.000", "unit": "kg", "source_kind": "step_ap242"},
                {"name": "cg_x_m", "value": "0.265", "unit": "m", "source_kind": "step_ap242"},
            ],
        },
        "fem": {
            "format": "nastran_bdf",
            "parameters": [
                {"name": "mass_kg", "value": "982.000", "unit": "kg", "source_kind": "nastran_bdf"},
                {"name": "cg_x_m", "value": "0.240", "unit": "m", "source_kind": "nastran_bdf"},
                {
                    "name": "thrust_n",
                    "value": "14800.000",
                    "unit": "N",
                    "source_kind": "nastran_bdf",
                },
            ],
        },
        "fem_f06": {
            "format": "nastran_f06",
            "gpwg_mass_kg": "982.000",
            "parameters": [
                {
                    "name": "spc_reaction_n",
                    "value": "13950.000",
                    "unit": "N",
                    "source_kind": "nastran_f06",
                },
                {
                    "name": "thrust_n",
                    "value": "14800.000",
                    "unit": "N",
                    "source_kind": "nastran_f06",
                },
            ],
        },
        "report": {
            "blocks": [
                {
                    "page_no": 4,
                    "bbox": [72.0, 210.0, 490.0, 232.0],
                    "text": (
                        "Stress Dossier Rev C: mass = 950 kg, cg_x = 0.180 m, resultant = 14800 N."
                    ),
                }
            ]
        },
    }


def _build_daemon_runner(ledger: Any, budget: OvernightBudget) -> DaemonRunner:
    runner = DaemonRunner(ledger, budget=budget)

    def _handle_artifact(job: dict[str, Any], checkpoint: Any) -> dict[str, Any]:
        payload = job["payload"]
        fpath = Path(str(payload["file_path"]))
        checkpoint({"stage": "reading_file", "filename": fpath.name})
        if not fpath.is_file():
            return {"status": "skipped_missing", "edge_tokens": 0, "cloud_tokens": 0}
        from evidence_ingest.router import ingest_bytes

        raw = fpath.read_bytes()
        parsed = ingest_bytes(raw, fpath.name)
        checkpoint({"stage": "ingested", "media_type": parsed["media_type"]})
        return {
            "media_type": parsed["media_type"],
            "source_hash": parsed["source_hash"],
            "block_count": len(parsed.get("blocks") or []),
            "edge_tokens": min(1500, max(120, len(raw) // 16)),
            "cloud_tokens": 0,
        }

    def _handle_git(job: dict[str, Any], checkpoint: Any) -> dict[str, Any]:
        payload = job["payload"]
        checkpoint({"stage": "git_audited", "branch": payload.get("branch")})
        changed = payload.get("changed_files") or []
        return {
            "branch": payload.get("branch"),
            "commit_sha": payload.get("commit_sha"),
            "changed_count": len(changed),
            "edge_tokens": 200 + 40 * len(changed),
            "cloud_tokens": 0,
        }

    runner.register_handler("artifact_ingest_audit", _handle_artifact)
    runner.register_handler("git_branch_audit", _handle_git)
    return runner


def run_overnight_cycle(
    ledger: Any,
    *,
    watch_dirs: list[Path | str] | None = None,
    git_repo: Path | str | None = None,
    git_base: str = "master",
    cross_artifact_inputs: dict[str, Any] | None = None,
    nafems_inputs: dict[str, Any] | None = None,
    run_fuzzer: bool = True,
    quarantine_dir: Path | None = None,
    budget: OvernightBudget | None = None,
    actor_id: str = "overnight_worker",
    webhook_transport: Any | None = None,
    use_showcase_if_empty: bool = False,
) -> dict[str, Any]:
    """Run full overnight verification: watchers -> queue -> cross-artifact -> red-team."""
    run_id = f"run_{secrets.token_hex(6)}"
    now_ts = _now_iso()
    effective_budget = budget or OvernightBudget()

    watcher_summary: dict[str, Any] = {"folders": None, "git": None}
    if watch_dirs:
        watcher_summary["folders"] = FolderWatcher(watch_dirs).scan_and_enqueue(ledger)
    if git_repo:
        watcher_summary["git"] = GitWatcher(git_repo, base_branch=git_base).scan_and_enqueue(ledger)

    runner = _build_daemon_runner(ledger, effective_budget)
    queue_summary = runner.run_pending()

    # Cross-artifact audit
    ca_inputs = cross_artifact_inputs
    if ca_inputs is None and use_showcase_if_empty:
        ca_inputs = default_showcase_artifacts()

    cross_report: dict[str, Any] | None = None
    if ca_inputs is not None:
        cross_report = audit_cross_artifact_consistency(
            ledger,
            requirements=ca_inputs.get("requirements"),
            cad=ca_inputs.get("cad"),
            fem=ca_inputs.get("fem"),
            fem_f06=ca_inputs.get("fem_f06"),
            report=ca_inputs.get("report"),
            invalidate_cells=True,
            actor_id=actor_id,
            created_at=now_ts,
            webhook_transport=webhook_transport,
        )

    critic_report: dict[str, Any] | None = None
    attacker_report: dict[str, Any] | None = None
    if run_fuzzer:
        critic_report = run_envelope_critic()
        attacker_report = run_bench_attacker(quarantine_dir=quarantine_dir)

    # Persist structured findings into overnight_findings table for Morning Briefing 08:00 AM
    recorded_findings: list[dict[str, Any]] = []
    ledger_events = ledger.events()
    latest_calc_hash = ""
    for ev in reversed(ledger_events):
        if ev["body"]["event_type"] == "calc":
            latest_calc_hash = ev["event_hash"]
            break

    if cross_report is not None:
        for disc in cross_report["discrepancies"]:
            target_cid = (
                cross_report["invalidated_cell_ids"][0]
                if cross_report["invalidated_cell_ids"]
                else None
            )
            f_row = {
                "finding_id": f"ca_{disc['discrepancy_id']}",
                "run_id": run_id,
                "category": disc["category"],
                "severity": disc["severity"],
                "risk_score": _risk_score_for_item(disc["category"], disc["severity"]),
                "title": disc["title"],
                "summary": disc["summary"],
                "before": disc["before"],
                "after": disc["after"],
                "target_event_hash": latest_calc_hash or None,
                "cell_id": target_cid,
                "status": "open",
                "created_at": now_ts,
            }
            if hasattr(ledger, "queue"):
                ledger.queue.save_overnight_finding(f_row)
            recorded_findings.append(f_row)

    if critic_report is not None:
        for prop in critic_report["proposals"]:
            f_row = {
                "finding_id": prop["proposal_id"],
                "run_id": run_id,
                "category": "smt_counterexample",
                "severity": "CRITICAL",
                "risk_score": _risk_score_for_item("ms_negative", "CRITICAL", "-0.05"),
                "title": f"Red-Team `envelope_critic`: Contraejemplo {prop['property']}",
                "summary": f"{prop['reason']} -> {prop['counterexample']}",
                "before": {"property": prop["property"], "status": "assumed_safe"},
                "after": {
                    "proof_status": prop["proof_status"],
                    "counterexample": prop["counterexample"],
                },
                "target_event_hash": latest_calc_hash or None,
                "cell_id": None,
                "status": "open",
                "created_at": now_ts,
            }
            if hasattr(ledger, "queue"):
                ledger.queue.save_overnight_finding(f_row)
            recorded_findings.append(f_row)

    if attacker_report is not None:
        for rf in attacker_report["ranked_findings"][:12]:
            ms_mut = rf.get("mutated_ms")
            is_neg = ms_mut is not None and Decimal(str(ms_mut)) < Decimal("0")
            cat = "ms_negative" if is_neg else "adversarial_fuzzer"
            fid = (
                "fuzz_"
                + hashlib.sha256(
                    f"{rf['method_id']}:{rf['attack_vector']}:{rf.get('field')}".encode()
                ).hexdigest()[:12]
            )
            f_row = {
                "finding_id": fid,
                "run_id": run_id,
                "category": cat,
                "severity": rf["severity"],
                "risk_score": _risk_score_for_item(cat, rf["severity"], ms_mut),
                "title": f"[{rf['method_id']}] {rf['attack_vector']}",
                "summary": rf["summary"],
                "before": rf.get("before") or {},
                "after": rf.get("after") or {},
                "target_event_hash": latest_calc_hash or None,
                "cell_id": None,
                "status": "open",
                "created_at": now_ts,
            }
            if hasattr(ledger, "queue"):
                ledger.queue.save_overnight_finding(f_row)
            recorded_findings.append(f_row)

    nafems_report: dict[str, Any] | None = None
    if nafems_inputs is not None and nafems_inputs.get("bdf_parsed") is not None:
        nafems_report = run_full_nafems_audit(
            bdf_parsed=nafems_inputs["bdf_parsed"],
            bdf_hash=str(nafems_inputs.get("bdf_hash") or ""),
            f06_parsed=nafems_inputs.get("f06_parsed"),
            f06_hash=str(nafems_inputs.get("f06_hash") or ""),
            report_blocks=nafems_inputs.get("report_blocks"),
            report_claims=nafems_inputs.get("report_claims"),
            report_hash=nafems_inputs.get("report_hash"),
            required_load_families=nafems_inputs.get("required_load_families"),
            rotor_rpm=nafems_inputs.get("rotor_rpm"),
            blade_count=int(nafems_inputs.get("blade_count", 4)),
            guard_band_pct=str(nafems_inputs.get("guard_band_pct", "10.0")),
            min_effective_mass_frac=str(nafems_inputs.get("min_effective_mass_frac", "0")),
            require_unit_system=bool(nafems_inputs.get("require_unit_system", False)),
        )
        for disc in nafems_report["property_drift"]["discrepancies"]:
            fid = (
                "nafems_prop_"
                + hashlib.sha256(f"{disc.get('pid')}:{disc.get('category')}".encode()).hexdigest()[
                    :12
                ]
            )
            f_row = {
                "finding_id": fid,
                "run_id": run_id,
                "category": disc["category"],
                "severity": disc["severity"],
                "risk_score": _risk_score_for_item(disc["category"], disc["severity"]),
                "title": f"NAFEMS Deriva PID {disc.get('pid')}: BDF vs Memoria PDF",
                "summary": (
                    f"BDF={disc.get('bdf_thickness_mm')} mm vs "
                    f"PDF={disc.get('report_thickness_mm')} mm"
                ),
                "before": {"bdf_thickness_mm": disc.get("bdf_thickness_mm")},
                "after": {"report_thickness_mm": disc.get("report_thickness_mm")},
                "target_event_hash": latest_calc_hash or None,
                "cell_id": None,
                "status": "open",
                "created_at": now_ts,
            }
            if hasattr(ledger, "queue"):
                ledger.queue.save_overnight_finding(f_row)
            recorded_findings.append(f_row)

    briefing = build_morning_briefing(ledger)
    return {
        "run_id": run_id,
        "completed_at": now_ts,
        "watchers": watcher_summary,
        "queue": queue_summary,
        "cross_artifact": cross_report,
        "nafems_audit": nafems_report,
        "envelope_critic": critic_report,
        "bench_attacker": attacker_report,
        "recorded_findings_count": len(recorded_findings),
        "briefing": briefing,
    }


_BRIEFING_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def build_morning_briefing(ledger: Any) -> dict[str, Any]:
    """Assemble 08:00 AM risk-sorted queue: MS < 0, ABSTAIN, CAD<->FEM<->PDF, stale cells."""
    head = ledger.head_hash() if hasattr(ledger, "head_hash") else ""
    tenant = str(getattr(ledger, "tenant_id", "default"))
    cache_key = (tenant, head)

    summary_fast = (
        ledger.coverage_summary_fast() if hasattr(ledger, "coverage_summary_fast") else None
    )
    event_count = int(summary_fast.get("event_count", 0)) if summary_fast else 0

    stored_findings = (
        ledger.queue.list_overnight_findings(limit=200) if hasattr(ledger, "queue") else []
    )
    # Only return cached snapshot if finding count/statuses haven't changed since last head hash
    finding_sig = tuple(
        (str(f["finding_id"]), str(f.get("status", "open"))) for f in stored_findings
    )
    cached = _BRIEFING_CACHE.get(cache_key)
    if cached is not None and cached.get("_finding_sig") == finding_sig:
        return dict(cached["payload"])

    if event_count > 5000 and hasattr(ledger, "query_events"):
        tail_offset = max(0, event_count - 500)
        q_res = ledger.query_events(limit=500, offset=tail_offset)
        events = [
            {
                "event_hash": ev["event_hash"],
                "prev_hash": ev["prev_hash"],
                "body": ev["body"],
            }
            for ev in q_res.get("events", [])
        ]
    else:
        events = ledger.events()
    cells = generate_cells()
    cell_rows = list_cells_with_status(events, cells=cells)
    stale_cells = [c for c in cell_rows if c.get("stale")]
    abstain_events = [ev for ev in events if ev["body"]["event_type"] == "abstain"]
    calc_events = [ev for ev in events if ev["body"]["event_type"] == "calc"]
    signoff_targets = {
        str(ev["body"]["payload"].get("target_event_hash") or "")
        for ev in events
        if ev["body"]["event_type"] == "human_signoff"
    }

    items: list[dict[str, Any]] = list(stored_findings)
    seen_ids = {item["finding_id"] for item in items}

    # Include any unsigned ABSTAIN or stale cell entries cleanly in the unified briefing queue
    for ev in reversed(abstain_events[-10:]):
        fid = f"abstain_{ev['event_hash'][:12]}"
        if fid in seen_ids or ev["event_hash"] in signoff_targets:
            continue
        seen_ids.add(fid)
        payload = ev["body"].get("payload") or {}
        items.append(
            {
                "finding_id": fid,
                "run_id": "ledger",
                "category": "abstain",
                "severity": "HIGH",
                "risk_score": _risk_score_for_item("abstain", "HIGH"),
                "title": (
                    f"ABSTAIN fail-closed: "
                    f"{payload.get('reason') or ev['body']['envelope'].get('method_version')}"
                ),
                "summary": f"Evento {ev['event_hash'][:12]} retenido para decision humana.",
                "before": {"status": "requested"},
                "after": {"status": "abstain", "reason": payload.get("reason", "unspecified")},
                "target_event_hash": ev["event_hash"],
                "cell_id": payload.get("cell_id"),
                "status": "open",
                "created_at": ev["body"]["created_at"],
            }
        )

    for cell in stale_cells[:15]:
        fid = f"stale_{cell['cell_id']}"
        if fid in seen_ids:
            continue
        seen_ids.add(fid)
        items.append(
            {
                "finding_id": fid,
                "run_id": "coverage",
                "category": "stale_cell",
                "severity": "HIGH",
                "risk_score": _risk_score_for_item("stale_cell", "HIGH"),
                "title": f"Celda Stale invalidada: {cell['cell_id']}",
                "summary": (
                    f"Invalidada {cell['invalidation_count']} vez(ces); "
                    "requiere recalculo/revision."
                ),
                "before": {"status": "calc"},
                "after": {
                    "status": "gap (stale)",
                    "invalidation_count": cell["invalidation_count"],
                },
                "target_event_hash": cell.get("evidence_event_hash")
                or (calc_events[-1]["event_hash"] if calc_events else None),
                "cell_id": cell["cell_id"],
                "status": "open",
                "created_at": _now_iso(),
            }
        )

    items.sort(
        key=lambda x: (
            0 if x.get("status") == "open" else 1,
            -int(x.get("risk_score", 0)),
        )
    )

    budget_usage = ledger.queue.get_budget_usage() if hasattr(ledger, "queue") else {}
    dlq_pending = (
        ledger.queue.list_webhook_dlq(status="dead_letter", limit=100)
        if hasattr(ledger, "queue")
        else []
    )
    daemon_jobs = ledger.queue.list_daemon_jobs(limit=50) if hasattr(ledger, "queue") else []
    tel_snap = get_telemetry().snapshot()

    open_items = [x for x in items if x.get("status") == "open"]
    result_payload = {
        "generated_at": _now_iso(),
        "executive_summary": {
            "total_queue_items": len(items),
            "open_items": len(open_items),
            "ms_negative_count": sum(1 for x in open_items if x["category"] == "ms_negative"),
            "cross_artifact_count": sum(
                1
                for x in open_items
                if "mass" in x["category"]
                or "cg_" in x["category"]
                or "fem_" in x["category"]
                or "pdf_" in x["category"]
                or "cross_artifact" in x["category"]
                or "nastran_" in x["category"]
            ),
            "abstain_count": sum(1 for x in open_items if x["category"] == "abstain"),
            "stale_cells_count": len(stale_cells),
            "daemon_jobs_completed": sum(1 for j in daemon_jobs if j["status"] == "completed"),
            "dlq_pending_count": len(dlq_pending),
            "budget_usage": budget_usage,
            "telemetry": tel_snap,
        },
        "queue": items,
    }
    if len(_BRIEFING_CACHE) >= 64:
        _BRIEFING_CACHE.pop(next(iter(_BRIEFING_CACHE)), None)
    _BRIEFING_CACHE[cache_key] = {"_finding_sig": finding_sig, "payload": result_payload}
    return result_payload


def batch_human_signoff(
    ledger: Any,
    *,
    finding_ids: list[str],
    actor_id: str,
    actor_role: str = "cve",
    statement: str = SIGN_OFF_STATEMENT,
    created_at: str | None = None,
    enforce_distinct_reviewer: bool = True,
) -> dict[str, Any]:
    """Perform audited batch human_signoff on reviewed briefing findings respecting SoD."""
    clean_actor = str(actor_id or "").strip()
    if not clean_actor:
        raise LedgerError("actor_id required for batch signoff")
    role_lower = str(actor_role).lower()
    if role_lower == "author" or role_lower not in {"cve", "admin", "human"}:
        raise LedgerError("cve_role_required")
    when = created_at or _now_iso()
    clean_stmt = statement or SIGN_OFF_STATEMENT

    all_events = ledger.events()
    ev_by_hash = {ev["event_hash"]: ev for ev in all_events}
    findings = (
        {f["finding_id"]: f for f in ledger.queue.list_overnight_findings(limit=500)}
        if hasattr(ledger, "queue")
        else {}
    )
    fallback_target = all_events[-1]["event_hash"] if all_events else ""

    signed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for fid in finding_ids:
        f = findings.get(fid)
        target_hash = (f.get("target_event_hash") if f else None) or fallback_target
        if not target_hash or target_hash not in ev_by_hash:
            rejected.append({"finding_id": fid, "reason": "no_target_event_in_ledger"})
            continue

        orig_author = str(ev_by_hash[target_hash]["body"].get("actor_id") or "")
        if enforce_distinct_reviewer and orig_author == clean_actor:
            rejected.append({"finding_id": fid, "reason": "self_signoff_prohibited"})
            continue

        signoff_inputs = {
            "target_event_hash": target_hash,
            "statement": SIGN_OFF_STATEMENT,
            "review_note": clean_stmt,
        }
        signoff_payload = {
            "actor_id": clean_actor,
            "target_event_hash": target_hash,
            "statement": SIGN_OFF_STATEMENT,
            "review_note": clean_stmt,
            "batch_finding_id": fid,
        }
        envelope = make_envelope(
            sources=[
                project_source("human-review", "https://aeroregu.local/signoff", "ASSUMPTION")
            ],
            method_version="human_signoff@1.0.0",
            inputs=signoff_inputs,
            confidence="deterministic",
            result=signoff_payload,
        )
        try:
            sig_hash = record(
                ledger,
                {
                    "event_type": "human_signoff",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": clean_actor,
                    "created_at": when,
                    "payload": signoff_payload,
                    "envelope": envelope,
                },
            )
            if hasattr(ledger, "queue") and fid in findings:
                ledger.queue.resolve_overnight_finding(
                    fid, signed_off_by=clean_actor, signed_off_at=when
                )
            signed.append(
                {
                    "finding_id": fid,
                    "target_event_hash": target_hash,
                    "signoff_event_hash": sig_hash,
                    "signed_off_by": clean_actor,
                }
            )
        except LedgerError as exc:
            rejected.append({"finding_id": fid, "reason": str(exc)})

    return {
        "signed_count": len(signed),
        "rejected_count": len(rejected),
        "signed": signed,
        "rejected": rejected,
    }
