"""Reproduce score, S1 and a ledger tamper check. Writes only under audit/repro/out.

Does not call write_report or write_bench_snapshot, so docs/benchmarks stays untouched.
S1_SEED is a label in evidence_eval.s1. iter_cases does not take a seed.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from evidence_eval.s1 import S1_SEED, public_summary, run_s1
from evidence_eval.score import load_split, score_cases
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)


def _dump(name: str, payload: object) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def score_twice() -> dict:
    runs = []
    for index in (1, 2):
        started = time.perf_counter()
        report = score_cases(load_split("dev"))
        elapsed = round(time.perf_counter() - started, 3)
        slim = {
            "run": index,
            "elapsed_s": elapsed,
            "false_alarms": report["false_alarms"],
            "llm_numeric_violation": report["llm_numeric_violation"],
            "deterministic_recall": report["deterministic_recall"],
            "mismatches": report["mismatches"],
            "missing_input_ok": report["missing_input_ok"],
            "missing_input_total": report["missing_input_total"],
        }
        runs.append(slim)
        print("score", slim, flush=True)
    return {
        "identical": runs[0]["deterministic_recall"] == runs[1]["deterministic_recall"]
        and runs[0]["llm_numeric_violation"] == runs[1]["llm_numeric_violation"]
        and runs[0]["false_alarms"] == runs[1]["false_alarms"],
        "runs": runs,
    }


def s1_twice() -> dict:
    runs = []
    for index in (1, 2):
        started = time.perf_counter()
        summary = public_summary(run_s1())
        elapsed = round(time.perf_counter() - started, 3)
        summary["run"] = index
        summary["elapsed_s"] = elapsed
        runs.append(summary)
        print(
            "s1",
            index,
            elapsed,
            summary["cases"],
            summary["llm_numeric_violation"],
            summary["false_alarm_rate"],
            flush=True,
        )
    left = {key: runs[0][key] for key in runs[0] if key not in {"run", "elapsed_s"}}
    right = {key: runs[1][key] for key in runs[1] if key not in {"run", "elapsed_s"}}
    return {
        "seed_constant": S1_SEED,
        "seed_changes_output": False,
        "identical": left == right,
        "runs": runs,
    }


def tamper() -> dict:
    path = OUT / "tamper.sqlite3"
    if path.exists():
        path.unlink()
    ledger = Ledger(path, "audit")
    envelope = make_envelope(
        sources=[project_source("audit", "https://aeroregu.local/audit", "ASSUMPTION")],
        method_version="audit@1.0.0",
        inputs={"marker": "one"},
        confidence="deterministic",
        result={"marker": "one"},
    )
    digest = record(
        ledger,
        {
            "event_type": "calc",
            "tenant_id": "audit",
            "actor_id": "author",
            "created_at": "2026-11-09T00:00:00Z",
            "payload": {"marker": "one"},
            "envelope": envelope,
        },
    )
    intact = ledger.verify()
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET body_json = '{\"tampered\":true}' WHERE seq = 1")
    conn.commit()
    conn.close()
    detected = ledger.verify() is False
    return {
        "appended_hash_prefix": digest[:12],
        "intact_before": intact,
        "tamper_detected": detected,
    }


def main() -> None:
    score = score_twice()
    _dump("score_dev_two_runs.json", score)
    tamper_report = tamper()
    _dump("ledger_tamper.json", tamper_report)
    print("tamper", tamper_report, flush=True)
    s1 = s1_twice()
    _dump("s1_two_runs.json", s1)
    print("DONE identical_s1", s1["identical"], flush=True)


if __name__ == "__main__":
    main()
