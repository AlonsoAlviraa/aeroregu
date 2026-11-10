"""Score third-party files that this repository did not generate.

The files stay under data/external/ood and are not rewritten. Reports contain
counts, schema tokens, and unit tokens only. They do not copy requirement
sentences, claim text, or trace names.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from evidence_calc.units import conversion_interval
from evidence_kernel.paths import repo_root

from evidence_eval.b2 import EV_RE, PUBLIC_HEADINGS, predict
from evidence_eval.external_public import file_sha256
from evidence_eval.score import wilson

CLDR_SHA256 = "fa3b509179e5694360ccc777270ac0cae8a042fc32852f0fd2f53e594fc97444"
TRACE_SHA256 = "eb5398251774b1e2bebc76d38ef5285d39653bff3af3aefc9b13d4c56780059e"
CASE_SHA256 = "e2bb673a97fd0dc11dc3e8ecf19f18b288c1bcafb38ed2788d8eb36277d947c3"
DOSSPRE_SHA256 = "ecd542eb0160aa201dfb78bbd7e0acd458e7bc0c7a2efe5f654096332c3ddc86"
LICENSE_SHA256 = "0becf16567beb77fa252b7664631dd177c8f9a1889e48995b45379c7130e5303"

_PINS = {
    "cldr/units.xml": CLDR_SHA256,
    "mobstr/traceModel.xmi": TRACE_SHA256,
    "mobstr/mobstr-safetycase.integration": CASE_SHA256,
    "mobstr/LICENSE": LICENSE_SHA256,
    "dosspre/DOSSPRE-2.0Binary.csv": DOSSPRE_SHA256,
}
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCHEMA = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
_EXPR = re.compile(r"^[A-Za-z0-9_ */.+-]{1,240}$")
_STEM = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# Taken from this file's unitIdComponents. Power binds to the next stem.
_PREFIXES = frozenset("arc british dessert fluid light nautical xxx x curr".split())
_SUFFIXES = frozenset(
    "force imperial luminosity mass metric person radius scandinavian troy "
    "unit it us energy density cloth length jp".split()
)
_POWERS = {"square": 2, "cubic": 3, **{f"pow{n}": n for n in range(2, 16)}}
_EVIDENCE_HASH = "ab" * 32
_PRIOR = (
    "UnitSafe",
    "Dronology",
    "JCS",
    "NIST SP 811 Appendix B.8",
    "QuRE",
)

_REFUSED: list[dict[str, Any]] = [
    {
        "id": "figshare-29293868",
        "acquired": False,
        "source_url": "https://doi.org/10.6084/m9.figshare.29293868",
        "licence_seen": "cc-by-4.0",
        "bytes": 306430669,
        "label": "VERIFIED",
        "reason": (
            "API licence was cc-by-4.0 on 2026-11-10. The file was not downloaded. "
            "The record mixes upstream components whose own licence is not stated."
        ),
    },
    {
        "id": "zenodo-6524460",
        "acquired": False,
        "source_url": "https://doi.org/10.5281/zenodo.6524460",
        "licence_seen": "cc-by-4.0",
        "bytes": 354357304,
        "label": "VERIFIED",
        "reason": (
            "API licence id was cc-by-4.0 on 2026-11-10. The zip was not downloaded. "
            "It mixes code and data. MobSTr covers the trace problem at a smaller size."
        ),
    },
    {
        "id": "mendeley-7zbk8zsd8y",
        "acquired": False,
        "source_url": "https://doi.org/10.17632/7zbk8zsd8y",
        "label": "NOT VERIFIED",
        "reason": (
            "A curator note said the source-story licence was unknown. "
            "DataCite for this DOI was not opened on 2026-11-10. Not downloaded."
        ),
    },
    {
        "id": "earlier-register-refusals",
        "acquired": False,
        "label": "NOT VERIFIED",
        "reason": (
            "CoEST, DSTG/HUMS, ETH Airbus accelerometer, Paderborn, CMAPSS, "
            "DASHLINK 644, CWRU, and TPS-CalcBench were not downloaded for this run."
        ),
    },
]


def audit_path() -> Path:
    """New audit file. This does not replace the 2026-11-09 external report."""
    return repo_root() / "audit" / "06-ood-benchmarks-2026-11-10.md"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _elements(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [node for node in root.iter() if _local(node.tag) == name]


def _xsi_type(node: ElementTree.Element) -> str:
    if _XSI_TYPE in node.attrib:
        return node.attrib[_XSI_TYPE]
    for key, value in node.attrib.items():
        if _local(key) == "type" and "XMLSchema-instance" in key:
            return value
    return ""


def _schema_token(value: str) -> str:
    token = value.rsplit(":", 1)[-1]
    if _SCHEMA.fullmatch(token):
        return token
    return ""


def _grammar(root: ElementTree.Element) -> tuple[frozenset[str], frozenset[str], dict[str, int]]:
    """Prefix, suffix, and power lists. The file's own lists win when present."""
    found: dict[str, list[str]] = {}
    for node in _elements(root, "unitIdComponent"):
        kind = str(node.get("type") or "")
        found[kind] = str(node.get("values") or "").split()
    prefixes = frozenset(found.get("prefix") or _PREFIXES)
    suffixes = frozenset(found.get("suffix") or _SUFFIXES)
    power_names = found.get("power") or list(_POWERS)
    powers: dict[str, int] = {}
    for name in power_names:
        if name == "square":
            powers[name] = 2
        elif name == "cubic":
            powers[name] = 3
        elif name.startswith("pow") and name[3:].isdigit():
            powers[name] = int(name[3:])
    return prefixes, suffixes, powers or _POWERS


