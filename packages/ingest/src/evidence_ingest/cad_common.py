"""Shared deterministic numeric and geometry helpers for CAD/CAE ingestion."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from evidence_ingest.blocks import Block

_NASTRAN_SHORT_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d+)$")


def parse_decimal_str(raw: str | None, *, allow_nastran_short: bool = False) -> str | None:
    """Parse an ASCII numeric token into a canonical Decimal string without floats."""
    if raw is None:
        return None
    token = raw.strip().replace("D", "E").replace("d", "e")
    if not token:
        return None
    if allow_nastran_short and "e" not in token.lower():
        match = _NASTRAN_SHORT_RE.match(token)
        if match:
            token = f"{match.group(1)}E{match.group(2)}"
    try:
        dec = Decimal(token)
    except InvalidOperation:
        return None
    if not dec.is_finite():
        return None
    normalized = format(dec.normalize(), "f") if dec != 0 else "0"
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".") or "0"
    return normalized


def decimal_str(value: Decimal, quantum: str = "0.000001") -> str:
    """Format a Decimal cleanly without scientific notation."""
    if value == 0:
        return "0"
    q = Decimal(quantum)
    quantized = value.quantize(q)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".") or "0"
    return text


def compute_bbox_and_centroid(
    points: list[tuple[Decimal, Decimal, Decimal]],
) -> tuple[dict[str, list[str]] | None, list[str] | None]:
    """Compute exact Decimal [min, max] bounding box and geometric centroid."""
    if not points:
        return None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    count = Decimal(len(points))
    bbox = {
        "min": [decimal_str(min(xs)), decimal_str(min(ys)), decimal_str(min(zs))],
        "max": [decimal_str(max(xs)), decimal_str(max(ys)), decimal_str(max(zs))],
    }
    centroid = [
        decimal_str(sum(xs, Decimal(0)) / count),
        decimal_str(sum(ys, Decimal(0)) / count),
        decimal_str(sum(zs, Decimal(0)) / count),
    ]
    return bbox, centroid


def blocks_from_lines_with_spans(
    lines: list[tuple[str, int, int]],
    source_hash: str,
    *,
    block_kind: str = "cad_cae",
) -> list[Block]:
    """Build span-tracked Block objects from pre-sliced (text, start, end) tuples."""
    blocks: list[Block] = []
    for text, start, end in lines:
        cleaned = text.strip()
        if cleaned:
            blocks.append(
                Block(
                    text=cleaned,
                    span_start=start,
                    span_end=end,
                    source_hash=source_hash,
                    block_kind=block_kind,
                )
            )
    return blocks


def make_param_entry(
    *,
    path: str,
    name: str,
    value: Any,
    unit: str = "",
    source_kind: str,
    formula: str = "",
) -> dict[str, Any]:
    """Normalized Knowledgeware / CAD / FEM parameter entry."""
    return {
        "path": path,
        "name": name,
        "value": value,
        "unit": unit,
        "source_kind": source_kind,
        "formula": formula,
    }
