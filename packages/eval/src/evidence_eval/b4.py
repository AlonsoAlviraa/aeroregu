"""B4 stays unscored until a local file is named in the data register."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import reject_ambiguous
from evidence_calc.units import same_unit, units_compatible


def unregistered_files(folder: Path, register_text: str) -> list[str]:
    if not folder.is_dir():
        return []
    missing: list[str] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in register_text:
            missing.append(path.name)
    return missing


def exceedance_count(
    samples: list[str],
    limit: str,
    unit: str,
    sample_unit: str | None = None,
) -> int:
    """Count samples strictly above limit. A different unit abstains.

    same_unit is the rule. It uses a Decimal scale of one. The same
    dimension is not enough, and the samples are not converted.
    """
    if not samples or limit == "" or unit == "":
        raise AbstainError("missing_input")
    declared = unit if sample_unit is None else sample_unit
    if not same_unit(declared, unit):
        raise AbstainError("unit_mismatch")
    reject_ambiguous(limit)
    cap = Decimal(limit)
    count = 0
    for sample in samples:
        reject_ambiguous(sample)
        if not isinstance(sample, str):
            raise AbstainError("ambiguous_input")
        if Decimal(sample) > cap:
            count += 1
    return count


_LIVE_SERIES_DIRS = frozenset({"as365", "b4"})


def _is_live_series_path(path: Path) -> bool:
    """True for data/as365 and data/b4, and for any file inside them."""
    candidates = [path]
    try:
        resolved = path.resolve()
    except OSError:
        resolved = None
    if resolved is not None and resolved != path:
        candidates.append(resolved)
    for candidate in candidates:
        parts = [part.casefold() for part in candidate.parts]
        for index in range(len(parts) - 1):
            folder = parts[index]
            name = parts[index + 1]
            if folder == "data" and name in _LIVE_SERIES_DIRS:
                return True
    return False


def score_series_file(path: Path) -> int:
    """Count samples above the limit written in this file.

    The unit and the exceedance limit both have to be lines in the file.
    A limit unit, when written, has to be the same unit as the samples.
    same_unit decides. The same dimension is not enough, and nothing is
    converted. A mismatch abstains with unit_mismatch before any sample
    is stored and returns no exceedance count. No external limit is
    applied, and none is inferred from the samples. data/as365 and
    data/b4 are refused before they are read.
    The count is exceedance_count. Samples are not retained. This count
    is not a public B4 result and does not mark B4 ready.
    """
    if _is_live_series_path(path):
        raise AbstainError("live_series_not_scored")
    unit, limit, limit_unit = _series_header(path)
    if unit is None or unit == "":
        raise AbstainError("unit_not_in_file")
    if limit is None or limit == "":
        raise AbstainError("limit_not_in_file")
    limit_name = unit if limit_unit is None or limit_unit == "" else limit_unit
    if not same_unit(unit, limit_name):
        raise AbstainError("unit_mismatch")
    samples = _series_samples(path)
    if limit_unit is None or limit_unit == "":
        return exceedance_count(samples, limit, unit)
    return exceedance_count(samples, limit, limit_unit, unit)


def _series_header(path: Path) -> tuple[str | None, str | None, str | None]:
    unit: str | None = None
    limit: str | None = None
    limit_unit: str | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            kind, value = _series_field(raw)
            if kind == "unit":
                if unit is not None:
                    raise AbstainError("ambiguous_input")
                unit = value
            elif kind == "limit":
                if limit is not None:
                    raise AbstainError("ambiguous_input")
                limit = value
            elif kind == "limit_unit":
                if limit_unit is not None:
                    raise AbstainError("ambiguous_input")
                limit_unit = value
    return unit, limit, limit_unit


def _series_samples(path: Path) -> list[str]:
    samples: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            kind, value = _series_field(raw)
            if kind == "sample" and value != "":
                samples.append(value)
    return samples


def _series_field(raw: str) -> tuple[str, str]:
    line = raw.strip()
    if line.startswith("limit_unit:"):
        return "limit_unit", line.removeprefix("limit_unit:").strip()
    if line.startswith("unit:"):
        return "unit", line.removeprefix("unit:").strip()
    if line.startswith("limit:"):
        return "limit", line.removeprefix("limit:").strip()
    return "sample", line


def naive_stated_count(stated: str | None) -> int:
    """Trust a stated count. Abstain only when it is missing."""
    if stated is None or stated == "":
        raise AbstainError("missing_input")
    reject_ambiguous(stated)
    return int(Decimal(stated))


DRILL_VERSION = "b4-drill@1.0.0"
DRILL_SERIES = (
    {
        "samples": ["1.0", "3.0", "2.5"],
        "limit": "2.0",
        "unit": "meter / second ** 2",
        "gold": 2,
        "stated": "0",
    },
    {
        "samples": ["1.0", "1.5"],
        "limit": "2.0",
        "unit": "meter / second ** 2",
        "gold": 0,
        "stated": "0",
    },
)


def _record_drill(counts: list[int], abstain_ok: bool) -> tuple[list[str], str | None, int]:
    import tempfile
    from pathlib import Path

    from evidence_kernel.contracts import ScribeOutput, ScribeSentence
    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.ledger import Ledger
    from evidence_kernel.orchestrator import record

    hashes: list[str] = []
    abstain_hash = None
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b4.sqlite3", "bench")
        for index, count in enumerate(counts):
            envelope = make_envelope(
                sources=[
                    project_source(
                        "exceedance",
                        "https://aeroregu.local/b4",
                        "ASSUMPTION",
                    )
                ],
                method_version=DRILL_VERSION,
                inputs={"series": str(index)},
                confidence="deterministic",
                result={"count": str(count)},
            )
            digest = record(
                ledger,
                {
                    "event_type": "recompute_flag",
                    "tenant_id": "bench",
                    "actor_id": "orchestrator",
                    "created_at": f"2026-11-04T17:30:{index:02d}Z",
                    "payload": {"count": str(count)},
                    "envelope": envelope,
                },
            )
            ScribeOutput(
                sentences=[
                    ScribeSentence(
                        text="The exceedance count is recorded.",
                        ledger_event_hash=digest,
                    )
                ]
            )
            hashes.append(digest)
        if abstain_ok:
            abstain_hash = enqueue(
                ledger,
                tenant_id="bench",
                actor_id="orchestrator",
                created_at="2026-11-04T17:31:00Z",
                reason="ambiguous_input",
            )
        violations = _count_violations(ledger.events())
    return hashes, abstain_hash, violations


def _count_violations(events: list[dict[str, object]]) -> int:
    """The recomputed count is allowed. Any other physical number is a violation."""
    from evidence_kernel.numbers import stray_physical_numbers

    violations = 0
    for event in events:
        body = event.get("body")
        envelope = body.get("envelope") if isinstance(body, dict) else None
        result = envelope.get("result") if isinstance(envelope, dict) else None
        allowed: set[str] = set()
        if isinstance(result, dict) and isinstance(result.get("count"), str):
            allowed.add(result["count"])
        violations += len(stray_physical_numbers(result, allowed))
    return violations


def line_is_bare_number(line: str) -> bool:
    text = line.strip()
    if text == "":
        return False
    try:
        reject_ambiguous(text)
        Decimal(text)
    except (AbstainError, ArithmeticError, ValueError):
        return False
    return True


def inspect_acceleration_zip(path: Path) -> dict[str, object]:
    """Read structure and first lines. Do not count exceedances."""
    import zipfile

    published_length = 80128
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        acceleration = sorted(name for name in names if name.endswith("-acceleration.txt"))
        pyc = [name for name in names if name.endswith(".pyc")]
        bare = 0
        other = 0
        first_file_lines = 0
        matching = 0
        shortest = None
        longest = None
        for index, name in enumerate(acceleration):
            with archive.open(name) as handle:
                first = handle.readline().decode("utf-8", errors="replace")
                count = 1 + sum(1 for _ in handle)
            if line_is_bare_number(first):
                bare += 1
            elif first.strip() != "":
                other += 1
            if index == 0:
                first_file_lines = count
            if count == published_length:
                matching += 1
            if shortest is None or count < shortest:
                shortest = count
            if longest is None or count > longest:
                longest = count
    published_codes = {"BF", "CF", "H", "IRF", "ORF"}
    tokens: set[str] = set()
    published_token_files = 0
    published_speeds = {"1000", "1500", "2000"}
    grid: dict[tuple[str, str], int] = {}
    for name in acceleration:
        parts = [part for part in name.split("/") if part]
        token = parts[-3] if len(parts) >= 3 else ""
        speed = parts[-2] if len(parts) >= 2 else ""
        tokens.add(token)
        if token in published_codes:
            published_token_files += 1
        grid[(token, speed)] = grid.get((token, speed), 0) + 1
    cells_of_ten = sum(1 for count in grid.values() if count == 10)
    speeds = {speed for _, speed in grid}
    if other:
        reason = "no_limit_in_file"
        unit = True
    else:
        reason = "unit_not_in_file"
        unit = False
    archive_abstain = _record_archive_abstain(reason)
    return {
        "acceleration_files": len(acceleration),
        "bare_first_lines": bare,
        "pyc_files": len(pyc),
        "pyc_executed": False,
        "unit_in_first_line": unit,
        "first_file_lines": first_file_lines,
        "files_matching_published_length": matching,
        "shortest_file_lines": shortest or 0,
        "longest_file_lines": longest or 0,
        "path_tokens": sorted(tokens),
        "files_whose_class_token_is_published": published_token_files,
        "grid_cells": len(grid),
        "grid_cells_with_ten_files": cells_of_ten,
        "speeds": sorted(speeds),
        "speeds_match_claim": speeds == published_speeds,
        "published_length_claim": published_length,
        "length_matches_claim": first_file_lines == published_length,
        "scored": False,
        "sensor_range_applied": False,
        "abstain_reason": reason,
        "abstain_hash": archive_abstain[0],
        "llm_numeric_violation": archive_abstain[1],
        "label": "NOT_VERIFIED",
    }


def _abstain_violations(events: list[dict[str, object]]) -> int:
    """A physical number in an abstain reason or result is a violation."""
    from evidence_kernel.numbers import stray_physical_numbers

    violations = 0
    for event in events:
        body = event.get("body")
        if not isinstance(body, dict):
            continue
        envelope = body.get("envelope") if isinstance(body.get("envelope"), dict) else {}
        result = envelope.get("result") if isinstance(envelope, dict) else None
        violations += len(stray_physical_numbers(result, set()))
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if isinstance(reason, str):
            violations += len(stray_physical_numbers(reason, set()))
    return violations


def _record_archive_abstain(reason: str) -> tuple[str, int]:
    import tempfile

    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.ledger import Ledger

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b4-archive.sqlite3", "bench")
        digest = enqueue(
            ledger,
            tenant_id="bench",
            actor_id="orchestrator",
            created_at="2026-11-04T17:56:00Z",
            reason=reason,
        )
        return digest, _abstain_violations(ledger.events())


def drill_sha256() -> str:
    import json

    payload = json.dumps(list(DRILL_SERIES), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def drill() -> dict[str, object]:
    """Invented series only. This does not score a public file."""
    from evidence_eval.score import wilson

    series = DRILL_SERIES
    detector_hits = 0
    naive_hits = 0
    false_alarms = 0
    clean = 0
    counts: list[int] = []
    for row in series:
        got = exceedance_count(row["samples"], row["limit"], row["unit"])
        counts.append(got)
        if row["gold"] == 0:
            clean += 1
            if got != 0:
                false_alarms += 1
        if got == row["gold"]:
            detector_hits += 1
        if naive_stated_count(row["stated"]) == row["gold"]:
            naive_hits += 1
    abstain_ok = False
    try:
        exceedance_count(["1.0 or 3.0"], "2.0", "meter / second ** 2")
    except AbstainError:
        abstain_ok = True
    total = len(series)
    hashes, abstain_hash, violations = _record_drill(counts, abstain_ok)
    return {
        "source": "founder-owned synthetic",
        "version": DRILL_VERSION,
        "series_sha256": drill_sha256(),
        "public_file": False,
        "detector_correct": f"{detector_hits}/{total}",
        "naive_correct": f"{naive_hits}/{total}",
        "false_alarms": f"{false_alarms}/{clean}",
        "false_alarm_ci95": wilson(false_alarms, clean),
        "abstain_ok": abstain_ok,
        "abstention_correctness": "1/1" if abstain_ok else "0/1",
        "abstention_ci95": wilson(1 if abstain_ok else 0, 1),
        "beats_single_llm": "NOT_VERIFIED",
        "detector_ci95": wilson(detector_hits, total),
        "event_hashes": hashes,
        "abstain_hash": abstain_hash,
        "llm_numeric_violation": violations,
        "label": "ESTIMATE",
        "note": "Not a public dataset. B4 is not ready.",
    }


def _not_registered_series() -> dict[str, object]:
    """The path exists, and its bytes are not the pinned series."""
    return {
        "file_present": True,
        "hash_match": False,
        "scored": False,
        "samples_counted": False,
        "samples_stored": False,
        "limit_applied": False,
        "sensor_range_applied": False,
        "external_limit_applied": False,
        "ready": False,
        "label": "NOT_VERIFIED",
        "note": "The file is not the registered one.",
    }


AS365_UFF = Path("data/as365/DataFiles_Type58UFF_AS365K2_AccelData.uff")
AS365_SHA256 = "b8f1a54300f12b05bb7f4f4802cd2d3f89b9aae6cf9fda81f4c287a263fb3c41"
BEARING_ZIP = Path("data/b4/data_SSF.zip")
BEARING_SHA256 = "816ccb70e9866692276bc3ab2095c885bdb39fe69b146e4163072d177d5aab0f"


def registered_bearing_zip() -> dict[str, object] | None:
    """Hash data_SSF.zip. Do not parse a file that is not the pin.

    None means the pinned path is not a file. A hash miss is not the
    registered series: no zip parse, no stored samples, and no limit.
    A hash hit does not parse either. The caller parses only that hit.
    """
    from evidence_kernel.paths import repo_root

    path = repo_root() / BEARING_ZIP
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != BEARING_SHA256:
        return _not_registered_series()
    return {
        "file_present": True,
        "hash_match": True,
        "scored": False,
        "samples_counted": False,
        "samples_stored": False,
        "limit_applied": False,
        "ready": False,
        "label": "NOT_VERIFIED",
    }


def inspect_as365_header() -> dict[str, object]:
    """Read the UFF header only when the file is the pinned series.

    A different hash is not the registered series. That file is not parsed,
    no samples are stored, and no limit is applied.
    """
    import tempfile

    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.ledger import Ledger
    from evidence_kernel.paths import repo_root

    path = repo_root() / AS365_UFF
    if not path.is_file():
        return {
            "file_present": False,
            "scored": False,
            "samples_counted": False,
            "label": "NOT_VERIFIED",
        }
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != AS365_SHA256:
        return _not_registered_series()
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(20):
            line = handle.readline()
            if line == "":
                break
            lines.append(line.rstrip("\n"))
    structure = _uff_structure(path)
    ordinate = _labelled_unit(lines, "Acceleration")
    abscissa = _labelled_unit(lines, "Time")
    limit_in_header = bool(structure["header_limit"])
    clip_in_header = bool(structure["header_token_60"])
    pint_ok = bool(ordinate) and units_compatible(str(ordinate), "meter / second ** 2")
    limit_reason = "limit_not_in_file" if not limit_in_header else "limit_not_applied"
    duration_matches = _duration_matches(structure["declared_counts"], 8192, 60)
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "as365.sqlite3", "bench")
        abstain_hash = enqueue(
            ledger,
            tenant_id="bench",
            actor_id="orchestrator",
            created_at="2026-11-04T19:40:00Z",
            reason=limit_reason,
        )
        length_hash = None
        if not duration_matches:
            length_hash = enqueue(
                ledger,
                tenant_id="bench",
                actor_id="orchestrator",
                created_at="2026-11-04T19:41:00Z",
                reason="record_length_disagrees",
            )
        series_violations = _abstain_violations(ledger.events())
    return {
        "file_present": True,
        "hash_match": True,
        "scored": False,
        "samples_counted": False,
        "record_count": structure["record_count"],
        "function_ids": structure["function_ids"],
        "declared_counts": structure["declared_counts"],
        "value_counts": structure["value_counts"],
        "structure_matches": structure["structure_matches"],
        "abscissa_steps": structure["abscissa_steps"],
        "step_matches_8192_hz": _steps_match_rate(structure["abscissa_steps"], 8192),
        "duration_at_8192_s": _exact_durations(structure["declared_counts"], 8192),
        "duration_matches_paper_60s": duration_matches,
        "ordinate_label": "Acceleration" if ordinate else None,
        "ordinate_unit": ordinate,
        "ordinate_units": structure["ordinate_units"],
        "abscissa_unit": abscissa,
        "pint_accepts_ordinate": pint_ok,
        "limit_in_header": limit_in_header,
        "suas_clip_limit_in_header": clip_in_header,
        "external_limit_applied": False,
        "abstain_reason": limit_reason,
        "abstain_hash": abstain_hash,
        "llm_numeric_violation": series_violations,
        "length_abstain_reason": None if duration_matches else "record_length_disagrees",
        "length_abstain_hash": length_hash,
        "label": "PARTIAL",
        "note": (
            "Header unit was read. Declared value counts were checked. "
            "No sample was stored. "
            f"{_limit_sentence(limit_in_header)} "
            f"{_clip_sentence(clip_in_header)} "
            "The 90-second header length does not match the article's 60-second record. "
            "The fetched article text does not state 90 seconds. Not scored."
        ),
    }


def _clip_sentence(clip_in_header: bool) -> str:
    if clip_in_header:
        return "The header states 60 with an acceleration unit. That figure is not applied."
    return "The sUAS clipping figure 60 m/s2 is not in this header and is not applied."


def _limit_sentence(limit_in_header: bool) -> str:
    if limit_in_header:
        return "A header line has the word limit and a number. That number was not applied."
    return "No exceedance limit is in the header."


def _header_has_suas_clip(lines: list[str]) -> bool:
    """60 next to an acceleration unit. A bare 60, or 60 seconds, is not that figure."""
    for line in lines:
        tokens = [part.strip(":,;").casefold() for part in line.split()]
        if "60" not in tokens and "60.0" not in tokens:
            continue
        compact = line.casefold().replace(" ", "")
        if "m/s^2" in compact or "m/s2" in compact:
            return True
    return False


def _header_has_limit(lines: list[str]) -> bool:
    """A whole word limit plus a number. The substring inside unlimited is not a limit."""
    for line in lines:
        words = [part.strip(":,;").casefold() for part in line.split()]
        if "limit" not in words:
            continue
        if any(_number_token(part) for part in line.split()):
            return True
    return False


def _number_token(part: str) -> bool:
    token = part.strip(":,;")
    if token == "":
        return False
    try:
        Decimal(token)
    except Exception:
        return False
    return True


def _uff_structure(path: Path) -> dict[str, object]:
    records = 0
    declared: list[int] = []
    increments: list[str] = []
    counts: list[int] = []
    ids: list[str] = []
    headers: list[str] = []
    ordinate_units: list[str] = []
    in_data = False
    current = 0
    saw_accel = False
    none_after = 0
    wait_id = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if text == "-1":
                if in_data:
                    counts.append(current)
                in_data = False
                current = 0
                saw_accel = False
                none_after = 0
                wait_id = False
                continue
            if not in_data:
                headers.append(text)
            if text == "58" and not in_data:
                records += 1
                wait_id = True
                continue
            if wait_id:
                ids.append(text.split()[0] if text else "")
                wait_id = False
                continue
            if not in_data and "Acceleration" in line:
                parts = line.split()
                ordinate_units.append(parts[-1] if parts else "")
                saw_accel = True
                continue
            if saw_accel and not in_data and "NONE" in line:
                none_after += 1
                if none_after == 2:
                    in_data = True
                continue
            if not in_data and not saw_accel:
                parts = text.split()
                if len(parts) >= 5 and parts[0] in {"2", "4", "5"}:
                    try:
                        declared.append(int(parts[1]))
                        Decimal(parts[4])
                        increments.append(parts[4])
                    except (ValueError, ArithmeticError):
                        pass
                continue
            if in_data:
                current += len(text.split())
    if in_data:
        counts.append(current)
    return {
        "record_count": records,
        "function_ids": ids,
        "declared_counts": declared,
        "abscissa_steps": increments,
        "value_counts": counts,
        "structure_matches": declared == counts and len(declared) == records and records > 0,
        "header_limit": _header_has_limit(headers),
        "header_token_60": _header_has_suas_clip(headers),
        "ordinate_units": ordinate_units,
    }


def _steps_match_rate(steps: object, hertz: int) -> bool:
    if not isinstance(steps, list) or not steps:
        return False
    exact = Decimal(1) / Decimal(hertz)
    for token in steps:
        if not isinstance(token, str):
            return False
        printed = format(exact, ".5E")
        if Decimal(token) != Decimal(printed):
            return False
    return True


def _exact_durations(counts: object, hertz: int) -> list[str]:
    if not isinstance(counts, list):
        return []
    durations: list[str] = []
    for count in counts:
        if not isinstance(count, int):
            return []
        durations.append(str(Decimal(count) / Decimal(hertz)))
    return durations


def _duration_matches(counts: object, hertz: int, seconds: int) -> bool:
    durations = _exact_durations(counts, hertz)
    if not durations:
        return False
    target = str(Decimal(seconds))
    return all(item == target for item in durations)


def _labelled_unit(lines: list[str], label: str) -> str | None:
    for line in lines:
        parts = line.split()
        if label in parts and parts:
            return parts[-1]
    return None