def _simple_units(
    side: str,
    prefixes: frozenset[str],
    suffixes: frozenset[str],
    powers: dict[str, int],
) -> list[str]:
    """One side of a CLDR id. square-second is second**2, not a separate unit."""
    tokens = [token for token in side.split("-") if token]
    index = 0
    factors: list[str] = []
    while index < len(tokens):
        power = 1
        if tokens[index] in powers:
            power = powers[tokens[index]]
            index += 1
        parts: list[str] = []
        while index < len(tokens) and tokens[index] in prefixes:
            parts.append(tokens[index])
            index += 1
        if index >= len(tokens) or tokens[index] in powers or tokens[index] in {"per", "and"}:
            raise ValueError("stem")
        parts.append(tokens[index])
        index += 1
        while index < len(tokens) and tokens[index] in suffixes:
            parts.append(tokens[index])
            index += 1
        stem = "_".join(parts)
        if not _STEM.fullmatch(stem):
            raise ValueError("stem")
        factors.append(stem if power == 1 else f"{stem} ** {power}")
    if not factors:
        raise ValueError("stem")
    return factors


def _pint_unit(
    value: str,
    prefixes: frozenset[str],
    suffixes: frozenset[str],
    powers: dict[str, int],
) -> str:
    """CLDR id to a pint expression. per divides the following product."""
    unit_id = value.strip()
    if not unit_id or any(char in unit_id for char in " \t\n\r/()"):
        return ""
    if unit_id.startswith("per-"):
        numerator, denominator = "", unit_id[4:]
    elif "-per-" in unit_id:
        numerator, denominator = unit_id.split("-per-", 1)
    else:
        numerator, denominator = unit_id, ""
    try:
        num_factors = _simple_units(numerator, prefixes, suffixes, powers) if numerator else []
        den_factors = _simple_units(denominator, prefixes, suffixes, powers) if denominator else []
    except ValueError:
        return ""
    if not num_factors and not den_factors:
        return ""
    expression = " * ".join(num_factors) if num_factors else "1"
    for factor in den_factors:
        expression = f"{expression} / {factor}"
    if not _EXPR.fullmatch(expression):
        return ""
    return expression


def _xml_root(path: Path, anchor: str | None = None) -> ElementTree.Element:
    text = path.read_bytes().decode("utf-8")
    if anchor is not None:
        start = text.find(f"<{anchor}")
        if start < 0:
            raise ElementTree.ParseError(anchor)
        text = text[start:]
    return ElementTree.fromstring(text)


