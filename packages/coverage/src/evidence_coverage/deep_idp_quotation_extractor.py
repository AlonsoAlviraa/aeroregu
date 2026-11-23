"""Deep Physical IDP Extractor coupling Nastran BDF/OP2/H5, STEP B-Rep & PDF/XLSX/DOCX BOMs.

Bridges `evidence_ingest.fem_parsers`, `evidence_ingest.cae_binary`, `evidence_ingest.cad_brep`,
and `evidence_ingest.bom_drawing_extractor` into deterministic quotation engineering sizing.
"""

from __future__ import annotations

import base64
import hashlib
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from evidence_calc.quantize import format_quantum
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.bom_drawing_extractor import extract_bom_and_drawings
from evidence_ingest.cad_brep import analyze_step_brep
from evidence_ingest.cae_binary import (
    parse_cae_h5_bytes,
    parse_cae_h5_file,
    parse_nastran_op2_bytes,
    parse_nastran_op2_file,
)
from evidence_ingest.fem_parsers import (
    parse_abaqus_inp,
    parse_nastran_bdf,
    parse_nastran_f06,
)

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")
_ONE = Decimal("1")


def _read_bytes_attachment(
    att: dict[str, Any],
    *,
    path_key: str,
    bytes_key: str,
    b64_key: str,
    default_name: str,
) -> tuple[bytes, str | None, Path | None]:
    raw_b = att.get(bytes_key)
    if isinstance(raw_b, (bytes, bytearray)) and len(raw_b) > 0:
        return bytes(raw_b), f"inline:{bytes_key}", None
    raw_b64 = att.get(b64_key)
    if isinstance(raw_b64, str) and raw_b64.strip():
        try:
            decoded = base64.b64decode(raw_b64.strip())
            if decoded:
                return decoded, f"inline:{b64_key}", None
        except Exception:
            pass
    raw_p = att.get(path_key)
    if raw_p:
        p = Path(str(raw_p))
        if p.is_file():
            return p.read_bytes(), p.name, p
    return b"", None, None


def _read_text_attachment(
    att: dict[str, Any],
    *,
    text_key: str,
    path_key: str,
    base_dir_key: str = "bdf_base_dir",
) -> tuple[str, str | None, Path | None]:
    raw_txt = att.get(text_key)
    if isinstance(raw_txt, str) and raw_txt.strip():
        base_dir = Path(str(att[base_dir_key])) if att.get(base_dir_key) else None
        return raw_txt, f"inline:{text_key}", base_dir
    raw_p = att.get(path_key)
    if raw_p:
        p = Path(str(raw_p))
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore"), p.name, p
    return "", None, None


