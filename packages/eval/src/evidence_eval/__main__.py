from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from evidence_eval.b2 import b1_status, b3_status, b4_status, score_b2
from evidence_eval.b3_second import score_second
from evidence_eval.baseline import naive_assess
from evidence_eval.bench_snapshot import write_bench_snapshot
from evidence_eval.merge_gate import freeze_gate
from evidence_eval.quarantine import quarantine_status
from evidence_eval.quote_pipeline import quotes_ok, score_nasa_quotes
from evidence_eval.repro import write_manifest
from evidence_eval.s1 import (
    checker_single_faults_pass,
    naive_baseline_still_naive,
    public_summary,
    run_s1,
    write_report,
)
from evidence_eval.score import assert_holdout_frozen, load_split, score_cases


def _at(value: object, path: str) -> object:
    """Walk a dotted path. A missing step raises KeyError and does not echo the value."""
    if not path:
        return value
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(part)
        current = current[part]
    return current


def _env_dir(name: str) -> Path | None:
    override = os.environ.get(name, "").strip()
    if not override:
        return None
    return Path(override)


def _inside_repo(folder: Path) -> bool:
    from evidence_kernel.paths import repo_root

    try:
        folder.resolve().relative_to(repo_root().resolve())
    except ValueError:
        return False
    return True


def _sealed(fn):
    """Run a blind command. A failure report names the exception class and nothing else."""
    try:
        return fn()
    except Exception as exc:
        return {
            "scored": False,
            "stopped": type(exc).__name__,
            "read": False,
            "label": "NOT_VERIFIED",
            "note": "The scorer stopped. The case text is not in this report.",
        }


def _blind_dir(name: str) -> Path | None:
    """The engineer folder, or None when it must not be read."""
    folder = _env_dir(name)
    if folder is None:
        print(json.dumps({"variable": name, "set": False, "read": False}))
        return None
    if _inside_repo(folder):
        print(json.dumps({"variable": name, "set": True, "outside_repo": False, "read": False}))
        return None
    return folder


def repo_docs() -> Path:
    from evidence_kernel.paths import repo_root

    return repo_root() / "docs" / "benchmarks"


def _checker_failed(report: dict) -> bool:
    """A scored fault must be recall 1.0.

    Recall 0.0 means the fault was in the split and was missed. None means
    that fault had no cases. A missing key is the same absence. Neither
    absence is a miss, and neither lets a 0.0 through.
    """
    failed = False
    for value in report["deterministic_recall"].values():
        if value is not None and value != 1.0:
            failed = True
    for value in report.get("trace_recall", {}).values():
        if value is not None and value != 1.0:
            failed = True
    if report["llm_numeric_violation"] != 0:
        failed = True
    if _abstain_mismatch(report):
        failed = True
    if report["false_alarms"]:
        failed = True
    if _per_fault_false_alarm(report):
        failed = True
    return failed


def _per_fault_false_alarm(report: dict) -> bool:
    for value in report.get("false_alarm_by_fault", {}).values():
        hits, _, total = str(value).partition("/")
        if total == "" or hits != "0":
            return True
    return False


def _abstain_mismatch(report: dict) -> bool:
    total = report["missing_input_total"]
    return bool(total) and report["missing_input_ok"] != total


def _baseline_failed(report: dict) -> bool:
    """The naive baseline must miss every deterministic fault it is shown.

    A fault with no cases has recall None. That absence is not a catch.
    An abstain is not a detection, including when the checker abstains too.
    """
    failed = False
    for fault, value in report["deterministic_recall"].items():
        if value is None or value == 0.0:
            continue
        failed = True
        print(f"naive baseline unexpectedly caught {fault}: {value}", file=sys.stderr)
    if report["llm_numeric_violation"] != 0:
        failed = True
    if _abstain_mismatch(report):
        failed = True
    if report["false_alarms"] or _per_fault_false_alarm(report):
        failed = True
    return failed