def _read_table(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _product(part: str, constants: dict[str, str], seen: set[str]) -> Decimal:
    if not part:
        raise ValueError("empty")
    value = Decimal(1)
    for token in part.split("*"):
        if not token:
            raise ValueError("empty")
        if _NUMBER.fullmatch(token):
            value *= Decimal(token)
            continue
        if token not in constants or token in seen:
            raise ValueError("token")
        value *= _factor(constants[token].replace(" ", ""), constants, seen | {token})
    return value


def _factor(expr: str, constants: dict[str, str], seen: set[str]) -> Decimal:
    """CLDR factor. Multiplication binds more tightly than division."""
    if any(char in expr for char in "()"):
        raise ValueError("paren")
    if _IDENT.fullmatch(expr) and expr in constants:
        if expr in seen:
            raise ValueError("cycle")
        return _factor(constants[expr].replace(" ", ""), constants, seen | {expr})
    parts = expr.split("/")
    value = _product(parts[0], constants, seen)
    for part in parts[1:]:
        value /= _product(part, constants, seen)
    return value


def _pair(left: str, right: str) -> str:
    if not left or not right:
        return ""
    return f"{left}|{right}"


def _raw_pair(source: str, base: str) -> str:
    """Unit ids only. A long or punctuated value is counted and not printed."""
    if _SCHEMA.fullmatch(source) and _SCHEMA.fullmatch(base):
        return f"{source}|{base}"
    return ""


def _endpoint_hrefs(node: ElementTree.Element) -> list[str]:
    """Href values on direct children. The child tag is not a dataset switch."""
    hrefs: list[str] = []
    for child in list(node):
        href = child.get("href")
        if href:
            hrefs.append(str(href))
    return hrefs


def _comparable_pair(hrefs: list[str]) -> tuple[str, str] | None:
    """One public heading and one evidence id. Any other href is not a label."""
    headings = [href for href in hrefs if href in PUBLIC_HEADINGS]
    evidence_ids = [href for href in hrefs if EV_RE.fullmatch(href)]
    if len(headings) == 1 and len(evidence_ids) == 1:
        return headings[0], evidence_ids[0]
    return None


def _evidence_rows(name: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in EV_RE.finditer(name):
        evidence_id = match.group()
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        rows.append({"id": evidence_id, "hash": _EVIDENCE_HASH})
    return rows


def _type_rows(counts: Counter[str]) -> list[dict[str, Any]]:
    return [{"type": name, "count": count} for name, count in sorted(counts.items())]


def _base(
    *,
    dataset_id: str,
    problem: str,
    path: Path,
    digest: str,
    pin: str,
    source_url: str,
    licence: str,
    licence_url: str,
    checker: str,
    scored: int,
    missing_component: str,
    measured: str,
    not_measured: str,
    domain_shift: str,
) -> dict[str, Any]:
    return {
        "id": dataset_id,
        "problem": problem,
        "source_url": source_url,
        "licence": licence,
        "licence_url": licence_url,
        "retrieved": "2026-11-10",
        "sha256": digest,
        "pin_match": digest == pin,
        "bytes": path.stat().st_size,
        "domain_shift": domain_shift,
        "checker": checker,
        "numeric_from_existing_checker": bool(checker) and scored == 1,
        "scored": scored,
        "missing_component": missing_component,
        "measured": measured,
        "not_measured": not_measured,
        "names_copied": 0,
        "requirements_copied": 0,
        "content_copied": 0,
    }


def score_cldr_units(path: Path) -> dict[str, Any]:
    """Exact interval check. No tolerance is added."""
    digest = file_sha256(path)
    root = _xml_root(path, "supplementalData")
    constants = {
        str(node.get("constant") or ""): str(node.get("value") or "")
        for node in _elements(root, "unitConstant")
        if node.get("constant")
    }
    prefixes, suffixes, powers = _grammar(root)
    agree = disagree = unparsed = incompatible = offset = bad = withheld = 0
    offset_none = 0
    disagree_detail: list[dict[str, str]] = []
    incompatible_pairs: list[str] = []
    unparsed_pairs: list[str] = []
    offset_pairs: list[str] = []
    rows = _elements(root, "convertUnit")
    for node in rows:
        source = str(node.get("source") or "")
        base = str(node.get("baseUnit") or "")
        left = _pint_unit(source, prefixes, suffixes, powers)
        right = _pint_unit(base, prefixes, suffixes, powers)
        pair = _pair(left, right)
        if node.get("offset"):
            offset += 1
            if pair:
                offset_pairs.append(pair)
            if left and right and conversion_interval(left, right) is None:
                offset_none += 1
            continue
        if not left or not right:
            unparsed += 1
            raw = _raw_pair(source, base)
            if raw:
                unparsed_pairs.append(raw)
            else:
                withheld += 1
            continue
        try:
            published = _factor((node.get("factor") or "1").replace(" ", ""), constants, set())
        except (ValueError, ArithmeticError):
            bad += 1
            continue
        got = conversion_interval(left, right)
        if got is None:
            unparsed += 1
            if pair:
                unparsed_pairs.append(pair)
            continue
        if got == "incompatible":
            incompatible += 1
            if pair:
                incompatible_pairs.append(pair)
            continue
        if got == published:
            agree += 1
            continue
        disagree += 1
        if pair:
            disagree_detail.append({"pair": pair, "pint": str(got), "published": str(published)})
    compared = agree + disagree
    counts: dict[str, Any] = {
        "convert_rows": len(rows),
        "agree": agree,
        "disagree": disagree,
        "compared": compared,
        "agreement": f"{agree}/{compared}",
        "unparsed": unparsed,
        "incompatible": incompatible,
        "offset_not_scored": offset,
        "offset_interval_none": offset_none,
        "bad_factor": bad,
        "tokens_withheld": withheld,
    }
    interval = wilson(agree, compared)
    if interval is not None:
        counts["wilson_low"] = interval["low"]
        counts["wilson_high"] = interval["high"]
        counts["wilson_method"] = interval["method"]
    report = _base(
        dataset_id="CLDR-units",
        problem="calculation-or-unit-fault",
        path=path,
        digest=digest,
        pin=CLDR_SHA256,
        source_url=(
            "https://raw.githubusercontent.com/unicode-org/cldr/main/common/supplemental/units.xml"
        ),
        licence="Unicode-3.0",
        licence_url="https://www.unicode.org/license.txt",
        checker="evidence_calc.units.conversion_interval",
        scored=1,
        missing_component="",
        measured="Exact equality of conversion_interval and the published factor.",
        not_measured="Kind-of-quantity. No epsilon. Offset rows are not misses.",
        domain_shift="CLDR is a general unit table, not a rotorcraft calculation note.",
    )
    report["counts"] = counts
    report["disagree_detail"] = sorted(disagree_detail, key=lambda item: item["pair"])
    report["incompatible_pairs"] = sorted(set(incompatible_pairs))
    report["unparsed_pairs"] = sorted(set(unparsed_pairs))
    report["offset_pairs"] = sorted(set(offset_pairs))
    report["reasons"] = {
        "unparsed": "The unit id did not spell, or conversion_interval returned None",
        "offset_not_scored": "offset unit",
        "incompatible": "conversion_interval returned incompatible",
        "disagree": "exact Decimal inequality",
    }
    return report


def score_trace_file(path: Path) -> dict[str, Any]:
    """Call predict. Recall only when an endpoint is a heading and an evidence id."""
    digest = file_sha256(path)
    root = _xml_root(path)
    predicted = 0
    hits = 0
    publisher = 0
    comparable = 0
    types: Counter[str] = Counter()
    traces = _elements(root, "traces")
    for node in traces:
        token = _schema_token(_xsi_type(node))
        types[token or "untyped"] += 1
        hrefs = _endpoint_hrefs(node)
        if len(hrefs) >= 2:
            publisher += 1
        endpoints = _comparable_pair(hrefs)
        name = str(node.get("name") or "")
        links, _flags = predict(name, _evidence_rows(name))
        predicted += len(links)
        if endpoints is None:
            continue
        comparable += 1
        heading, evidence_id = endpoints
        for link in links:
            same_heading = link.get("requirement_id") == heading
            same_evidence = link.get("evidence_id") == evidence_id
            if same_heading and same_evidence:
                hits += 1
                break
    counts: dict[str, Any] = {
        "trace_elements": len(traces),
        "publisher_links": publisher,
        "comparable_links": comparable,
        "negative_labels": 0,
        "predicted_links": predicted,
    }
    if comparable:
        counts["gold_hits"] = hits
        counts["linker_recall"] = f"{hits}/{comparable}"
        scored = 1
        missing = ""
        measured = (
            "predict on trace names, scored only where one endpoint is a public heading "
            "and the other is an evidence id."
        )
        not_measured = (
            "Artifact-reference endpoints. A trace retriever. "
            "Precision, because there is no negative label."
        )
    else:
        scored = 0
        missing = "publisher labels are artifact references, not the eight public headings"
        measured = (
            "predict was called on each trace name. "
            "No endpoint pair was a public heading and an evidence id."
        )
        not_measured = (
            "Recall against artifact references. A trace retriever. "
            "Precision, because there is no negative label."
        )
    report = _base(
        dataset_id="MobSTr-traces",
        problem="requirement-to-evidence-trace",
        path=path,
        digest=digest,
        pin=TRACE_SHA256,
        source_url=(
            "https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/"
            "__WorkspaceTraceModels/traceModel.xmi"
        ),
        licence="EPL-2.0",
        licence_url="https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/LICENSE",
        checker="evidence_eval.b2.predict",
        scored=scored,
        missing_component=missing,
        measured=measured,
        not_measured=not_measured,
        domain_shift="MobSTr is an automotive trace model, not rotorcraft.",
    )
    report["counts"] = counts
    report["precision"] = None
    report["precision_reason"] = "The trace file has positive links only."
    report["trace_types"] = _type_rows(types)
    return report


def score_assurance_file(path: Path) -> dict[str, Any]:
    """Census only. No checker reads an assurance-case link."""
    digest = file_sha256(path)
    root = _xml_root(path)
    types: Counter[str] = Counter()
    elements = _elements(root, "argumentationElement")
    for node in elements:
        token = _schema_token(_xsi_type(node))
        types[token or "untyped"] += 1
    report = _base(
        dataset_id="MobSTr-safetycase",
        problem="assurance-case-link",
        path=path,
        digest=digest,
        pin=CASE_SHA256,
        source_url=(
            "https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/"
            "org.panorama-research.mobstr.safetycase/mobstr-safetycase.integration"
        ),
        licence="EPL-2.0",
        licence_url="https://raw.githubusercontent.com/panorama-research/mobstr-dataset/master/LICENSE",
        checker="",
        scored=0,
        missing_component="assurance-case linker",
        measured="Count of argumentation element types.",
        not_measured="Whether an asserted link is supported. predict() was not used.",
        domain_shift="The MobSTr safety case is automotive, not rotorcraft.",
    )
    report["counts"] = {"argumentation_elements": len(elements), "scored": 0}
    report["element_types"] = _type_rows(types)
    return report


def score_requirement_classes(path: Path) -> dict[str, Any]:
    """Count class tokens. Requirement cells are not returned."""
    digest = file_sha256(path)
    text = _read_table(path)
    rows = list(csv.DictReader(io.StringIO(text)))
    counts: Counter[str] = Counter()
    for row in rows:
        label = str(row.get("Class") or "").strip()
        if _SCHEMA.fullmatch(label):
            counts[label] += 1
        else:
            counts["withheld"] += 1
        row.pop("Requirement", None)
    report = _base(
        dataset_id="DOSSPRE-2.0-binary",
        problem="requirement-quality-defect",
        path=path,
        digest=digest,
        pin=DOSSPRE_SHA256,
        source_url="https://data.mendeley.com/datasets/23xtbvk6yp/2",
        licence="CC-BY-4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/legalcode",
        checker="",
        scored=0,
        missing_component="requirement-quality classifier",
        measured="Count of publisher class tokens.",
        not_measured="Which class is correct. No classifier exists.",
        domain_shift=(
            "DOSSPRE labels student software requirements, not rotorcraft. "
            "The publisher label is security versus non-security."
        ),
    )
    report["counts"] = {
        "rows": len(rows),
        "scored": 0,
        "requirements_copied": 0,
    }
    report["class_counts"] = dict(sorted(counts.items()))
    if digest == DOSSPRE_SHA256:
        report["datacite_rows"] = 1317
        report["datacite_nsr"] = 801
        report["datacite_sr"] = 516
        report["abstract_matches_file"] = (
            len(rows) == 1317 and counts.get("NSR") == 801 and counts.get("SR") == 516
        )
    return report


def _denials() -> dict[str, Any]:
    return {
        "expert_holdout_written_by_this_run": False,
        "b1_expert_holdout_filled": False,
        "b2_expert_holdout_filled": False,
        "b3_expert_holdout_filled": False,
        "b4_ready": False,
        "certifies": False,
        "qualifies_tool": False,
        "programme_complete": False,
    }


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        if "\n" in value or "\r" in value:
            return ""
        return value
    if isinstance(value, dict):
        return {str(key): _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if value is None or isinstance(value, (int, bool)):
        return value
    raise TypeError(type(value).__name__)


def ood_report(root: Path | None = None, *, check_pin: bool = True) -> dict[str, Any]:
    """Score the four acquired files. Pins are required for the shipped command."""
    base = root or (repo_root() / "data" / "external" / "ood")
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, pin in _PINS.items():
        path = base / relative
        if relative == "mobstr/LICENSE" and not check_pin:
            continue
        if not path.is_file():
            missing.append(relative)
            continue
        if check_pin and file_sha256(path) != pin:
            mismatched.append(relative)
    envelope: dict[str, Any] = {
        "acquired": False,
        "date": "2026-11-10",
        "command": "ood-bench",
        "prior_sets_included": False,
        "prior_sets": list(_PRIOR),
        "refused": _REFUSED,
        **_denials(),
    }
    if missing or mismatched:
        envelope["missing"] = missing
        envelope["hash_mismatch"] = mismatched
        return _scrub(envelope)
    notice = base / "mobstr" / "LICENSE"
    notice_sha = file_sha256(notice) if notice.is_file() else ""
    datasets = [
        score_cldr_units(base / "cldr" / "units.xml"),
        score_trace_file(base / "mobstr" / "traceModel.xmi"),
        score_assurance_file(base / "mobstr" / "mobstr-safetycase.integration"),
        score_requirement_classes(base / "dosspre" / "DOSSPRE-2.0Binary.csv"),
    ]
    for item in datasets:
        if str(item["id"]).startswith("MobSTr"):
            item["notice_sha256"] = notice_sha
            item["notice_pin_match"] = notice_sha == LICENSE_SHA256
    datasets.sort(key=lambda item: str(item["id"]))
    envelope["acquired"] = True
    envelope["datasets"] = datasets
    envelope["problems"] = sorted({str(item["problem"]) for item in datasets})
    return _scrub(envelope)


def count_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Stable numeric snapshot. Two calls on the same files must match."""
    datasets = []
    for item in report.get("datasets") or []:
        datasets.append(
            {
                "id": item.get("id"),
                "problem": item.get("problem"),
                "scored": item.get("scored"),
                "missing_component": item.get("missing_component") or "",
                "counts": item.get("counts") or {},
                "class_counts": item.get("class_counts") or {},
                "trace_types": item.get("trace_types") or [],
                "element_types": item.get("element_types") or [],
                "disagree": len(item.get("disagree_detail") or []),
                "abstract_matches_file": item.get("abstract_matches_file"),
            }
        )
    return {
        "acquired": bool(report.get("acquired")),
        "problems": list(report.get("problems") or []),
        "datasets": datasets,
    }


def _line(label: str, text: str) -> str:
    return f"{label}: {text}"


def _dataset_lines(item: dict[str, Any]) -> list[str]:
    counts = item["counts"]
    hash_label = "VERIFIED" if item["pin_match"] else "NOT VERIFIED"
    lines = [
        f"## {item['id']}",
        "",
        _line(hash_label, f"SHA-256 {item['sha256']}. Bytes {item['bytes']}."),
        _line("VERIFIED", f"Source {item['source_url']}."),
        _line(
            "VERIFIED",
            f"Licence {item['licence']} at {item['licence_url']}. Retrieved {item['retrieved']}.",
        ),
        _line("VERIFIED", f"Business problem {item['problem']}."),
    ]
    if item.get("notice_sha256"):
        notice_label = "VERIFIED" if item.get("notice_pin_match") else "NOT VERIFIED"
        lines.append(_line(notice_label, f"Licence file SHA-256 {item['notice_sha256']}."))
    lines.extend(
        [
            _line("ASSUMPTION", item["domain_shift"]),
            _line("VERIFIED", f"Measured: {item['measured']}"),
            _line("NOT VERIFIED", f"Not measured: {item['not_measured']}"),
        ]
    )
    if item["problem"] == "calculation-or-unit-fault":
        lines.extend(
            [
                _line("VERIFIED", f"Convert rows {counts['convert_rows']}."),
                _line(
                    "VERIFIED",
                    f"Exact agreement {counts['agreement']}. "
                    f"Agree {counts['agree']}. Disagree {counts['disagree']}.",
                ),
                _line(
                    "VERIFIED",
                    "Each disagree is an exact Decimal inequality. No epsilon was applied.",
                ),
                _line(
                    "PARTIAL",
                    f"Unparsed {counts['unparsed']}. Reason: {item['reasons']['unparsed']}. "
                    "Those rows are not misses.",
                ),
                _line(
                    "PARTIAL",
                    f"Offset rows not scored {counts['offset_not_scored']}. "
                    f"Reason: {item['reasons']['offset_not_scored']}.",
                ),
                _line(
                    "VERIFIED",
                    f"Incompatible {counts['incompatible']}. "
                    f"Reason: {item['reasons']['incompatible']}.",
                ),
                _line("VERIFIED", f"Bad factors {counts['bad_factor']}."),
                _line("VERIFIED", f"Compared {counts['compared']}."),
                _line("VERIFIED", f"Offset interval none {counts['offset_interval_none']}."),
                _line("VERIFIED", f"Tokens withheld {counts['tokens_withheld']}."),
            ]
        )
        if "wilson_low" in counts:
            lines.append(
                _line(
                    "VERIFIED",
                    f"Wilson 95 percent low {counts['wilson_low']} high {counts['wilson_high']}. "
                    f"Method {counts['wilson_method']}.",
                )
            )
        for detail in item["disagree_detail"]:
            lines.append(
                _line(
                    "VERIFIED",
                    f"Disagree {detail['pair']} pint {detail['pint']} "
                    f"published {detail['published']}.",
                )
            )
        for pair in item["incompatible_pairs"]:
            lines.append(_line("VERIFIED", f"Incompatible pair {pair}."))
        for pair in item["unparsed_pairs"]:
            lines.append(_line("PARTIAL", f"Unparsed pair {pair}."))
        for pair in item["offset_pairs"]:
            lines.append(_line("PARTIAL", f"Offset pair {pair}."))
    elif item["problem"] == "requirement-to-evidence-trace":
        lines.extend(
            [
                _line("VERIFIED", f"Trace elements {counts['trace_elements']}."),
                _line("VERIFIED", f"Publisher links {counts['publisher_links']}."),
                _line("VERIFIED", f"Predicted links {counts['predicted_links']}."),
                _line("VERIFIED", f"Comparable links {counts['comparable_links']}."),
                _line("VERIFIED", f"Negative labels {counts['negative_labels']}."),
                _line("VERIFIED", "Precision is null. The file has no negative labels."),
            ]
        )
        if "linker_recall" in counts:
            lines.append(
                _line(
                    "VERIFIED",
                    f"Linker recall {counts['linker_recall']}. "
                    f"Gold hits {counts['gold_hits']}. "
                    "The denominator is the comparable endpoint count.",
                )
            )
            lines.append(
                _line(
                    "VERIFIED",
                    "Recall uses the eight public headings. The heading list was not edited.",
                )
            )
        else:
            lines.append(
                _line(
                    "NOT VERIFIED",
                    f"Scored {item['scored']}. Missing component: {item['missing_component']}. "
                    "Recall was not computed.",
                )
            )
        for row in item.get("trace_types") or []:
            lines.append(_line("VERIFIED", f"Trace type {row['type']} count {row['count']}."))
    elif item["scored"] == 0:
        lines.append(
            _line(
                "NOT VERIFIED",
                f"Scored {item['scored']}. Missing component: {item['missing_component']}.",
            )
        )
        if "argumentation_elements" in counts:
            lines.append(
                _line(
                    "VERIFIED",
                    f"Argumentation elements {counts['argumentation_elements']}. "
                    "Claim text was not copied.",
                )
            )
            for row in item.get("element_types") or []:
                lines.append(_line("VERIFIED", f"Element type {row['type']} count {row['count']}."))
        if "rows" in counts:
            lines.append(
                _line(
                    "VERIFIED",
                    f"File rows {counts['rows']}. Class tokens only. "
                    "Requirement text was not copied.",
                )
            )
            rendered_counts = json.dumps(item["class_counts"], sort_keys=True)
            lines.append(_line("VERIFIED", f"Class counts {rendered_counts}."))
            if "requirements_copied" in counts:
                lines.append(
                    _line(
                        "VERIFIED",
                        f"Requirements copied {counts['requirements_copied']}.",
                    )
                )
        if "abstract_matches_file" in item:
            lines.append(
                _line(
                    "PARTIAL",
                    "DataCite abstract rows "
                    f"{item['datacite_rows']}, NSR {item['datacite_nsr']}, "
                    f"SR {item['datacite_sr']}. "
                    f"abstract_matches_file is {str(item['abstract_matches_file']).lower()}.",
                )
            )
    return lines


def render_ood_audit(report: dict[str, Any]) -> str:
    """Human audit. Every count is copied from the report dict."""
    lines = [
        "# OOD third-party benchmarks, 2026-11-10",
        "",
        "This is a new audit file.",
        "It does not replace docs/benchmarks/external_public_latest.md.",
        "It does not replace audit/00-resumen.md.",
        "",
        "This run does not fill the B1, B2, or B3 expert holdout.",
        "This run does not make B4 ready.",
        "This run does not certify, qualify, or complete the programme.",
        "",
        _line(
            "VERIFIED",
            "UnitSafe, Dronology, JCS, NIST SP 811 Appendix B.8, and QuRE are not in this set.",
        ),
        _line(
            "VERIFIED",
            "Acquired is "
            f"{str(report.get('acquired')).lower()}. "
            "Date 2026-11-10. Command ood-bench.",
        ),
    ]
    if not report.get("acquired"):
        lines.extend(
            [
                _line("NOT VERIFIED", f"Missing {report.get('missing', [])}."),
                _line("NOT VERIFIED", f"Hash mismatch {report.get('hash_mismatch', [])}."),
                "",
            ]
        )
    else:
        lines.append(_line("VERIFIED", f"Problems {report['problems']}."))
        lines.append("")
        for item in report["datasets"]:
            lines.extend(_dataset_lines(item))
            lines.append("")
    lines.append("## Refused sources")
    lines.append("")
    for item in report.get("refused") or []:
        lines.append(_line(str(item["label"]), f"{item['id']}. {item['reason']}"))
    lines.extend(
        [
            "",
            "This run does not fill the B1, B2, or B3 expert holdout.",
            "This run does not make B4 ready.",
            "This run does not certify, qualify, or complete the programme.",
            "",
        ]
    )
    return "\n".join(lines)