def extract_deep_idp_engineering_package(
    attachments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect multi-include BDF, binary OP2/H5, STEP B-Rep solids, and PDF/XLSX/DOCX BOMs."""
    att = attachments or {}
    artifacts_analyzed: list[str] = []
    artifact_hashes: dict[str, str] = {}
    quality_findings: list[str] = []

    # 1. Nastran .bdf with nested INCLUDE tree, DOFs, local coords, and properties
    bdf_txt, bdf_name, bdf_path = _read_text_attachment(
        att, text_key="bdf_text", path_key="bdf_path"
    )
    bdf_parsed: dict[str, Any] | None = None
    include_tree: list[dict[str, Any]] = []
    coord_systems: list[dict[str, str]] = []
    local_cp_grid_count = 0
    dof_summary: dict[str, int] = {
        "node_count": 0,
        "raw_dofs": 0,
        "spc_constrained_dofs": 0,
        "mpc_rbe_dependent_dofs": 0,
        "active_dofs": 0,
        "rbe2_count": 0,
        "rbe3_count": 0,
        "mpc_count": 0,
    }
    prop_counts: dict[str, int] = {
        "pshell": 0,
        "pcomp": 0,
        "pbush": 0,
        "pbar": 0,
        "pbeam": 0,
        "psolid": 0,
    }
    bdf_nodes = 0
    bdf_elems = 0
    bdf_struct_elems = 0
    bdf_cbush = 0
    bdf_pcomp = 0
    bdf_subcases = 0

    if bdf_txt and bdf_name:
        artifacts_analyzed.append(bdf_name)
        bdf_bytes = bdf_txt.encode("utf-8")
        bdf_hash = hashlib.sha256(bdf_bytes).hexdigest()
        artifact_hashes[bdf_name] = bdf_hash
        base_dir = (
            bdf_path.parent
            if isinstance(bdf_path, Path) and bdf_path.is_file()
            else (bdf_path if isinstance(bdf_path, Path) and bdf_path.is_dir() else None)
        )
        try:
            bdf_parsed = parse_nastran_bdf(bdf_bytes, bdf_hash, base_dir=base_dir)
            include_tree = list(bdf_parsed.get("include_tree") or [])
            for inc in include_tree:
                inc_label = str(inc["relative_path"])
                artifacts_analyzed.append(inc_label)
                artifact_hashes[inc_label] = str(inc["sha256"])
            coord_systems = list(bdf_parsed.get("coordinate_systems") or [])
            local_cp_grid_count = int(bdf_parsed.get("local_cp_grid_count") or 0)
            dof_summary = dict(bdf_parsed.get("dof_summary") or dof_summary)
            props = bdf_parsed.get("properties") or {}
            for pkey in prop_counts:
                prop_counts[pkey] = len(props.get(pkey) or [])
            mesh_info = bdf_parsed.get("mesh") or {}
            bdf_nodes = int(mesh_info.get("node_count") or 0)
            bdf_elems = int(mesh_info.get("element_count") or 0)
            bdf_struct_elems = int(mesh_info.get("structural_element_count") or bdf_elems)
            cbush_elems = int(mesh_info.get("cbush_element_count") or 0)
            bdf_pcomp = prop_counts["pcomp"]
            bdf_subcases = max(
                len(bdf_parsed.get("subcases") or []),
                len((bdf_parsed.get("loads") or {}).get("load_cases") or []),
            )
            bdf_cbush = (
                cbush_elems
                + prop_counts["pbush"]
                + dof_summary.get("rbe2_count", 0)
                + dof_summary.get("rbe3_count", 0)
            )
        except IngestAbstain as exc:
            quality_findings.append(f"BDF parser notice: {exc.reason}")

    # 2. Binary .op2 and .h5 streaming extraction
    op2_bytes, op2_name, op2_path = _read_bytes_attachment(
        att,
        path_key="op2_path",
        bytes_key="op2_bytes",
        b64_key="op2_base64",
        default_name="run.op2",
    )
    h5_bytes, h5_name, h5_path = _read_bytes_attachment(
        att, path_key="h5_path", bytes_key="h5_bytes", b64_key="h5_base64", default_name="run.h5"
    )
    cae_binary_reports: list[dict[str, Any]] = []
    cae_stress_rows = 0
    cae_subcases = 0
    cae_imbalanced: list[int] = []
    cae_ms_mins: list[Decimal] = []

    if op2_bytes and op2_name:
        op2_hash = hashlib.sha256(op2_bytes).hexdigest()
        artifacts_analyzed.append(op2_name)
        artifact_hashes[op2_name] = op2_hash
        try:
            op2_res = (
                parse_nastran_op2_file(op2_path, source_hash=op2_hash)
                if op2_path is not None
                else parse_nastran_op2_bytes(op2_bytes, source_hash=op2_hash)
            )
            cae_binary_reports.append(
                {
                    "artifact": op2_name,
                    "format": "nastran_op2",
                    "node_count": op2_res["node_count"],
                    "element_count": op2_res["element_count"],
                    "subcase_count": op2_res["subcase_count"],
                    "stress_row_count": op2_res["stress_row_count"],
                    "equilibrium_verified": op2_res["equilibrium_verified"],
                    "imbalanced_subcases": op2_res["imbalanced_subcases"],
                    "ms_min": op2_res["ms_min"],
                    "critical_pid": op2_res["critical_pid"],
                }
            )
            cae_stress_rows += int(op2_res["stress_row_count"])
            cae_subcases = max(cae_subcases, int(op2_res["subcase_count"]))
            cae_imbalanced.extend(int(s) for s in op2_res.get("imbalanced_subcases") or [])
            if op2_res.get("ms_min") is not None:
                cae_ms_mins.append(Decimal(str(op2_res["ms_min"])))
            bdf_nodes = max(bdf_nodes, int(op2_res["node_count"]))
            bdf_elems = max(bdf_elems, int(op2_res["element_count"]))
            bdf_struct_elems = max(bdf_struct_elems, int(op2_res["element_count"]))
            if not op2_res["equilibrium_verified"]:
                imbal = op2_res["imbalanced_subcases"]
                quality_findings.append(f"Binary .op2 equilibrium imbalance in subcases {imbal}.")
        except IngestAbstain as exc:
            quality_findings.append(f"Binary .op2 notice: {exc.reason}")

    if h5_bytes and h5_name:
        h5_hash = hashlib.sha256(h5_bytes).hexdigest()
        artifacts_analyzed.append(h5_name)
        artifact_hashes[h5_name] = h5_hash
        try:
            h5_res = (
                parse_cae_h5_file(h5_path, source_hash=h5_hash)
                if h5_path is not None
                else parse_cae_h5_bytes(h5_bytes, source_hash=h5_hash)
            )
            cae_binary_reports.append(
                {
                    "artifact": h5_name,
                    "format": "cae_h5",
                    "node_count": h5_res["node_count"],
                    "element_count": h5_res["element_count"],
                    "subcase_count": h5_res["subcase_count"],
                    "stress_row_count": h5_res["stress_row_count"],
                    "equilibrium_verified": h5_res["equilibrium_verified"],
                    "imbalanced_subcases": h5_res["imbalanced_subcases"],
                    "ms_min": h5_res["ms_min"],
                    "critical_pid": h5_res["critical_pid"],
                }
            )
            cae_stress_rows += int(h5_res["stress_row_count"])
            cae_subcases = max(cae_subcases, int(h5_res["subcase_count"]))
            cae_imbalanced.extend(int(s) for s in h5_res.get("imbalanced_subcases") or [])
            if h5_res.get("ms_min") is not None:
                cae_ms_mins.append(Decimal(str(h5_res["ms_min"])))
            bdf_nodes = max(bdf_nodes, int(h5_res["node_count"]))
            bdf_elems = max(bdf_elems, int(h5_res["element_count"]))
            bdf_struct_elems = max(bdf_struct_elems, int(h5_res["element_count"]))
            if not h5_res["equilibrium_verified"]:
                quality_findings.append(
                    f"Binary .h5 equilibrium imbalance in subcases {h5_res['imbalanced_subcases']}."
                )
        except IngestAbstain as exc:
            quality_findings.append(f"Binary .h5 notice: {exc.reason}")

    # 2b. Optional Abaqus .inp with nested *INCLUDE tree & *SHELL SECTION, COMPOSITE
    abq_txt, abq_name, abq_path = _read_text_attachment(
        att,
        text_key="abaqus_text",
        path_key="abaqus_path",
        base_dir_key="abaqus_base_dir",
    )
    abaqus_summary: dict[str, Any] = {
        "present": False,
        "node_count": 0,
        "element_count": 0,
        "include_count": 0,
        "include_tree": [],
        "composite_sections": [],
        "total_composite_plies": 0,
        "load_cases_count": 0,
    }
    if abq_txt and abq_name:
        artifacts_analyzed.append(abq_name)
        abq_bytes = abq_txt.encode("utf-8")
        abq_hash = hashlib.sha256(abq_bytes).hexdigest()
        artifact_hashes[abq_name] = abq_hash
        abq_base_dir = (
            abq_path.parent
            if isinstance(abq_path, Path) and abq_path.is_file()
            else (abq_path if isinstance(abq_path, Path) and abq_path.is_dir() else None)
        )
        try:
            abq_parsed = parse_abaqus_inp(abq_bytes, abq_hash, base_dir=abq_base_dir)
            abq_inc = list(abq_parsed.get("include_tree") or [])
            for inc in abq_inc:
                inc_label = str(inc["relative_path"])
                artifacts_analyzed.append(inc_label)
                artifact_hashes[inc_label] = str(inc["sha256"])
            abq_mesh = abq_parsed.get("mesh") or {}
            abq_comp = list(abq_parsed.get("composite_sections") or [])
            abq_plies = sum(int(s.get("ply_count") or 0) for s in abq_comp)
            abq_lcs = len((abq_parsed.get("loads") or {}).get("load_cases") or [])
            abaqus_summary = {
                "present": True,
                "node_count": int(abq_mesh.get("node_count") or 0),
                "element_count": int(abq_mesh.get("element_count") or 0),
                "include_count": len(abq_inc),
                "include_tree": abq_inc,
                "composite_sections": abq_comp,
                "total_composite_plies": abq_plies,
                "load_cases_count": abq_lcs,
            }
            bdf_nodes = max(bdf_nodes, abaqus_summary["node_count"])
            bdf_elems = max(bdf_elems, abaqus_summary["element_count"])
            bdf_struct_elems = max(bdf_struct_elems, abaqus_summary["element_count"])
            bdf_pcomp = max(bdf_pcomp, len(abq_comp))
            bdf_subcases = max(bdf_subcases, abq_lcs)
        except IngestAbstain as exc:
            quality_findings.append(f"Abaqus .inp parser notice: {exc.reason}")

    # 3. Nastran .f06 solver audit (OLOAD/SPCFORCE/GPWG/EPSILON/SOL103/SOL105/GPFORCE)
    f06_txt, f06_name, _ = _read_text_attachment(att, text_key="f06_text", path_key="f06_path")
    f06_parsed: dict[str, Any] | None = None
    if f06_txt and f06_name:
        artifacts_analyzed.append(f06_name)
        f06_bytes = f06_txt.encode("utf-8")
        f06_hash = hashlib.sha256(f06_bytes).hexdigest()
        artifact_hashes[f06_name] = f06_hash
        try:
            f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
        except IngestAbstain:
            f06_parsed = None
    f06_upper = f06_txt.upper()
    has_gpwg = ("WEIGHT GENERATOR" in f06_upper) or (
        "G R I D   P O I N T   W E I G H T" in f06_upper
    )
    has_oload_spc = ("OLOAD" in f06_upper) and ("SPCFORCE" in f06_upper)
    has_fatal = ("FATAL MESSAGE" in f06_upper) or ("USER FATAL MESSAGE" in f06_upper)
    eps_matches = re.findall(
        r"EPSILON\s*(?:=|\s)\s*([+-]?\d+(?:\.\d+)?(?:[EeDd][+-]?\d+)?)",
        f06_upper,
    )
    eps_max_dec: Decimal | None = None
    for m in eps_matches:
        try:
            d = Decimal(m.replace("D", "E")).copy_abs()
        except InvalidOperation:
            continue
        if eps_max_dec is None or d > eps_max_dec:
            eps_max_dec = d
    eps_exceeded = eps_max_dec is not None and eps_max_dec > Decimal("1e-6")
    buckling_modes = list((f06_parsed or {}).get("buckling_eigenvalues") or [])
    modal_modes = list((f06_parsed or {}).get("modal_eigenvalues") or [])
    crit_buckling = (f06_parsed or {}).get("critical_buckling_factor")
    buckling_ms_min = (f06_parsed or {}).get("buckling_ms_min")
    gpforce_freebody = (f06_parsed or {}).get("gpforce_freebody")
    buckling_unstable = False
    if crit_buckling is not None and Decimal(str(crit_buckling)) < _ONE:
        buckling_unstable = True
        quality_findings.append(f"Nastran SOL 105 critical buckling factor {crit_buckling} < 1.0.")
    if gpforce_freebody is not None and not gpforce_freebody.get("freebody_balanced", True):
        quality_findings.append(
            "Nastran GPFORCE freebody nodal residual exceeds equilibrium tolerance."
        )
    if has_fatal:
        quality_findings.append("Nastran .f06 contains FATAL MESSAGE.")
    if eps_exceeded:
        quality_findings.append(
            f"Nastran .f06 EPSILON={eps_max_dec} exceeds 1e-6 equilibrium threshold."
        )
    if f06_txt and not (has_gpwg and has_oload_spc) and not (buckling_modes or gpforce_freebody):
        quality_findings.append("Nastran .f06 missing GPWG or OLOAD/SPCFORCE balance tables.")

    # 4. STEP AP203/214/242 B-Rep Buy-to-Fly, Surface Area & Machining Complexity
    step_txt, step_name, _ = _read_text_attachment(att, text_key="step_text", path_key="step_path")
    step_brep: dict[str, Any] = {}
    step_solids = 0
    step_faces = 0
    if step_txt and step_name:
        step_bytes = step_txt.encode("utf-8")
        step_hash = hashlib.sha256(step_bytes).hexdigest()
        artifacts_analyzed.append(step_name)
        artifact_hashes[step_name] = step_hash
        step_solids = len(
            re.findall(r"MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS|CLOSED_SHELL", step_txt, re.IGNORECASE)
        )
        step_faces = len(re.findall(r"ADVANCED_FACE", step_txt, re.IGNORECASE))
        try:
            step_brep = analyze_step_brep(step_bytes, step_hash)
            step_solids = max(step_solids, int(step_brep.get("solid_count") or 0))
        except Exception as exc:
            quality_findings.append(f"STEP B-Rep analysis fallback: {exc}")

    # 5. DXF entity scan
    dxf_txt, dxf_name, _ = _read_text_attachment(att, text_key="dxf_text", path_key="dxf_path")
    if dxf_txt and dxf_name:
        artifacts_analyzed.append(dxf_name)
        artifact_hashes[dxf_name] = hashlib.sha256(dxf_txt.encode("utf-8")).hexdigest()
    dxf_entities = len(
        re.findall(r"(?m)^\s*(?:DIMENSION|INSERT|LWPOLYLINE|CIRCLE|LINE)\s*$", dxf_txt)
    )

    # 6. BOM & Drawing-List extraction from PDF / XLSX / DOCX attachments
    bom_items: list[dict[str, Any]] = []
    drawing_list: list[dict[str, Any]] = []
    verified_bbox_citations: list[dict[str, Any]] = []
    bom_docs_processed: list[dict[str, Any]] = []

    doc_specs: list[tuple[bytes | Path, str]] = []
    for key_prefix, default_ext in (
        ("bom_pdf", "bom.pdf"),
        ("bom_xlsx", "bom.xlsx"),
        ("bom_docx", "bom.docx"),
    ):
        b_data, b_name, b_path = _read_bytes_attachment(
            att,
            path_key=f"{key_prefix}_path",
            bytes_key=f"{key_prefix}_bytes",
            b64_key=f"{key_prefix}_base64",
            default_name=default_ext,
        )
        if b_path is not None:
            doc_specs.append((b_path, b_path.name))
        elif b_data:
            doc_specs.append((b_data, str(att.get(f"{key_prefix}_filename") or default_ext)))

    for extra in att.get("rfq_documents") or []:
        if not isinstance(extra, dict):
            continue
        fname = str(extra.get("filename") or "rfq_doc.pdf")
        if extra.get("path") and Path(str(extra["path"])).is_file():
            doc_specs.append((Path(str(extra["path"])), fname))
        elif isinstance(extra.get("bytes"), (bytes, bytearray)):
            doc_specs.append((bytes(extra["bytes"]), fname))
        elif isinstance(extra.get("base64"), str) and extra["base64"].strip():
            doc_specs.append((base64.b64decode(extra["base64"].strip()), fname))

    for src, fname in doc_specs:
        try:
            ext_res = extract_bom_and_drawings(src, filename=fname)
            artifacts_analyzed.append(fname)
            artifact_hashes[fname] = str(ext_res["source_hash"])
            bom_items.extend(ext_res["bom_items"])
            drawing_list.extend(ext_res["drawing_list"])
            verified_bbox_citations.extend(ext_res["verified_bbox_citations"])
            bom_docs_processed.append(
                {
                    "filename": fname,
                    "format": ext_res["format"],
                    "source_hash": ext_res["source_hash"],
                    "bom_parts_count": ext_res["bom_parts_count"],
                    "drawings_count": ext_res["drawings_count"],
                    "bom_total_mass_kg": ext_res["bom_total_mass_kg"],
                }
            )
        except Exception as exc:
            quality_findings.append(f"BOM/Drawing extraction notice ({fname}): {exc}")

    # 7. Synthesize solve/postproc hours & CAD manufacturing sizing deterministically
    effective_subcases = max(bdf_subcases, cae_subcases)
    active_dofs = int(dof_summary.get("active_dofs") or (6 * bdf_nodes))
    min_ms = min(cae_ms_mins) if cae_ms_mins else None

    with localcontext() as ctx:
        ctx.prec = 30
        solve_hrs = (
            (Decimal(active_dofs) / Decimal("5000")) * Decimal("1.500")
            + Decimal(effective_subcases) * Decimal("0.450")
            + (Decimal(cae_stress_rows) / Decimal("50000")) * Decimal("2.000")
            + Decimal(prop_counts["pcomp"] + len(abaqus_summary["composite_sections"]))
            * Decimal("0.600")
            + Decimal(dof_summary.get("rbe2_count", 0) + dof_summary.get("rbe3_count", 0))
            * Decimal("0.150")
        )
        if cae_imbalanced:
            solve_hrs += Decimal("8.000") + Decimal("4.000") * Decimal(len(cae_imbalanced))
        if min_ms is not None and min_ms < _ZERO:
            solve_hrs += Decimal("16.000")
        if buckling_unstable:
            solve_hrs += Decimal("14.000")
        if has_fatal or eps_exceeded:
            solve_hrs += Decimal("12.000")

        cad_btf = (
            Decimal(str(step_brep["assembly_buy_to_fly_ratio"]))
            if step_brep.get("assembly_buy_to_fly_ratio")
            else Decimal("1.000")
        )
        cfrp_area_m2 = (
            Decimal(str(step_brep["assembly_surface_area_m2"]))
            if step_brep.get("assembly_surface_area_m2")
            else Decimal("0.000000")
        )
        mach_complex = (
            Decimal(str(step_brep["machining_complexity_index"]))
            if step_brep.get("machining_complexity_index")
            else Decimal("1.000")
        )

    bom_total_qty = sum(int(item.get("quantity") or 0) for item in bom_items)
    bom_total_mass = sum(
        (Decimal(str(item.get("total_mass_kg") or "0")) for item in bom_items), _ZERO
    )

    return {
        "artifacts_analyzed": artifacts_analyzed,
        "artifact_hashes": artifact_hashes,
        "quality_findings": quality_findings,
        "bdf_summary": {
            "node_count": bdf_nodes,
            "element_count": bdf_elems,
            "structural_element_count": bdf_struct_elems,
            "cbush_joints_count": bdf_cbush,
            "pcomp_laminates_count": bdf_pcomp,
            "subcases_count": effective_subcases,
            "include_tree": include_tree,
            "include_count": len(include_tree),
            "coordinate_systems_count": len(coord_systems),
            "coordinate_systems": coord_systems,
            "local_cp_grid_count": local_cp_grid_count,
            "dof_summary": dof_summary,
            "property_counts": prop_counts,
        },
        "f06_audit": {
            "present": bool(f06_txt),
            "has_gpwg": has_gpwg,
            "has_oload_spc": has_oload_spc,
            "has_fatal": has_fatal,
            "epsilon_max": str(eps_max_dec) if eps_max_dec is not None else None,
            "epsilon_exceeded": eps_exceeded,
            "modal_modes_count": len(modal_modes),
            "buckling_modes_count": len(buckling_modes),
            "critical_buckling_factor": crit_buckling,
            "buckling_ms_min": buckling_ms_min,
            "gpforce_freebody": gpforce_freebody,
        },
        "abaqus_summary": abaqus_summary,
        "cae_binary_summary": {
            "files_parsed": len(cae_binary_reports),
            "reports": cae_binary_reports,
            "total_stress_rows": cae_stress_rows,
            "imbalanced_subcases": sorted(set(cae_imbalanced)),
            "global_ms_min": format_quantum(min_ms, _Q3) if min_ms is not None else None,
        },
        "cad_brep_sizing": {
            "solid_count": step_solids,
            "face_count": step_faces,
            "dxf_entities_count": dxf_entities,
            "assembly_volume_mm3": step_brep.get("assembly_volume_mm3"),
            "assembly_stock_volume_mm3": step_brep.get("assembly_stock_volume_mm3"),
            "buy_to_fly_ratio": format_quantum(cad_btf, _Q3),
            "cfrp_surface_area_m2": str(cfrp_area_m2),
            "min_web_thickness_mm": step_brep.get("min_web_thickness_mm"),
            "machining_complexity_index": format_quantum(mach_complex, _Q3),
            "composite_ply_book": step_brep.get("composite_ply_book"),
        },
        "bom_and_drawings": {
            "documents": bom_docs_processed,
            "bom_parts_count": len(bom_items),
            "bom_total_quantity": bom_total_qty,
            "bom_total_mass_kg": format_quantum(bom_total_mass, _Q3),
            "drawings_count": len(drawing_list),
            "bom_items": bom_items,
            "drawing_list": drawing_list,
            "verified_bbox_citations": verified_bbox_citations,
        },
        "estimated_solve_postproc_hours": format_quantum(solve_hrs, _Q2),
    }