def _ledger_numbers_ok(benchmarks: dict) -> bool:
    b2 = benchmarks.get("b2") or {}
    for key in ("agent_chain", "two_pack_probe", "span_probe"):
        block = b2.get(key) or {}
        if isinstance(block, dict) and block.get("llm_numeric_violation", 0) != 0:
            return False
    quarantine = benchmarks.get("quarantine_duplicate_citation") or {}
    if isinstance(quarantine, dict) and quarantine.get("llm_numeric_violation", 0) != 0:
        return False
    second = benchmarks.get("b3_second") or {}
    if second.get("scored") and second.get("llm_numeric_violation", 0) != 0:
        return False
    b3 = benchmarks.get("b3") or {}
    if b3.get("expert_holdout") and b3.get("expert_holdout_llm_numeric_violation", 0) != 0:
        return False
    if b3.get("llm_numeric_violation", 0) != 0:
        return False
    b4 = benchmarks.get("b4") or {}
    drill_report = b4.get("drill") or {}
    if isinstance(drill_report, dict) and drill_report.get("llm_numeric_violation", 0) != 0:
        return False
    for key in ("as365", "public_archive"):
        series = b4.get(key) or {}
        if isinstance(series, dict) and series.get("llm_numeric_violation", 0) != 0:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_eval")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("--split", default="dev")
    base = sub.add_parser("baseline")
    base.add_argument("--split", default="dev")
    sub.add_parser("bench")
    sub.add_parser("validate-b1")
    sub.add_parser("score-blind-b1")
    sub.add_parser("score-blind-b2")
    sub.add_parser("score-blind-b3")
    sub.add_parser("hash-blind-dirs")
    hash_inputs = sub.add_parser("hash-inputs")
    hash_inputs.add_argument("path")
    hash_inputs.add_argument("--at", default="")
    hash_file = sub.add_parser("hash-file")
    hash_file.add_argument("path")
    sub.add_parser("external-public")
    sub.add_parser("ood-bench")
    args = parser.parse_args(argv)
    if args.command == "validate-b1":
        from evidence_eval.expert_validate import validate_b1

        folder = _blind_dir("B1_EXPERT_DIR")
        if folder is None:
            return 2
        report = _sealed(lambda: validate_b1(folder))
        print(json.dumps(report, indent=2))
        return 0 if report.get("ready") else 2
    if args.command == "score-blind-b1":
        from evidence_eval.expert_blind import score_blind_b1

        folder = _blind_dir("B1_EXPERT_DIR")
        if folder is None:
            return 2
        report = _sealed(lambda: score_blind_b1(folder))
        print(json.dumps(report, indent=2))
        return 0 if report.get("scored") else 2
    if args.command == "score-blind-b2":
        from evidence_eval.b2 import score_expert_holdout

        folder = _blind_dir("B2_EXPERT_DIR")
        if folder is None:
            return 2
        report = _sealed(lambda: score_expert_holdout(folder))
        print(json.dumps(report, indent=2))
        return 0 if report.get("scored") else 2
    if args.command == "score-blind-b3":
        from evidence_eval.b3 import score_b3_holdout

        folder = _blind_dir("B3_EXPERT_DIR")
        if folder is None:
            return 2
        report = _sealed(lambda: score_b3_holdout(folder))
        print(json.dumps(report, indent=2))
        return 0 if report.get("scored") else 2
    if args.command == "hash-blind-dirs":
        from evidence_eval.expert_blind import expert_tree_hash

        found: dict[str, object] = {}
        for name in ("B1_EXPERT_DIR", "B2_EXPERT_DIR", "B3_EXPERT_DIR"):
            folder = _env_dir(name)
            if folder is None:
                continue
            if _inside_repo(folder):
                found[name] = {"present": True, "outside_repo": False, "read": False}
                continue
            if not folder.is_dir():
                found[name] = {"present": False, "files": 0}
                continue
            try:
                found[name] = {"present": True, **expert_tree_hash(folder)}
            except Exception as exc:
                found[name] = {
                    "present": True,
                    "stopped": type(exc).__name__,
                    "read": False,
                }
        print(json.dumps(found, indent=2))
        blocked = any(
            item.get("present") is False or item.get("read") is False for item in found.values()
        )
        if not found or blocked:
            return 2
        return 0
    if args.command == "hash-inputs":
        from evidence_kernel.canonical import inputs_hash

        path = Path(args.path)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            selected = _at(loaded, str(args.at))
            digest = inputs_hash(selected)
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            print(type(exc).__name__, file=sys.stderr)
            return 2
        print(digest)
        return 0
    if args.command == "hash-file":
        import hashlib

        path = Path(args.path)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            print(type(exc).__name__, file=sys.stderr)
            return 2
        print(digest)
        return 0
    if args.command == "external-public":
        from evidence_eval.external_public import external_public_report, render_external_markdown

        report = external_public_report()
        out_dir = repo_docs()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "external_public_latest.json").write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "external_public_latest.md").write_text(
            render_external_markdown(report),
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("acquired") else 2
    if args.command == "ood-bench":
        from evidence_eval.ood_bench import audit_path, ood_report, render_ood_audit

        report = ood_report()
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_ood_audit(report), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report.get("acquired") else 2
    if args.command == "bench":
        write_manifest()
        cases = load_split("dev")
        checker = score_cases(cases)
        baseline = score_cases(cases, assess_fn=naive_assess)
        print(json.dumps({"checker": checker, "naive_baseline": baseline}, indent=2))
        print(
            "expert_holdout was not scored. It stays empty until the domain expert writes it.",
            file=sys.stderr,
        )
        s1 = run_s1()
        write_report(s1)
        print(
            json.dumps(
                {
                    "s1_cases": s1["cases"],
                    "s1_checker_single_faults_pass": checker_single_faults_pass(s1),
                    "s1_naive_still_naive": naive_baseline_still_naive(s1),
                    "s1_compound_complete": s1["compound_complete"],
                    "s1_compound_complete_is_a_pass": s1["compound_complete_is_a_pass"],
                },
                indent=2,
            )
        )
        s1_ok = (
            checker_single_faults_pass(s1)
            and naive_baseline_still_naive(s1)
            and s1["compound_complete_is_a_pass"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            from evidence_kernel.ledger import Ledger

            quote_ledger = Ledger(Path(tmp) / "quotes.sqlite3", "bench")
            quotes = score_nasa_quotes(quote_ledger)
        benchmarks = {
            "b1": b1_status(),
            "dev": {
                "cases": checker["cases"],
                "label": "ESTIMATE",
                "false_alarm_by_fault": checker["false_alarm_by_fault"],
                "false_alarm_by_fault_ci95": checker["false_alarm_by_fault_ci95"],
                "abstention_by_fault": checker["abstention_by_fault"],
                "abstention_by_fault_ci95": checker["abstention_by_fault_ci95"],
                "fault_counts": checker["fault_counts"],
                "note": checker["note"],
            },
            "b2": score_b2(),
            "b3": b3_status(),
            "b3_second": score_second(),
            "b3_quotes": quotes,
            "b4": b4_status(),
            "quarantine_duplicate_citation": quarantine_status(),
            "s1": public_summary(s1),
            "programme": freeze_gate(),
        }
        write_bench_snapshot(
            benchmarks,
            note="ESTIMATE: written by make bench in one process.",
        )
        print(json.dumps({"benchmarks": benchmarks}, indent=2))
        smoke_ok = not _checker_failed(checker) and not _baseline_failed(baseline)
        numbers_ok = _ledger_numbers_ok(benchmarks)
        headings_ok = benchmarks["b2"].get("public_headings_only") is True
        return 0 if smoke_ok and s1_ok and quotes_ok(quotes) and numbers_ok and headings_ok else 1
    assess_fn = naive_assess if args.command == "baseline" else None
    if args.split == "holdout":
        assert_holdout_frozen()
        print(
            "bench/holdout is same-author smoke data. It is not scored. "
            "Expert cases belong in bench/b1/expert_holdout and are not read here.",
            file=sys.stderr,
        )
        return 2
    if args.split == "b1":
        print("expert holdout is not scored from this command", file=sys.stderr)
        return 2
    report = score_cases(load_split(args.split), assess_fn=assess_fn)
    print(json.dumps(report, indent=2))
    if args.command == "baseline":
        return 1 if _baseline_failed(report) else 0
    return 1 if _checker_failed(report) else 0


if __name__ == "__main__":
    sys.exit(main())
