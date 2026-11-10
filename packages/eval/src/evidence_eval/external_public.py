"""Score published datasets that this repository did not generate.

The files stay under data/external and are not rewritten. Reports contain
counts and unit tokens only. They do not copy problem statements, numeric
answers, or requirement text.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evidence_calc.units import dimension_exponents
from evidence_kernel.paths import repo_root

from evidence_eval.b2 import predict
from evidence_eval.score import wilson

UNITSAFE_SHA256 = "f7ba395958f70cfb80ff3a2559f9a428dc038cac06d35bf15a71d94f4ce92a8a"
QURE_SHA256 = "c6a0c872873ba54028b97361c4cf1d5ad488bdea622a922cbee33265814925d6"
DRONOLOGY_SHA256 = {
    "traces.csv": "445549cffea0e586cf4bede807e7200568f536c3c743c612142b9eed549e26d2",
    "artifacts.csv": "a41ce5b4e12c962d8717038f598fef4f696f7fcb6621d7a65a147eea4aa3420a",
    "matrices.csv": "75db13f7eac59f945ac22efd1ac71f5637c2aaeba50ac7ebfe11f360370594dc",
}

_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_BASES = set("MLTIΘNJA")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_si_signature(text: str) -> dict[str, int] | None:
    """Parse a UnitSafe SI signature. Returns None when the token is not that grammar."""
    if text == "dimensionless":
        return {}
    exponents: dict[str, int] = {}
    for part in text.split("·"):
        token = part.strip()
        if not token or token[0] not in _BASES:
            return None
        raw = token[1:].translate(_SUPER)
        try:
            exponent = int(raw) if raw else 1
        except ValueError:
            return None
        exponents[token[0]] = exponents.get(token[0], 0) + exponent
    return {key: value for key, value in exponents.items() if value != 0}


def _signature_split(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Count answer units that match the published signature. This does not score the row."""
    same = differ = unparsed = 0
    for row in rows:
        unit = str((row.get("answer") or {}).get("unit", ""))
        signature = parse_si_signature(str(row.get("si_signature", "")))
        got = read_unit_exponents(unit)
        if signature is None or got is None:
            unparsed += 1
        elif got == signature:
            same += 1
        else:
            differ += 1
    return same, differ, unparsed


def _exponents(exponents: dict[str, int]) -> str:
    """Stable text for a dimension map. Empty means dimensionless."""
    return ",".join(f"{key}:{value}" for key, value in sorted(exponents.items())) or "dimensionless"


def read_unit_exponents(unit: str) -> dict[str, int] | None:
    """Read dimensions for a published unit token. Does not change the token's meaning."""
    candidates = [unit]
    if "·" in unit:
        candidates.append(unit.replace("·", "*"))
        candidates.append(unit.replace("·", " "))
    if unit.casefold() == "dimensionless":
        candidates.append("dimensionless")
    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        exponents = dimension_exponents(name)
        if exponents is not None:
            return exponents
    return None


