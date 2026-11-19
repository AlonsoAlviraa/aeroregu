"""Deterministic STEP AP242 (ISO 10303-21 / ISO 10303-242) + semantic GD&T parser."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from evidence_ingest.blocks import Block, IngestAbstain
from evidence_ingest.cad_common import (
    compute_bbox_and_centroid,
    make_param_entry,
    parse_decimal_str,
)

_ENTITY_RE = re.compile(r"#(\d+)\s*=\s*(.+)$", re.DOTALL)
_HEADER_ITEM_RE = re.compile(
    r"\b(FILE_DESCRIPTION|FILE_NAME|FILE_SCHEMA)\s*\((.*)\)\s*$", re.DOTALL
)

_GDT_TYPES = {
    "GEOMETRIC_TOLERANCE",
    "GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE",
    "GEOMETRIC_TOLERANCE_WITH_MODIFIERS",
    "FLATNESS_TOLERANCE",
    "STRAIGHTNESS_TOLERANCE",
    "CIRCULARITY_TOLERANCE",
    "CYLINDRICITY_TOLERANCE",
    "PERPENDICULARITY_TOLERANCE",
    "PARALLELISM_TOLERANCE",
    "ANGULARITY_TOLERANCE",
    "POSITION_TOLERANCE",
    "CONCENTRICITY_TOLERANCE",
    "SYMMETRY_TOLERANCE",
    "LINE_PROFILE_TOLERANCE",
    "PROFILE_LINE_TOLERANCE",
    "SURFACE_PROFILE_TOLERANCE",
    "PROFILE_SURFACE_TOLERANCE",
    "CIRCULAR_RUNOUT_TOLERANCE",
    "TOTAL_RUNOUT_TOLERANCE",
    "RUNOUT_TOLERANCE",
}

_SI_PREFIX = {
    "EXA": "E",
    "PETA": "P",
    "TERA": "T",
    "GIGA": "G",
    "MEGA": "M",
    "KILO": "k",
    "HECTO": "h",
    "DECA": "da",
    "DECI": "d",
    "CENTI": "c",
    "MILLI": "m",
    "MICRO": "u",
    "NANO": "n",
}

_SI_BASE = {
    "METRE": "m",
    "GRAM": "g",
    "SECOND": "s",
    "RADIAN": "rad",
    "STERADIAN": "sr",
    "NEWTON": "N",
    "PASCAL": "Pa",
    "KELVIN": "K",
}


def _strip_step_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
            i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break
            out.append(" ")
            i = end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_statements(section_text: str) -> list[str]:
    stmts: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    n = len(section_text)
    while i < n:
        ch = section_text[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and section_text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf.clear()
        else:
            buf.append(ch)
        i += 1
    return stmts


def _split_args(arg_str: str) -> list[Any]:
    args: list[Any] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    i = 0
    n = len(arg_str)
    while i < n:
        ch = arg_str[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and arg_str[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append(_parse_token("".join(buf).strip()))
            buf.clear()
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        args.append(_parse_token(tail))
    return args


def _parse_token(tok: str) -> Any:
    if not tok or tok == "$" or tok == "*":
        return None
    if tok.startswith("'") and tok.endswith("'") and len(tok) >= 2:
        return tok[1:-1].replace("''", "'")
    if tok.startswith("(") and tok.endswith(")"):
        return _split_args(tok[1:-1].strip())
    if tok.startswith(".") and tok.endswith(".") and len(tok) >= 2:
        return f".{tok[1:-1].strip()}."
    if tok.startswith("#") and tok[1:].isdigit():
        return tok
    # Typed STEP parameter e.g. LENGTH_MEASURE(0.05) or POSITIVE_LENGTH_MEASURE(0.05)
    paren = tok.find("(")
    if paren > 0 and tok.endswith(")"):
        fn_name = tok[:paren].strip().upper()
        inner = _split_args(tok[paren + 1 : -1].strip())
        return {"_typed": fn_name, "args": inner}
    return tok


def _parse_complex_components(rhs: str) -> list[tuple[str, list[Any]]]:
    """Parse complex entity '(TYPE1(...) TYPE2(...))' or simple 'TYPE(...)'."""
    s = rhs.strip()
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].strip()
        components: list[tuple[str, list[Any]]] = []
        i = 0
        n = len(inner)
        while i < n:
            while i < n and inner[i].isspace():
                i += 1
            if i >= n:
                break
            paren = inner.find("(", i)
            if paren == -1:
                break
            name = inner[i:paren].strip().upper()
            depth = 1
            j = paren + 1
            in_str = False
            while j < n and depth > 0:
                c = inner[j]
                if in_str:
                    if c == "'":
                        if j + 1 < n and inner[j + 1] == "'":
                            j += 2
                            continue
                        in_str = False
                else:
                    if c == "'":
                        in_str = True
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                j += 1
            args = _split_args(inner[paren + 1 : j - 1])
            components.append((name, args))
            i = j
        return components

    paren = s.find("(")
    if paren > 0 and s.endswith(")"):
        return [(s[:paren].strip().upper(), _split_args(s[paren + 1 : -1]))]
    return []


def _format_unit(components: list[tuple[str, list[Any]]]) -> tuple[str, str]:
    """Return (dimension_kind, unit_symbol) from unit entity components."""
    dim = ""
    symbol = ""
    for etype, args in components:
        if "LENGTH_UNIT" in etype:
            dim = "length"
        elif "MASS_UNIT" in etype:
            dim = "mass"
        elif "PLANE_ANGLE_UNIT" in etype:
            dim = "angle"
        elif "SOLID_ANGLE_UNIT" in etype:
            dim = "solid_angle"
        if "SI_UNIT" in etype and len(args) >= 2:
            pref = str(args[0] or "").strip(".").upper()
            base = str(args[1] or "").strip(".").upper()
            p_sym = _SI_PREFIX.get(pref, "")
            b_sym = _SI_BASE.get(base, base.lower())
            symbol = f"{p_sym}{b_sym}"
        elif "CONVERSION_BASED_UNIT" in etype and args:
            name = str(args[0] or "").strip().lower()
            alias = {"inch": "in", "foot": "ft", "pound": "lb", "degree": "deg"}
            symbol = alias.get(name, name)
    return dim, symbol


def _unwrap_measure(val: Any) -> tuple[str | None, str]:
    if isinstance(val, dict) and "_typed" in val:
        inner = val.get("args") or []
        num = parse_decimal_str(str(inner[0])) if inner else None
        return num, str(val["_typed"])
    if isinstance(val, str):
        return parse_decimal_str(val), ""
    return None, ""


def _collect_refs(obj: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(obj, str) and obj.startswith("#") and obj[1:].isdigit():
        refs.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(_collect_refs(item))
    elif isinstance(obj, dict) and "args" in obj:
        refs.extend(_collect_refs(obj["args"]))
    return refs


def parse_step_ap242(raw: bytes, source_hash: str) -> dict[str, Any]:
    """Parse STEP AP242 / ISO 10303-21 bytes into structured geometry, GD&T/PMI, and params."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    cleaned = _strip_step_comments(text)
    upper = cleaned.upper()
    if "ISO-10303-21" not in upper or "DATA;" not in upper:
        raise IngestAbstain("invalid_step_p21")

    header_start = upper.find("HEADER;")
    data_start = upper.find("DATA;")
    end_pos = upper.find("END-ISO-10303-21")
    if data_start == -1 or (end_pos != -1 and end_pos < data_start):
        raise IngestAbstain("invalid_step_p21")

    header_text = (
        cleaned[header_start + len("HEADER;") : data_start]
        if 0 <= header_start < data_start
        else ""
    )
    data_end = end_pos if end_pos != -1 else len(cleaned)
    data_text = cleaned[data_start + len("DATA;") : data_end]

    header_info: dict[str, Any] = {
        "description": [],
        "name": "",
        "timestamp": "",
        "author": [],
        "organization": [],
        "originating_system": "",
        "schemas": [],
    }
    for stmt in _split_statements(header_text):
        m = _HEADER_ITEM_RE.match(stmt.strip())
        if not m:
            continue
        kind = m.group(1).upper()
        args = _split_args(m.group(2))
        if kind == "FILE_DESCRIPTION" and args:
            header_info["description"] = args[0] if isinstance(args[0], list) else [args[0]]
        elif kind == "FILE_NAME" and args:
            header_info["name"] = str(args[0] or "")
            if len(args) > 1:
                header_info["timestamp"] = str(args[1] or "")
            if len(args) > 2:
                header_info["author"] = args[2] if isinstance(args[2], list) else [args[2]]
            if len(args) > 3:
                header_info["organization"] = args[3] if isinstance(args[3], list) else [args[3]]
            if len(args) > 5:
                header_info["originating_system"] = str(args[5] or "")
        elif kind == "FILE_SCHEMA" and args:
            raw_schemas = args[0] if isinstance(args[0], list) else [args[0]]
            header_info["schemas"] = [str(s) for s in raw_schemas if s]

    entities: dict[str, list[tuple[str, list[Any]]]] = {}
    for stmt in _split_statements(data_text):
        m = _ENTITY_RE.match(stmt)
        if not m:
            continue
        eid = f"#{m.group(1)}"
        comps = _parse_complex_components(m.group(2))
        if comps:
            entities[eid] = comps

    if not entities:
        raise IngestAbstain("empty_step_data")

    schemas_joined = " ".join(header_info["schemas"]).upper()
    ap_level = (
        "AP242"
        if "AP242" in schemas_joined
        else (
            "AP214"
            if "AP214" in schemas_joined
            else ("AP203" if "AP203" in schemas_joined else "STEP")
        )
    )

    units: dict[str, str] = {}
    cartesian_points: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    products: list[dict[str, str]] = []
    assembly_links: list[dict[str, str]] = []
    datums: dict[str, dict[str, str]] = {}
    datum_features: dict[str, str] = {}
    datum_refs: dict[str, dict[str, Any]] = {}
    shape_aspects: dict[str, str] = {}
    measure_items: dict[str, dict[str, Any]] = {}
    descriptive_items: dict[str, dict[str, str]] = {}
    gdt_entities: list[tuple[str, str, list[Any]]] = []
    dim_entities: list[tuple[str, str, list[Any]]] = []
    plus_minus_tols: list[tuple[str, list[Any]]] = []
    tol_values: dict[str, dict[str, Any]] = {}
    prop_defs: list[tuple[str, list[Any]]] = []
    prop_reps: list[tuple[str, list[Any]]] = []
    rep_items_by_rep: dict[str, list[str]] = {}

    for eid, comps in entities.items():
        dim, sym = _format_unit(comps)
        if sym:
            units[eid] = sym
            if dim:
                units.setdefault(dim, sym)

        for etype, args in comps:
            if etype == "CARTESIAN_POINT" and len(args) >= 2 and isinstance(args[1], list):
                coords = args[1]
                if len(coords) >= 3:
                    sx = parse_decimal_str(str(coords[0]))
                    sy = parse_decimal_str(str(coords[1]))
                    sz = parse_decimal_str(str(coords[2]))
                    if sx is not None and sy is not None and sz is not None:
                        cartesian_points[eid] = (Decimal(sx), Decimal(sy), Decimal(sz))
            elif etype == "PRODUCT" and args:
                products.append(
                    {
                        "entity_id": eid,
                        "id": str(args[0] or ""),
                        "name": str(args[1] or args[0] or "")
                        if len(args) > 1
                        else str(args[0] or ""),
                    }
                )
            elif etype == "NEXT_ASSEMBLY_USAGE_OCCURRENCE" and len(args) >= 5:
                assembly_links.append(
                    {
                        "entity_id": eid,
                        "id": str(args[0] or ""),
                        "name": str(args[1] or ""),
                        "relating_product_def": str(args[3] or ""),
                        "related_product_def": str(args[4] or ""),
                    }
                )
            elif etype == "SHAPE_ASPECT" and args:
                shape_aspects[eid] = str(args[0] or "")
            elif etype == "DATUM" and args:
                ident = str(args[-1] or args[0] or "")
                datums[eid] = {"entity_id": eid, "label": ident, "name": str(args[0] or "")}
            elif etype == "DATUM_FEATURE" and args:
                datum_features[eid] = str(args[0] or "")
            elif etype in {
                "DATUM_REFERENCE",
                "DATUM_REFERENCE_ELEMENT",
                "DATUM_REFERENCE_COMPARTMENT",
            }:
                datum_refs[eid] = {
                    "entity_id": eid,
                    "etype": etype,
                    "refs": _collect_refs(args),
                    "args": args,
                }
            elif (
                etype in {"MEASURE_REPRESENTATION_ITEM", "VALUE_REPRESENTATION_ITEM"}
                and len(args) >= 2
            ):
                val, mtype = _unwrap_measure(args[1])
                unit_ref = str(args[2]) if len(args) > 2 and isinstance(args[2], str) else ""
                measure_items[eid] = {
                    "entity_id": eid,
                    "name": str(args[0] or ""),
                    "value": val,
                    "measure_type": mtype,
                    "unit": units.get(unit_ref, ""),
                }
            elif etype == "LENGTH_MEASURE_WITH_UNIT" and len(args) >= 2:
                val, mtype = _unwrap_measure(args[0])
                unit_ref = str(args[1]) if isinstance(args[1], str) else ""
                measure_items[eid] = {
                    "entity_id": eid,
                    "name": "length_measure",
                    "value": val,
                    "measure_type": mtype,
                    "unit": units.get(unit_ref, ""),
                }
            elif etype == "DESCRIPTIVE_REPRESENTATION_ITEM" and len(args) >= 2:
                descriptive_items[eid] = {
                    "entity_id": eid,
                    "name": str(args[0] or ""),
                    "description": str(args[1] or ""),
                }
            elif etype in _GDT_TYPES:
                gdt_entities.append((eid, etype, args))
            elif etype in {"DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION"}:
                dim_entities.append((eid, etype, args))
            elif etype == "PLUS_MINUS_TOLERANCE":
                plus_minus_tols.append((eid, args))
            elif etype == "TOLERANCE_VALUE" and len(args) >= 2:
                lo, _ = _unwrap_measure(args[0])
                hi, _ = _unwrap_measure(args[1])
                tol_values[eid] = {"lower": lo, "upper": hi}
            elif etype == "PROPERTY_DEFINITION" and args:
                prop_defs.append((eid, args))
            elif etype == "PROPERTY_DEFINITION_REPRESENTATION" and len(args) >= 2:
                prop_reps.append((eid, args))
            elif (
                etype
                in {"REPRESENTATION", "SHAPE_REPRESENTATION", "ADVANCED_BREP_SHAPE_REPRESENTATION"}
                and len(args) >= 2
            ):
                rep_items_by_rep[eid] = _collect_refs(args[1])

    # Resolve unit table again now that all unit entities have been scanned
    for eid, comps in entities.items():
        if eid not in units:
            _, sym = _format_unit(comps)
            if sym:
                units[eid] = sym
    for item in measure_items.values():
        if not item["unit"]:
            # Look up raw entity arg for late unit ref
            comps = entities.get(item["entity_id"], [])
            for _, args in comps:
                for ref in _collect_refs(args):
                    if ref in units:
                        item["unit"] = units[ref]
                        break

    # Resolve Datum Reference Labels
    def _resolve_datum_labels(refs: list[str]) -> list[str]:
        labels: list[str] = []
        visited: set[str] = set()
        stack = list(refs)
        while stack:
            ref = stack.pop(0)
            if ref in visited:
                continue
            visited.add(ref)
            if ref in datums and datums[ref]["label"]:
                labels.append(datums[ref]["label"])
            elif ref in datum_features and datum_features[ref]:
                labels.append(datum_features[ref])
            elif ref in datum_refs:
                stack.extend(datum_refs[ref]["refs"])
            elif ref in entities:
                for etype, args in entities[ref]:
                    if etype in {
                        "DATUM_SYSTEM",
                        "DATUM_REFERENCE_COMPARTMENT",
                        "DATUM_REFERENCE_ELEMENT",
                        "DATUM_REFERENCE",
                    }:
                        stack.extend(_collect_refs(args))
                    elif etype == "DATUM" and args:
                        labels.append(str(args[-1] or args[0] or ref))
        deduped: list[str] = []
        for lbl in labels:
            clean_lbl = lbl.strip()
            if clean_lbl and clean_lbl not in deduped:
                deduped.append(clean_lbl)
        return deduped

    gdt_pmi: list[dict[str, Any]] = []
    for eid, etype, args in gdt_entities:
        # AP242 GEOMETRIC_TOLERANCE(name, desc, mag, shape_aspect, [modifiers], [datum_system])
        name = str(args[0] or etype) if args else etype
        desc = str(args[1] or "") if len(args) > 1 else ""
        tol_val: str | None = None
        tol_unit = units.get("length", "mm")
        applied_to = ""
        datum_labels: list[str] = []
        modifiers: list[str] = []

        for arg in args[2:]:
            if isinstance(arg, str) and arg.startswith("#"):
                if arg in measure_items:
                    tol_val = measure_items[arg]["value"]
                    if measure_items[arg]["unit"]:
                        tol_unit = measure_items[arg]["unit"]
                elif arg in shape_aspects:
                    applied_to = shape_aspects[arg]
                elif arg in datum_features:
                    applied_to = datum_features[arg]
                else:
                    d_lbls = _resolve_datum_labels([arg])
                    datum_labels.extend(d_lbls)
            elif isinstance(arg, list):
                for sub in arg:
                    if isinstance(sub, str) and sub.startswith(".") and sub.endswith("."):
                        modifiers.append(sub.strip("."))
                    elif isinstance(sub, str) and sub.startswith("#"):
                        datum_labels.extend(_resolve_datum_labels([sub]))
            elif isinstance(arg, str) and arg.startswith(".") and arg.endswith("."):
                modifiers.append(arg.strip("."))

        # Deduplicate datum_labels preserving order
        seen_d: list[str] = []
        for d in datum_labels:
            if d not in seen_d:
                seen_d.append(d)

        gdt_pmi.append(
            {
                "entity_id": eid,
                "gdt_type": etype,
                "name": name,
                "description": desc,
                "tolerance_value": tol_val,
                "unit": tol_unit,
                "datum_refs": seen_d,
                "modifiers": modifiers,
                "applied_to": applied_to,
            }
        )

    # Extract dimensional tolerances (PLUS_MINUS_TOLERANCE + DIMENSIONAL_SIZE)
    dim_map: dict[str, dict[str, Any]] = {}
    for eid, etype, args in dim_entities:
        name = str(args[1] if len(args) > 1 else args[0] or etype)
        dim_map[eid] = {"entity_id": eid, "kind": etype, "name": name}
    for eid, args in plus_minus_tols:
        if len(args) >= 2:
            tol_ref = str(args[0] or "")
            dim_ref = str(args[1] or "")
            tv = tol_values.get(tol_ref)
            dm = dim_map.get(dim_ref)
            if tv and dm:
                gdt_pmi.append(
                    {
                        "entity_id": eid,
                        "gdt_type": "PLUS_MINUS_TOLERANCE",
                        "name": dm["name"],
                        "description": f"lower={tv['lower']}, upper={tv['upper']}",
                        "tolerance_value": tv["upper"] or tv["lower"],
                        "lower_deviation": tv["lower"],
                        "upper_deviation": tv["upper"],
                        "unit": units.get("length", "mm"),
                        "datum_refs": [],
                        "modifiers": [],
                        "applied_to": dm["name"],
                    }
                )

    # Extract mass/CG properties and parameters from PROPERTY_DEFINITION_REPRESENTATION.
    parameters: list[dict[str, Any]] = []
    cg_points: list[dict[str, Any]] = []
    prop_name_by_id: dict[str, str] = {}
    for eid, args in prop_defs:
        prop_name_by_id[eid] = str(args[0] or "")

    for _, args in prop_reps:
        if len(args) < 2:
            continue
        pdef_ref = str(args[0] or "")
        rep_ref = str(args[1] or "")
        prop_name = prop_name_by_id.get(pdef_ref, "")
        rep_items = rep_items_by_rep.get(rep_ref, [])
        for ritem in rep_items:
            if ritem in measure_items:
                mi = measure_items[ritem]
                if mi["value"] is not None:
                    pname = mi["name"] or prop_name or ritem
                    parameters.append(
                        make_param_entry(
                            path=f"STEP\\{prop_name or 'Properties'}\\{pname}",
                            name=pname,
                            value=mi["value"],
                            unit=mi["unit"],
                            source_kind="step_ap242",
                        )
                    )
            elif ritem in cartesian_points and any(
                k in prop_name.lower() for k in ("cg", "gravity", "mass_cent", "centroid")
            ):
                pt = cartesian_points[ritem]
                coords = [str(pt[0]), str(pt[1]), str(pt[2])]
                cg_points.append(
                    {
                        "label": prop_name or "STEP_CG",
                        "coords": coords,
                        "unit": units.get("length", "mm"),
                        "source_kind": "step_ap242",
                    }
                )

    # Also capture standalone named measure items not already added
    seen_param_names = {p["name"] for p in parameters}
    for eid, mi in measure_items.items():
        if (
            mi["value"] is not None
            and mi["name"] not in seen_param_names
            and mi["name"] != "length_measure"
        ):
            seen_param_names.add(mi["name"])
            parameters.append(
                make_param_entry(
                    path=f"STEP\\Measures\\{mi['name']}",
                    name=mi["name"],
                    value=mi["value"],
                    unit=mi["unit"],
                    source_kind="step_ap242",
                )
            )

    # Geometric bounding box & centroid from CARTESIAN_POINTs
    bbox, geo_centroid = compute_bbox_and_centroid(list(cartesian_points.values()))
    if not cg_points and geo_centroid is not None:
        cg_points.append(
            {
                "label": "STEP_Geometric_Centroid_ESTIMATE",
                "coords": geo_centroid,
                "unit": units.get("length", "mm"),
                "source_kind": "step_ap242_estimate",
            }
        )

    # Build deterministic span-tracked blocks for requirement/audit linking
    block_lines: list[str] = [
        f"STEP {ap_level} Schema: {', '.join(header_info['schemas']) or 'UNKNOWN'} | "
        f"System: {header_info['originating_system'] or 'UNKNOWN'} | "
        f"Products: {len(products)} | GD&T/PMI: {len(gdt_pmi)}"
    ]
    for item in descriptive_items.values():
        block_lines.append(
            f"STEP PMI Note [{item['entity_id']}]: {item['name']} - {item['description']}"
        )
    for g in gdt_pmi:
        d_str = f" Datums=[{','.join(g['datum_refs'])}]" if g["datum_refs"] else ""
        block_lines.append(
            f"STEP GD&T [{g['entity_id']}] {g['gdt_type']}: {g['name']} = "
            f"{g['tolerance_value'] or 'N/A'} {g['unit']}{d_str}"
        )
    blocks: list[Block] = []
    offset = 0
    for line in block_lines:
        blocks.append(
            Block(
                text=line,
                span_start=offset,
                span_end=offset + len(line),
                source_hash=source_hash,
                block_kind="step_ap242",
            )
        )
        offset += len(line) + 1

    from evidence_ingest.cad_brep import analyze_step_brep

    brep_report = analyze_step_brep(raw, source_hash)
    if brep_report.get("solid_count", 0) > 0:
        existing_names = {str(p.get("name", "")) for p in parameters}
        for bp in brep_report.get("parameters", []):
            if str(bp.get("name", "")) not in existing_names:
                parameters.append(bp)

    return {
        "format": "step_ap242",
        "ap_level": ap_level,
        "header": header_info,
        "units": {k: v for k, v in units.items() if not k.startswith("#")},
        "entity_count": len(entities),
        "products": products,
        "assembly_links": assembly_links,
        "gdt_pmi": gdt_pmi,
        "parameters": parameters,
        "cg_points": cg_points,
        "bbox": bbox,
        "cartesian_point_count": len(cartesian_points),
        "brep": brep_report,
        "blocks": blocks,
    }
