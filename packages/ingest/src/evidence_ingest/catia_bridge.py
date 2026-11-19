"""Deterministic CATIA XML / Knowledgeware & native .CATPart/.CATProduct tree parser."""

from __future__ import annotations

import io
import re
from typing import Any

import olefile
from defusedxml import ElementTree as SafeET

from evidence_ingest.blocks import Block, IngestAbstain
from evidence_ingest.cad_common import make_param_entry, parse_decimal_str

_KW_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_\\/.:-]+)\s*=\s*([^\s#']+?)(?:\s+([A-Za-z0-9_*/^.-]+))?\s*$"
)


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _attr_ci(elem: Any, *names: str) -> str:
    lower_map = {k.lower(): str(v) for k, v in elem.attrib.items()}
    for name in names:
        val = lower_map.get(name.lower())
        if val is not None and val.strip():
            return val.strip()
    return ""


def _child_text_ci(elem: Any, *names: str) -> str:
    want = {n.lower() for n in names}
    for child in elem:
        if _local_tag(child.tag).lower() in want and child.text:
            return child.text.strip()
    return ""


def _normalize_value(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if ";" in text:
        parts = [p.strip() for p in text.split(";") if p.strip()]
        if parts:
            norm_parts = []
            for part in parts:
                if part.lower() in {"true", "false"}:
                    norm_parts.append(part.lower() == "true")
                else:
                    dec = parse_decimal_str(part)
                    norm_parts.append(dec if dec is not None else part)
            return norm_parts
    dec = parse_decimal_str(text)
    if dec is not None:
        return dec
    return text


def _split_value_and_unit(raw_val: str, explicit_unit: str) -> tuple[str, str]:
    val = raw_val.strip()
    if explicit_unit:
        return val, explicit_unit
    # Handle "9800.000 N" or "800 kg" inside XML value
    parts = val.split()
    if len(parts) == 2 and parse_decimal_str(parts[0]) is not None:
        return parts[0], parts[1]
    return val, ""


def _parse_catia_xml_text(xml_text: str, source_hash: str, *, origin_label: str) -> dict[str, Any]:
    try:
        root = SafeET.fromstring(xml_text)
    except Exception as exc:
        raise IngestAbstain("invalid_catia_xml") from exc

    parameters: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []
    cg_points: list[dict[str, Any]] = []
    gdt_pmi: list[dict[str, Any]] = []
    product_tree: list[dict[str, Any]] = []

    def _walk(node: Any, path_stack: list[str], tree_children: list[dict[str, Any]]) -> None:
        tag = _local_tag(node.tag)
        tag_low = tag.lower()
        node_name = _attr_ci(node, "name", "id", "title", "alias") or _child_text_ci(node, "name")

        if tag_low in {"catproduct", "catpart", "product", "part", "component", "parameterset"}:
            label = node_name or tag
            branch: dict[str, Any] = {
                "kind": tag,
                "name": label,
                "children": [],
                "parameters": [],
            }
            tree_children.append(branch)
            next_stack = [*path_stack, label]
            for child in node:
                _walk(child, next_stack, branch["children"])
            # Attach parameters belonging to this branch level
            branch_prefix = "\\".join(next_stack)
            branch["parameters"] = [
                p["name"] for p in parameters if p["path"].startswith(branch_prefix + "\\")
            ]
            return

        if tag_low in {"parameter", "param", "knowledgeparameter", "attribute"}:
            pname = node_name or _attr_ci(node, "key")
            raw_v = (
                _attr_ci(node, "value", "val")
                or _child_text_ci(node, "value", "val")
                or (node.text or "").strip()
            )
            raw_u = _attr_ci(node, "unit", "units", "uom") or _child_text_ci(node, "unit", "units")
            val_str, unit_str = _split_value_and_unit(raw_v, raw_u)
            formula = _attr_ci(node, "formula", "relation") or _child_text_ci(node, "formula")
            if pname and val_str != "":
                full_path = "\\".join([*path_stack, pname]) if path_stack else pname
                entry = make_param_entry(
                    path=full_path,
                    name=pname,
                    value=_normalize_value(val_str),
                    unit=unit_str,
                    source_kind=origin_label,
                    formula=formula,
                )
                parameters.append(entry)
                if formula:
                    formulas.append(
                        {
                            "name": pname,
                            "path": full_path,
                            "expression": formula,
                            "declared_value": entry["value"],
                            "unit": unit_str,
                        }
                    )
            return

        if tag_low in {"formula", "relation", "rule", "check"}:
            fname = node_name or tag
            out_param = _attr_ci(node, "output", "target", "parameter") or _child_text_ci(
                node, "output", "target"
            )
            expr = (
                _attr_ci(node, "expression", "body", "formula")
                or _child_text_ci(node, "expression", "body")
                or (node.text or "").strip()
            )
            val_raw = _attr_ci(node, "value", "declared_value") or _child_text_ci(node, "value")
            unit_str = _attr_ci(node, "unit", "units")
            val_str, unit_str = _split_value_and_unit(val_raw, unit_str)
            formulas.append(
                {
                    "name": fname,
                    "output_param": out_param or fname,
                    "expression": expr,
                    "declared_value": _normalize_value(val_str) if val_str else None,
                    "unit": unit_str,
                }
            )
            return

        if tag_low in {"centerofgravity", "cg", "massproperties", "inertia"}:
            x = parse_decimal_str(_attr_ci(node, "x", "cx", "cg_x") or _child_text_ci(node, "x"))
            y = parse_decimal_str(_attr_ci(node, "y", "cy", "cg_y") or _child_text_ci(node, "y"))
            z = parse_decimal_str(_attr_ci(node, "z", "cz", "cg_z") or _child_text_ci(node, "z"))
            unit_cg = _attr_ci(node, "unit", "length_unit") or "m"
            if x is not None and y is not None and z is not None:
                cg_points.append(
                    {
                        "label": node_name or ("\\".join(path_stack) or "CATIA_CG"),
                        "coords": [x, y, z],
                        "unit": unit_cg,
                        "source_kind": origin_label,
                    }
                )
            mass_val = parse_decimal_str(_attr_ci(node, "mass") or _child_text_ci(node, "mass"))
            if mass_val is not None:
                mass_u = _attr_ci(node, "mass_unit") or "kg"
                parameters.append(
                    make_param_entry(
                        path="\\".join([*path_stack, "mass_kg"]) if path_stack else "mass_kg",
                        name="mass_kg",
                        value=mass_val,
                        unit=mass_u,
                        source_kind=origin_label,
                    )
                )

        if tag_low in {"gdt", "tolerance", "ftatolerance", "geometrictolerance"}:
            g_type = _attr_ci(node, "type")
            tol_v = parse_decimal_str(
                _attr_ci(node, "value", "tolerance") or _child_text_ci(node, "value")
            )
            datums_raw = _attr_ci(node, "datums", "datum_refs")
            if g_type or tol_v is not None or datums_raw or _attr_ci(node, "feature", "target"):
                gname = node_name or g_type or "CATIA_GDT"
                tol_u = _attr_ci(node, "unit") or "mm"
                gdt_pmi.append(
                    {
                        "entity_id": _attr_ci(node, "id") or f"CATIA-{len(gdt_pmi) + 1}",
                        "gdt_type": g_type or tag,
                        "name": gname,
                        "description": _attr_ci(node, "description", "feature"),
                        "tolerance_value": tol_v,
                        "unit": tol_u,
                        "datum_refs": [d.strip() for d in datums_raw.split(",") if d.strip()],
                        "modifiers": [],
                        "applied_to": _attr_ci(node, "feature", "target"),
                    }
                )

        next_stack = [*path_stack, node_name] if node_name else path_stack
        for child in node:
            _walk(child, next_stack, tree_children)

    _walk(root, [], product_tree)

    # Synthesize CG point if cg_x / cg_y / cg_z params exist without <CenterOfGravity>.
    if not cg_points:
        by_low = {p["name"].lower(): p for p in parameters}
        cx = by_low.get("cg_x") or by_low.get("cg_x_m") or by_low.get("x_cg")
        cy = by_low.get("cg_y") or by_low.get("cg_y_m") or by_low.get("y_cg")
        cz = by_low.get("cg_z") or by_low.get("cg_z_m") or by_low.get("z_cg")
        if cx is not None:
            cg_points.append(
                {
                    "label": "CATIA_Knowledgeware_CG",
                    "coords": [
                        str(cx["value"]),
                        str(cy["value"]) if cy is not None else "0",
                        str(cz["value"]) if cz is not None else "0",
                    ],
                    "unit": cx.get("unit") or "m",
                    "source_kind": origin_label,
                }
            )

    if not parameters and not formulas and not cg_points and not product_tree:
        raise IngestAbstain("empty_catia_xml")

    block_lines: list[str] = [
        f"CATIA Knowledgeware XML ({origin_label}): "
        f"{len(parameters)} parameters, {len(formulas)} formulas, {len(cg_points)} CG points"
    ]
    for p in parameters:
        val_txt = (
            ";".join(str(x) for x in p["value"])
            if isinstance(p["value"], list)
            else str(p["value"])
        )
        u_txt = f" {p['unit']}" if p["unit"] else ""
        block_lines.append(f"Param {p['path']} = {val_txt}{u_txt}")
    for f in formulas:
        block_lines.append(
            f"Formula {f.get('output_param') or f['name']}: {f.get('expression') or '-'}"
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
                block_kind=origin_label,
            )
        )
        offset += len(line) + 1

    from evidence_ingest.cad_brep import parse_composite_ply_book

    ply_book = parse_composite_ply_book(xml_text)
    return {
        "format": origin_label,
        "product_tree": product_tree,
        "parameters": parameters,
        "formulas": formulas,
        "gdt_pmi": gdt_pmi,
        "cg_points": cg_points,
        "composite_ply_book": ply_book,
        "blocks": blocks,
    }


def _extract_kw_lines_from_stream(stream_bytes: bytes, stream_name: str) -> list[dict[str, Any]]:
    """Extract explicit Knowledgeware key=value lines from UTF-8 or UTF-16LE OLE2 streams."""
    params: list[dict[str, Any]] = []
    candidates: list[str] = []
    try:
        candidates.append(stream_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    if b"\x00" in stream_bytes:
        try:
            candidates.append(stream_bytes.decode("utf-16-le"))
        except UnicodeDecodeError:
            pass
    for text in candidates:
        for line in text.splitlines():
            m = _KW_LINE_RE.match(line)
            if not m:
                continue
            path, raw_val, unit = m.group(1), m.group(2), m.group(3) or ""
            # Require either path separator or valid numeric/boolean to avoid binary noise
            val = _normalize_value(raw_val)
            if isinstance(val, str) and "\\" not in path and "/" not in path:
                continue
            name = path.replace("/", "\\").split("\\")[-1]
            params.append(
                make_param_entry(
                    path=path,
                    name=name,
                    value=val,
                    unit=unit,
                    source_kind=f"catia_ole2:{stream_name}",
                )
            )
    return params


def parse_catia_xml(raw: bytes, source_hash: str) -> dict[str, Any]:
    """Parse CATIA Knowledgeware / Product / Part XML."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestAbstain("invalid_utf8") from exc
    return _parse_catia_xml_text(text, source_hash, origin_label="catia_xml")


def parse_catia_native(raw: bytes, source_hash: str, filename: str) -> dict[str, Any]:
    """Parse native .CATPart / .CATProduct (XML-wrapped or OLE2 compound stream container)."""
    stripped = raw.lstrip()
    if stripped.startswith(b"<"):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        parsed = _parse_catia_xml_text(text, source_hash, origin_label="catia_native_xml")
        parsed["container"] = "xml"
        parsed["filename"] = filename
        return parsed

    bio = io.BytesIO(raw)
    if not olefile.isOleFile(bio):
        raise IngestAbstain("invalid_catia_container")

    bio.seek(0)
    ole = olefile.OleFileIO(bio)
    try:
        streams = ["/".join(entry) for entry in ole.listdir(streams=True, storages=False)]
        all_params: list[dict[str, Any]] = []
        all_formulas: list[dict[str, Any]] = []
        all_cg: list[dict[str, Any]] = []
        all_gdt: list[dict[str, Any]] = []
        product_tree: list[dict[str, Any]] = []

        for stream_path in streams:
            data = ole.openstream(stream_path.split("/")).read()
            # 1. Embedded XML stream inside OLE2 CATPart / CATProduct
            xml_pos = data.find(b"<?xml")
            if xml_pos == -1:
                xml_pos = data.find(b"<CAT")
            if xml_pos != -1:
                try:
                    sub = _parse_catia_xml_text(
                        data[xml_pos:].decode("utf-8", errors="ignore"),
                        source_hash,
                        origin_label="catia_native_ole2_xml",
                    )
                    all_params.extend(sub["parameters"])
                    all_formulas.extend(sub["formulas"])
                    all_cg.extend(sub["cg_points"])
                    all_gdt.extend(sub["gdt_pmi"])
                    product_tree.extend(sub["product_tree"])
                    continue
                except IngestAbstain:
                    pass
            # 2. Structured Knowledgeware parameter stream
            if any(
                key in stream_path.lower()
                for key in ("knowledge", "param", "design", "catia", "inertia", "prop")
            ):
                all_params.extend(_extract_kw_lines_from_stream(data, stream_path))
    finally:
        ole.close()

    if not all_params and not all_formulas and not all_cg and not product_tree:
        # Fail closed cleanly on proprietary opaque CATIA binary with no Knowledgeware stream
        raise IngestAbstain("opaque_catia_binary_no_parameter_stream")

    if not all_cg:
        by_low = {p["name"].lower(): p for p in all_params}
        cx = by_low.get("cg_x") or by_low.get("cg_x_m")
        cy = by_low.get("cg_y") or by_low.get("cg_y_m")
        cz = by_low.get("cg_z") or by_low.get("cg_z_m")
        if cx is not None:
            all_cg.append(
                {
                    "label": f"{filename}_CG",
                    "coords": [
                        str(cx["value"]),
                        str(cy["value"]) if cy is not None else "0",
                        str(cz["value"]) if cz is not None else "0",
                    ],
                    "unit": cx.get("unit") or "m",
                    "source_kind": "catia_native_ole2",
                }
            )

    block_lines = [
        f"CATIA Native OLE2 ({filename}): streams={len(streams)}, "
        f"parameters={len(all_params)}, formulas={len(all_formulas)}"
    ]
    for p in all_params:
        block_lines.append(f"CATIA Param {p['path']} = {p['value']} {p['unit']}".strip())

    blocks: list[Block] = []
    offset = 0
    for line in block_lines:
        blocks.append(
            Block(
                text=line,
                span_start=offset,
                span_end=offset + len(line),
                source_hash=source_hash,
                block_kind="catia_native",
            )
        )
        offset += len(line) + 1

    return {
        "format": "catia_native",
        "container": "ole2",
        "ole2_streams": streams,
        "product_tree": product_tree,
        "parameters": all_params,
        "formulas": all_formulas,
        "gdt_pmi": all_gdt,
        "cg_points": all_cg,
        "blocks": blocks,
    }
