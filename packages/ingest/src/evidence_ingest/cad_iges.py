"""Deterministic IGES 5.3 fixed-80-column ASCII CAD/PMI parser."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_ingest.blocks import Block, IngestAbstain
from evidence_ingest.cad_common import (
    compute_bbox_and_centroid,
    make_param_entry,
    parse_decimal_str,
)

_IGES_UNIT_MAP = {
    "1": "in",
    "2": "mm",
    "4": "ft",
    "5": "mi",
    "6": "m",
    "7": "km",
    "8": "mil",
    "9": "um",
    "10": "cm",
    "11": "uin",
}

_IGES_ENTITY_NAMES = {
    100: "CircularArc",
    102: "CompositeCurve",
    104: "ConicArc",
    106: "CopiousData",
    108: "Plane",
    110: "Line",
    112: "ParametricSplineCurve",
    114: "ParametricSplineSurface",
    116: "Point",
    118: "RuledSurface",
    120: "SurfaceOfRevolution",
    122: "TabulatedCylinder",
    124: "TransformationMatrix",
    126: "RationalBSplineCurve",
    128: "RationalBSplineSurface",
    142: "CurveOnParametricSurface",
    144: "TrimmedParametricSurface",
    212: "GeneralNote",
    214: "LeaderArrow",
    216: "LinearDimension",
    220: "OrdinateDimension",
    222: "RadiusDimension",
    308: "SubfigureDefinition",
    402: "AssociativityInstance",
    406: "Property",
    408: "SingularSubfigureInstance",
}


def _decode_hollerith_tokens(raw_text: str, param_delim: str, record_delim: str) -> list[str]:
    """Parse IGES parameter tokens supporting nH... Hollerith strings."""
    tokens: list[str] = []
    i = 0
    n = len(raw_text)
    while i < n:
        while i < n and raw_text[i].isspace():
            i += 1
        if i >= n:
            break
        if raw_text[i] == record_delim:
            break
        if raw_text[i] == param_delim:
            tokens.append("")
            i += 1
            continue
        # Check for Hollerith nH...
        j = i
        while j < n and raw_text[j].isdigit():
            j += 1
        if j > i and j < n and raw_text[j] in ("H", "h"):
            length = int(raw_text[i:j])
            start = j + 1
            val = raw_text[start : start + length]
            tokens.append(val.strip())
            i = start + length
            while i < n and raw_text[i].isspace():
                i += 1
            if i < n and raw_text[i] == param_delim:
                i += 1
            elif i < n and raw_text[i] == record_delim:
                break
            continue

        end = i
        while end < n and raw_text[end] not in (param_delim, record_delim):
            end += 1
        tokens.append(raw_text[i:end].strip())
        if end < n and raw_text[end] == param_delim:
            i = end + 1
        else:
            i = end
    return tokens


def _parse_global_section(global_lines: list[str]) -> dict[str, Any]:
    joined = "".join(line[:72] for line in global_lines).strip()
    if not joined:
        return {}
    param_delim = ","
    record_delim = ";"
    # IGES spec: first two parameters can override delimiters via 1Hx
    idx = 0
    if joined.startswith("1H") and len(joined) >= 3:
        param_delim = joined[2]
        idx = 3
        if idx < len(joined) and joined[idx] == param_delim:
            idx += 1
        if joined[idx : idx + 2] == "1H" and idx + 2 < len(joined):
            record_delim = joined[idx + 2]
    tokens = _decode_hollerith_tokens(joined, param_delim, record_delim)

    # Standard IGES Global parameter positions (0-indexed after delimiters):
    # 0: param delim, 1: record delim, 2: product_id_sender, 3: filename,
    # 4: native_system, 5: preprocessor_version, ..., 13: units_flag, 14: units_name,
    # 16: model_space_scale, 20: author, 21: organization, 22: iges_version
    def _at(pos: int) -> str:
        return tokens[pos] if pos < len(tokens) else ""

    units_flag = _at(13)
    units_name = _at(14) or _IGES_UNIT_MAP.get(units_flag, "")
    return {
        "param_delim": param_delim,
        "record_delim": record_delim,
        "product_id_sender": _at(2),
        "filename": _at(3),
        "native_system": _at(4),
        "preprocessor_version": _at(5),
        "units_flag": units_flag,
        "units": units_name.lower() if units_name else "mm",
        "model_space_scale": parse_decimal_str(_at(16)) or "1",
        "author": _at(20),
        "organization": _at(21),
        "iges_version": _at(22),
    }


def parse_iges(raw: bytes, source_hash: str) -> dict[str, Any]:
    """Parse IGES 5.3 fixed-80-column ASCII bytes into geometry, notes, and parameters."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    lines = text.splitlines()
    sections: dict[str, list[str]] = {"S": [], "G": [], "D": [], "P": [], "T": []}
    for line in lines:
        if len(line) < 73:
            continue
        sec = line[72].upper()
        if sec in sections:
            sections[sec].append(line)

    if not sections["G"] or not sections["D"] or not sections["P"]:
        raise IngestAbstain("invalid_iges")

    global_info = _parse_global_section(sections["G"])
    p_delim = str(global_info.get("param_delim") or ",")
    r_delim = str(global_info.get("record_delim") or ";")
    unit = str(global_info.get("units") or "mm")

    # Parse Directory Entry pairs (every 2 lines = 1 entity)
    de_lines = sections["D"]
    if len(de_lines) < 2:
        raise IngestAbstain("empty_iges")

    de_records: dict[int, dict[str, Any]] = {}
    for idx in range(0, len(de_lines) - 1, 2):
        l1 = de_lines[idx]
        l2 = de_lines[idx + 1]
        try:
            etype = int(l1[0:8].strip() or "0")
            param_ptr = int(l1[8:16].strip() or "0")
            seq_no = int(l1[73:80].strip() or str(idx + 1))
        except ValueError:
            continue
        form = int(l2[32:40].strip() or "0") if l2[32:40].strip().isdigit() else 0
        label = l2[56:64].strip()
        de_records[seq_no] = {
            "de_seq": seq_no,
            "entity_type": etype,
            "entity_name": _IGES_ENTITY_NAMES.get(etype, f"Entity_{etype}"),
            "param_ptr": param_ptr,
            "form": form,
            "label": label,
        }

    # Group Parameter Data lines by DE sequence pointer (cols 65-72)
    param_chunks: dict[int, list[str]] = {}
    for p_line in sections["P"]:
        de_ptr_raw = p_line[64:72].strip()
        if not de_ptr_raw.isdigit():
            continue
        de_ptr = int(de_ptr_raw)
        param_chunks.setdefault(de_ptr, []).append(p_line[:64])

    points: list[tuple[Decimal, Decimal, Decimal]] = []
    annotations: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    entity_counts: dict[str, int] = {}

    for de_seq, de in de_records.items():
        ename = de["entity_name"]
        entity_counts[ename] = entity_counts.get(ename, 0) + 1
        chunk = "".join(param_chunks.get(de_seq, []))
        if not chunk:
            continue
        tokens = _decode_hollerith_tokens(chunk, p_delim, r_delim)
        if not tokens:
            continue

        etype = de["entity_type"]
        if etype == 116 and len(tokens) >= 4:  # Point
            sx = parse_decimal_str(tokens[1])
            sy = parse_decimal_str(tokens[2])
            sz = parse_decimal_str(tokens[3])
            if sx and sy and sz:
                points.append((Decimal(sx), Decimal(sy), Decimal(sz)))
        elif etype == 110 and len(tokens) >= 7:  # Line
            for base in (1, 4):
                sx = parse_decimal_str(tokens[base])
                sy = parse_decimal_str(tokens[base + 1])
                sz = parse_decimal_str(tokens[base + 2])
                if sx and sy and sz:
                    points.append((Decimal(sx), Decimal(sy), Decimal(sz)))
        elif etype == 126 and len(tokens) >= 8:  # Rational B-Spline Curve
            try:
                k_idx = int(tokens[1])
                num_poles = k_idx + 1
                m_deg = int(tokens[2])
                knot_count = num_poles + m_deg + 1
                w_start = 7 + knot_count
                pts_start = w_start + num_poles
                for p_i in range(num_poles):
                    off = pts_start + 3 * p_i
                    if off + 2 < len(tokens):
                        sx = parse_decimal_str(tokens[off])
                        sy = parse_decimal_str(tokens[off + 1])
                        sz = parse_decimal_str(tokens[off + 2])
                        if sx and sy and sz:
                            points.append((Decimal(sx), Decimal(sy), Decimal(sz)))
            except ValueError:
                pass
        elif etype == 212:  # General Note (PMI / GD&T text)
            # Extract trailing/non-numeric Hollerith strings
            note_texts = [t for t in tokens[1:] if t and parse_decimal_str(t) is None]
            if note_texts:
                annotations.append(
                    {
                        "de_seq": de_seq,
                        "label": de["label"] or f"NOTE_{de_seq}",
                        "text": " ".join(note_texts),
                    }
                )
        elif etype == 406 and len(tokens) >= 3:  # Property
            pname = de["label"] or f"IGES_PROP_{de_seq}"
            val = parse_decimal_str(tokens[2])
            if val is not None:
                parameters.append(
                    make_param_entry(
                        path=f"IGES\\Properties\\{pname}",
                        name=pname,
                        value=val,
                        unit=unit,
                        source_kind="iges",
                    )
                )

    bbox, centroid = compute_bbox_and_centroid(points)
    cg_points: list[dict[str, Any]] = []
    if centroid is not None:
        cg_points.append(
            {
                "label": "IGES_Geometric_Centroid_ESTIMATE",
                "coords": centroid,
                "unit": unit,
                "source_kind": "iges_estimate",
            }
        )

    start_text = " ".join(line[:72].strip() for line in sections["S"] if line[:72].strip())
    block_lines: list[str] = [
        f"IGES {global_info.get('iges_version') or '5.3'} | Product: "
        f"{global_info.get('product_id_sender') or 'UNKNOWN'} | Units: {unit} | "
        f"Entities: {len(de_records)}"
    ]
    if start_text:
        block_lines.append(f"IGES Start: {start_text}")
    for ann in annotations:
        block_lines.append(f"IGES GeneralNote [{ann['label']}]: {ann['text']}")

    blocks: list[Block] = []
    offset = 0
    for line in block_lines:
        blocks.append(
            Block(
                text=line,
                span_start=offset,
                span_end=offset + len(line),
                source_hash=source_hash,
                block_kind="iges",
            )
        )
        offset += len(line) + 1

    return {
        "format": "iges",
        "global": global_info,
        "units": {"length": unit},
        "entity_count": len(de_records),
        "entity_counts": entity_counts,
        "annotations": annotations,
        "parameters": parameters,
        "cg_points": cg_points,
        "bbox": bbox,
        "point_count": len(points),
        "blocks": blocks,
    }