def score_unitsafe_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare published answer units with published signatures.

    Conversion rows only. Must-fail rows have quantity kind 'invalid', so their
    signature is not treated as the dimension of a valid answer. Numeric answers
    are not read. Kind-of-quantity refusals are not scored: this checker has no
    such verdict.
    """
    conversion = [row for row in rows if row.get("expected_error") is None]
    matched = 0
    mismatched = 0
    unparsed = 0
    bad_signature = 0
    scibench = 0
    mismatch_units: Counter[str] = Counter()
    mismatch_detail: Counter[tuple[str, str, str]] = Counter()
    unparsed_units: Counter[str] = Counter()
    for row in rows:
        source = row.get("source")
        if isinstance(source, dict) and source.get("dataset") == "SciBench":
            scibench += 1
    for row in conversion:
        signature = parse_si_signature(str(row.get("si_signature", "")))
        if signature is None:
            bad_signature += 1
            continue
        unit = str((row.get("answer") or {}).get("unit", ""))
        got = read_unit_exponents(unit)
        if got is None:
            unparsed += 1
            unparsed_units[unit] += 1
            continue
        if got == signature:
            matched += 1
        else:
            mismatched += 1
            mismatch_units[unit] += 1
            mismatch_detail[(unit, _exponents(got), _exponents(signature))] += 1
    dimension_rows = [row for row in rows if row.get("expected_error") == "dimension_mismatch"]
    koq_rows = [row for row in rows if row.get("expected_error") == "koq_mismatch"]
    dimension_same, dimension_differ, dimension_unparsed = _signature_split(dimension_rows)
    koq_same, koq_differ, koq_unparsed = _signature_split(koq_rows)
    expected_errors = Counter(
        "conversion" if row.get("expected_error") is None else str(row.get("expected_error"))
        for row in rows
    )
    parsed = matched + mismatched
    return {
        "dataset": "radiativity/UnitSafe",
        "license": "Apache-2.0",
        "rows": len(rows),
        "scibench_rows": scibench,
        "expected_error": dict(expected_errors),
        "conversion_rows": len(conversion),
        "signature_match": matched,
        "signature_mismatch": mismatched,
        "unit_unparsed": unparsed,
        "bad_signature": bad_signature,
        "parsed_agreement": f"{matched}/{parsed}" if parsed else "0/0",
        "parsed_agreement_ci95": wilson(matched, parsed),
        "mismatch_units": dict(mismatch_units.most_common()),
        "mismatch_detail": [
            {"unit": unit, "pint": pint, "published": published, "rows": count}
            for (unit, pint, published), count in sorted(mismatch_detail.items())
        ],
        "unparsed_units": dict(unparsed_units.most_common()),
        "koq_rows": expected_errors.get("koq_mismatch", 0),
        "koq_scored": 0,
        "dimension_mismatch_rows": expected_errors.get("dimension_mismatch", 0),
        "dimension_mismatch_scored": 0,
        "dimension_mismatch_signature_same": dimension_same,
        "dimension_mismatch_signature_differ": dimension_differ,
        "dimension_mismatch_signature_unparsed": dimension_unparsed,
        "koq_signature_same": koq_same,
        "koq_signature_differ": koq_differ,
        "koq_signature_unparsed": koq_unparsed,
        "numeric_answers_scored": 0,
        "label": "ESTIMATE",
    }


def is_gold_link(
    requirement_id: str, evidence_id: str, gold: set[tuple[str | None, str | None]]
) -> bool:
    """The published order is source then target. The swapped order is not a hit."""
    return (requirement_id, evidence_id) in gold


def score_dronology(folder: Path) -> dict[str, Any]:
    """Run the existing heading linker on Dronology. Do not copy artifact text."""
    with (folder / "traces.csv").open(encoding="utf-8", newline="") as handle:
        traces = list(csv.DictReader(handle))
    with (folder / "artifacts.csv").open(encoding="utf-8", newline="") as handle:
        artifacts = list(csv.DictReader(handle))
    gold_pairs = {(row.get("s_id"), row.get("t_id")) for row in traces if row.get("label") == "1"}
    predicted = 0
    hits = 0
    for artifact in artifacts:
        links, _flags = predict(str(artifact.get("content") or ""), [])
        for link in links:
            predicted += 1
            if is_gold_link(link["requirement_id"], link["evidence_id"], gold_pairs):
                hits += 1
    labels = Counter(row.get("label") for row in traces)
    gold = len(gold_pairs)
    return {
        "dataset": "thearod5/dronology",
        "license": "MIT",
        "artifacts": len(artifacts),
        "traces": len(traces),
        "trace_labels": dict(labels),
        "gold_positive_links": gold,
        "negative_labels": sum(count for label, count in labels.items() if label != "1"),
        "predicted_links": predicted,
        "gold_hits": hits,
        "linker_recall": f"{hits}/{gold}",
        "false_alarms": f"{predicted - hits}/{predicted}",
        "false_alarm_ci95": wilson(predicted - hits, predicted),
        "precision": None,
        "precision_reason": "The published trace file has no negative labels.",
        "label": "ESTIMATE",
        "note": (
            "predict() only links eight public headings, and only next to an ev- id. "
            "Dronology identifiers are not those headings. A reversed pair is not a hit. "
            "This is that linker on someone else's gold, not a new trace-recovery model."
        ),
    }


def load_unitsafe(path: Path) -> list[dict[str, Any]]:
    actual = file_sha256(path)
    if actual != UNITSAFE_SHA256:
        raise ValueError("UnitSafe file hash does not match the pin")
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(rows) != 500:
        raise ValueError("UnitSafe row count is not 500")
    return rows


def score_qure(path: Path) -> dict[str, Any]:
    """Count QuRE labels. Requirement sentences are not returned."""
    if file_sha256(path) != QURE_SHA256:
        raise ValueError("QuRE file hash does not match the pin")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ok_tokens = {row["weak_word"].strip() for row in rows if row["defect"] == "ok"}
    defect_tokens = {row["weak_word"].strip() for row in rows if row["defect"] == "defect"}
    return {
        "dataset": "10.5281/zenodo.16049822",
        "license": "CC-BY-4.0",
        "rows": len(rows),
        "defect": sum(row["defect"] == "defect" for row in rows),
        "ok": sum(row["defect"] == "ok" for row in rows),
        "weak_word_tokens": len(ok_tokens | defect_tokens),
        "weak_word_on_both_labels": len(ok_tokens & defect_tokens),
        "weak_word_only_on_ok": sorted(ok_tokens - defect_tokens),
        "weak_word_only_on_defect": sorted(defect_tokens - ok_tokens),
        "requirements_copied": 0,
        "scored": 0,
        "sha256": QURE_SHA256,
        "label": "ESTIMATE",
        "note": (
            "The weak_word token is not the defect label. Requirement text is not in this report."
        ),
    }


def load_checked_dronology(folder: Path) -> None:
    for name, expected in DRONOLOGY_SHA256.items():
        actual = file_sha256(folder / name)
        if actual != expected:
            raise ValueError(f"{name} hash does not match the pin")


def external_public_report(root: Path | None = None) -> dict[str, Any]:
    base = root or (repo_root() / "data" / "external")
    unitsafe_path = base / "unitsafe" / "test.jsonl"
    dronology_path = base / "dronology"
    missing = [
        str(path)
        for path in (unitsafe_path, dronology_path / "traces.csv", dronology_path / "artifacts.csv")
        if not path.is_file()
    ]
    if missing:
        return {
            "acquired": False,
            "missing": missing,
            "label": "NOT_VERIFIED",
        }
    rows = load_unitsafe(unitsafe_path)
    load_checked_dronology(dronology_path)
    unitsafe = score_unitsafe_rows(rows)
    unitsafe["sha256"] = UNITSAFE_SHA256
    dronology = score_dronology(dronology_path)
    dronology["sha256"] = DRONOLOGY_SHA256
    from evidence_eval.jcs_vectors import score_jcs

    jcs_path = base / "jcs"
    jcs: dict[str, Any] = {"acquired": False, "label": "NOT_VERIFIED"}
    if (jcs_path / "input").is_dir():
        jcs = {"acquired": True, **score_jcs(jcs_path)}
    from evidence_eval.nist_sp811 import score_nist_b8

    nist_path = base / "nist-sp811" / "b8.md"
    nist: dict[str, Any] = {"acquired": False, "label": "NOT_VERIFIED"}
    if nist_path.is_file():
        nist = {"acquired": True, **score_nist_b8(nist_path)}
    qure_path = base / "qure" / "QuRE.csv"
    qure: dict[str, Any] = {"acquired": False, "label": "NOT_VERIFIED", "scored": 0}
    if qure_path.is_file():
        qure = {"acquired": True, **score_qure(qure_path)}
    return {
        "acquired": True,
        "date": "2026-11-09",
        "unitsafe": unitsafe,
        "dronology": dronology,
        "jcs": jcs,
        "nist_b8": nist,
        "qure": qure,
        "expert_holdout_written_by_this_run": False,
        "label": "ESTIMATE",
        "note": (
            "These files were published by other people. This run did not rewrite them. "
            "They do not replace a blind set written by another engineer."
        ),
    }


def _qure_lines(qure: dict[str, Any]) -> str:
    if not qure.get("acquired"):
        return "QuRE was not on disk. NOT VERIFIED."
    return (
        "Source: https://zenodo.org/records/16049822. Licence CC BY 4.0. "
        f"Rows: {qure['rows']}. Defect: {qure['defect']}. Ok: {qure['ok']}. "
        f"Weak-word tokens: {qure['weak_word_tokens']}. "
        f"On both labels: {qure['weak_word_on_both_labels']}. "
        f"Only on ok: {qure['weak_word_only_on_ok']}. "
        f"Only on defect: {qure['weak_word_only_on_defect']}. "
        f"Scored: {qure['scored']}. Requirement sentences are not copied. Not B1."
    )


def _nist_lines(nist: dict[str, Any]) -> str:
    if not nist.get("acquired"):
        return "NIST SP 811 Appendix B.8 was not on disk. NOT VERIFIED."
    return (
        "Source: the NIST Guide to the SI, Appendix B.8, retrieved 2026-11-09. "
        f"Rows: {nist['rows']}. No trailing symbol: {nist['no_trailing_symbol']}. "
        f"Symbol unknown to pint: {nist['symbol_unknown']}. "
        f"Interval factor agrees: {nist['agree']}. "
        f"Same symbols, another printed definition: {nist['other_definition']}. "
        f"Disagree: {nist['disagree']} {nist.get('disagree_detail', nist['disagree_pairs'])}. "
        f"Incompatible dimensions: {nist['incompatible']}. "
        "Boldface exact factors were not in the text fetch. "
        "This is not B1."
    )


def _jcs_lines(jcs: dict[str, Any]) -> str:
    if not jcs.get("acquired"):
        return "JCS vectors were not on disk. NOT VERIFIED."
    return (
        "Source: https://github.com/cyberphone/json-canonicalization testdata. "
        "The LICENSE file, retrieved 2026-11-09, says Apache-2.0. "
        f"Files with no float matched: {jcs['matched']}. "
        f"Files skipped because they contain a fractional number: {jcs['float_skipped']}. "
        f"Mismatches: {jcs['mismatched']}. "
        f"UTF-8 bytes equal to the published outhex image: {jcs.get('byte_matched', [])}. "
        f"Byte mismatches: {jcs.get('byte_mismatched', [])}. "
        "The ledger hashes those bytes. This is not a full RFC 8785 pass. Floats stay rejected."
    )


def render_external_markdown(report: dict[str, Any]) -> str:
    if not report.get("acquired"):
        return "# External public benchmarks\n\nNOT VERIFIED. The pinned files are not on disk.\n"
    unitsafe = report["unitsafe"]
    dronology = report["dronology"]
    lines = [
        "# External public benchmarks",
        "",
        "Date: 2026-11-09.",
        "ESTIMATE: counts from the pinned files on this machine.",
        "VERIFIED: the SHA-256 pins matched the files that were scored.",
        "The problems and the requirement sentences are not copied here.",
        "This run did not write bench/b1/expert_holdout.",
        "",
        "## UnitSafe",
        "",
        "Source: https://huggingface.co/datasets/radiativity/UnitSafe",
        "Licence read from the dataset API on 2026-11-09: Apache-2.0.",
        f"SHA-256: {unitsafe['sha256']}",
        f"Rows: {unitsafe['rows']}. Conversion: {unitsafe['conversion_rows']}.",
        f"Must-fail dimension_mismatch: {unitsafe['dimension_mismatch_rows']}, scored: "
        f"{unitsafe['dimension_mismatch_scored']}. "
        "On those rows the published signature matches the answer unit on "
        f"{unitsafe.get('dimension_mismatch_signature_same', 0)}, differs on "
        f"{unitsafe.get('dimension_mismatch_signature_differ', 0)}, "
        "and does not parse on "
        f"{unitsafe.get('dimension_mismatch_signature_unparsed', 0)}. "
        "The label is not a unit-versus-signature test.",
        f"Must-fail koq_mismatch: {unitsafe['koq_rows']}, scored: {unitsafe['koq_scored']}.",
        f"Numeric answers scored: {unitsafe['numeric_answers_scored']}.",
        f"SciBench-derived rows, prose not copied: {unitsafe['scibench_rows']}.",
        "On conversion rows, pint's reading of answer.unit matched the published "
        f"si_signature on {unitsafe['signature_match']} rows, differed on "
        f"{unitsafe['signature_mismatch']}, and did not parse on {unitsafe['unit_unparsed']}.",
        f"Agreement among parsed units: {unitsafe['parsed_agreement']}. "
        f"Wilson 95%: {unitsafe['parsed_agreement_ci95']}.",
        "That comparison uses the published unit token and the published signature. "
        "It is not a score of the numeric answer, and it is not B1.",
        f"Mismatch unit tokens: {unitsafe['mismatch_units']}.",
        f"Mismatch dimensions: {unitsafe.get('mismatch_detail', [])}.",
        f"Unparsed unit tokens: {unitsafe['unparsed_units']}.",
        "",
        "## Dronology",
        "",
        "Source: https://huggingface.co/datasets/thearod5/dronology",
        "Licence read from the dataset API on 2026-11-09: MIT.",
        f"Artifacts: {dronology['artifacts']}. Traces: {dronology['traces']}.",
        f"Gold positive links: {dronology['gold_positive_links']}.",
        f"Predicted links from the existing heading linker: {dronology['predicted_links']}.",
        f"Linker recall: {dronology['linker_recall']}.",
        "Precision: not computed. The trace file has no negative labels.",
        dronology["note"],
        "",
        "## JSON canonicalization",
        "",
        _jcs_lines(report.get("jcs") or {}),
        "",
        "## NIST SP 811 Appendix B.8",
        "",
        _nist_lines(report.get("nist_b8") or {}),
        "",
        "## QuRE",
        "",
        _qure_lines(report.get("qure") or {}),
        "",
        "## What this does not close",
        "",
        "B1 is still empty. A manufacturer-facing set has to be written by another "
        "engineer. This command must not be cited as that set.",
        "",
    ]
    return "\n".join(lines)
