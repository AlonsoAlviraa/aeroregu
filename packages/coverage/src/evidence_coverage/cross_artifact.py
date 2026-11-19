"""Cross-Artifact Consistency Auditor across Requirements, CAD, FEM & Reports."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from evidence_calc.units import conversion_interval
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.orchestrator import record
from evidence_kernel.telemetry import get_telemetry
from evidence_kernel.webhooks import dispatch_webhook_with_retry

from evidence_coverage.grid import Cell, generate_cells
from evidence_coverage.status import list_cells_with_status

_MASS_RE = re.compile(
    r"(?:mass|masa|weight|peso|m_total)\s*(?:=|:|is|of)?\s*([-+]?\d+(?:\.\d+)?)\s*(kg|lb|lbm|g)\b",
    re.IGNORECASE,
)
_CG_X_RE = re.compile(
    r"(?:cg_x|x_cg|cg\s*x|center of gravity x|centro de gravedad x)\s*"
    r"(?:=|:|is)?\s*([-+]?\d+(?:\.\d+)?)\s*(m|mm|cm|in)\b",
    re.IGNORECASE,
)
_LOAD_RE = re.compile(
    r"(?:resultant|total\s+force|thrust|applied\s+load|empuje|carga)\s*(?:=|:|is)?\s*([-+]?\d+(?:\.\d+)?)\s*(kn|n|lbf)\b",
    re.IGNORECASE,
)


def _norm_dec(value: Any, raw_unit: str | None, target_unit: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        return None
    if not raw_unit or raw_unit.lower() == target_unit.lower():
        return dec
    unit_map = {
        "n": "newton",
        "kn": "kilonewton",
        "lbf": "pound_force",
        "kg": "kilogram",
        "lb": "pound",
        "lbm": "pound",
        "g": "gram",
        "m": "meter",
        "mm": "millimeter",
        "cm": "centimeter",
        "in": "inch",
    }
    src = unit_map.get(raw_unit.strip().lower(), raw_unit.strip().lower())
    dst = unit_map.get(target_unit.strip().lower(), target_unit.strip().lower())
    factor = conversion_interval(src, dst)
    if isinstance(factor, Decimal):
        return (dec * factor).quantize(Decimal("0.0001"))
    return None


def _extract_param_from_cad_cae(
    artifact: dict[str, Any] | None, *, names: tuple[str, ...], target_unit: str
) -> dict[str, Any] | None:
    if not isinstance(artifact, dict):
        return None
    cad_cae = artifact.get("cad_cae") if isinstance(artifact.get("cad_cae"), dict) else artifact
    params = cad_cae.get("parameters") if isinstance(cad_cae, dict) else None
    if isinstance(params, list):
        for p in params:
            pname = str(p.get("name") or "").lower()
            ppath = str(p.get("path") or "").lower()
            if any(pname == n or pname.endswith(n) or n in ppath for n in names):
                val = _norm_dec(p.get("value"), str(p.get("unit") or target_unit), target_unit)
                if val is not None:
                    return {
                        "value": val,
                        "raw_value": str(p.get("value")),
                        "raw_unit": str(p.get("unit") or target_unit),
                        "path": str(p.get("path") or pname),
                        "source_kind": str(
                            p.get("source_kind") or cad_cae.get("format") or "cad_cae"
                        ),
                    }
    # Fallback direct fields (e.g. nastran_f06 GPWG or CG points)
    if "mass_kg" in names and isinstance(cad_cae, dict):
        if cad_cae.get("gpwg_mass_kg") not in (None, ""):
            val = _norm_dec(cad_cae["gpwg_mass_kg"], "kg", "kg")
            if val is not None:
                return {
                    "value": val,
                    "raw_value": str(cad_cae["gpwg_mass_kg"]),
                    "raw_unit": "kg",
                    "path": "GPWG\\mass_kg",
                    "source_kind": "nastran_f06",
                }
        if cad_cae.get("mass_kg") not in (None, ""):
            val = _norm_dec(cad_cae["mass_kg"], "kg", "kg")
            if val is not None:
                return {
                    "value": val,
                    "raw_value": str(cad_cae["mass_kg"]),
                    "raw_unit": "kg",
                    "path": "direct\\mass_kg",
                    "source_kind": str(cad_cae.get("format") or "direct"),
                }
    if "cg_x_m" in names and isinstance(cad_cae, dict):
        cg_pts = cad_cae.get("cg_points") or []
        if isinstance(cg_pts, list) and cg_pts:
            coords = cg_pts[0].get("coords") or []
            if len(coords) >= 1:
                unit = str(cg_pts[0].get("unit") or "m")
                val = _norm_dec(coords[0], unit, "m")
                if val is not None:
                    return {
                        "value": val,
                        "raw_value": str(coords[0]),
                        "raw_unit": unit,
                        "path": str(cg_pts[0].get("label") or "CG[0]"),
                        "source_kind": str(
                            cg_pts[0].get("source_kind") or cad_cae.get("format") or "cg"
                        ),
                    }
        if cad_cae.get("cg_x_m") not in (None, ""):
            val = _norm_dec(cad_cae["cg_x_m"], "m", "m")
            if val is not None:
                return {
                    "value": val,
                    "raw_value": str(cad_cae["cg_x_m"]),
                    "raw_unit": "m",
                    "path": "direct\\cg_x_m",
                    "source_kind": str(cad_cae.get("format") or "direct"),
                }
    return None


def _extract_from_report(report_artifact: dict[str, Any] | None) -> dict[str, Any]:
    """Extract grounded numerical declarations (with page_no + bbox) from PDF/DOCX blocks."""
    out: dict[str, Any] = {}
    if not isinstance(report_artifact, dict):
        return out
    blocks = report_artifact.get("blocks")
    text_blob = ""
    evidence_by_key: dict[str, dict[str, Any]] = {}
    if isinstance(blocks, list):
        for blk in blocks:
            rows = blk.get("table_rows")
            if isinstance(rows, list):
                for row in rows:
                    row_txt = " ".join(str(c) for c in row)
                    if "mass" not in out:
                        m = _MASS_RE.search(row_txt)
                        if m:
                            val = _norm_dec(m.group(1), m.group(2), "kg")
                            if val is not None:
                                out["mass"] = val
                                evidence_by_key["mass"] = {
                                    "raw_value": m.group(1),
                                    "raw_unit": m.group(2),
                                    "quotation": row_txt[:200],
                                    "page_no": blk.get("page_no"),
                                    "bbox": blk.get("bbox"),
                                }
                    if "cg_x" not in out:
                        mc = _CG_X_RE.search(row_txt)
                        if mc:
                            val = _norm_dec(mc.group(1), mc.group(2), "m")
                            if val is not None:
                                out["cg_x"] = val
                                evidence_by_key["cg_x"] = {
                                    "raw_value": mc.group(1),
                                    "raw_unit": mc.group(2),
                                    "quotation": row_txt[:200],
                                    "page_no": blk.get("page_no"),
                                    "bbox": blk.get("bbox"),
                                }
                    if "force" not in out:
                        mf = _LOAD_RE.search(row_txt)
                        if mf:
                            val = _norm_dec(mf.group(1), mf.group(2), "N")
                            if val is not None:
                                out["force"] = val
                                evidence_by_key["force"] = {
                                    "raw_value": mf.group(1),
                                    "raw_unit": mf.group(2),
                                    "quotation": row_txt[:200],
                                    "page_no": blk.get("page_no"),
                                    "bbox": blk.get("bbox"),
                                }

            txt = str(blk.get("text") or "")
            if "mass" not in out:
                m = _MASS_RE.search(txt)
                if m:
                    val = _norm_dec(m.group(1), m.group(2), "kg")
                    if val is not None:
                        out["mass"] = val
                        evidence_by_key["mass"] = {
                            "raw_value": m.group(1),
                            "raw_unit": m.group(2),
                            "quotation": txt[:200],
                            "page_no": blk.get("page_no"),
                            "bbox": blk.get("bbox"),
                        }
            if "cg_x" not in out:
                mc = _CG_X_RE.search(txt)
                if mc:
                    val = _norm_dec(mc.group(1), mc.group(2), "m")
                    if val is not None:
                        out["cg_x"] = val
                        evidence_by_key["cg_x"] = {
                            "raw_value": mc.group(1),
                            "raw_unit": mc.group(2),
                            "quotation": txt[:200],
                            "page_no": blk.get("page_no"),
                            "bbox": blk.get("bbox"),
                        }
            if "force" not in out:
                mf = _LOAD_RE.search(txt)
                if mf:
                    val = _norm_dec(mf.group(1), mf.group(2), "N")
                    if val is not None:
                        out["force"] = val
                        evidence_by_key["force"] = {
                            "raw_value": mf.group(1),
                            "raw_unit": mf.group(2),
                            "quotation": txt[:200],
                            "page_no": blk.get("page_no"),
                            "bbox": blk.get("bbox"),
                        }
            text_blob += "\n" + txt
    # Support direct summary keys in report dict as well
    for key_alias, norm_key, target_u in (
        ("mass_kg", "mass", "kg"),
        ("cg_x_m", "cg_x", "m"),
        ("resultant_force_n", "force", "N"),
    ):
        if norm_key not in out and report_artifact.get(key_alias) not in (None, ""):
            val = _norm_dec(report_artifact[key_alias], target_u, target_u)
            if val is not None:
                out[norm_key] = val
                evidence_by_key[norm_key] = {
                    "raw_value": str(report_artifact[key_alias]),
                    "raw_unit": target_u,
                    "quotation": f"{key_alias}={report_artifact[key_alias]} {target_u}",
                    "page_no": report_artifact.get("page_no", 1),
                    "bbox": report_artifact.get("bbox"),
                }
    out["evidence"] = evidence_by_key
    return out


def audit_cross_artifact_consistency(
    ledger: Any | None = None,
    *,
    requirements: dict[str, Any] | None = None,
    cad: dict[str, Any] | None = None,
    fem: dict[str, Any] | None = None,
    fem_f06: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    tolerances: dict[str, str] | None = None,
    invalidate_cells: bool = True,
    actor_id: str = "cross_artifact_auditor",
    created_at: str = "2026-11-14T06:00:00Z",
    webhook_transport: Any | None = None,
) -> dict[str, Any]:
    """Compare mass, CG envelope, applied FEM loads vs .f06 reactions, and PDF/DOCX claims."""
    reqs = dict(requirements or {})
    tol = {
        "mass_kg": Decimal(str((tolerances or {}).get("mass_kg", "5.0"))),
        "cg_m": Decimal(str((tolerances or {}).get("cg_m", "0.015"))),
        "force_n": Decimal(str((tolerances or {}).get("force_n", "50.0"))),
    }
    mass_min = _norm_dec(reqs.get("mass_min_kg"), "kg", "kg")
    mass_max = _norm_dec(reqs.get("mass_max_kg"), "kg", "kg")
    cg_box_x = reqs.get("cg_x_bounds_m") or [-0.200, 0.220]
    cg_x_min = _norm_dec(cg_box_x[0], "m", "m") if len(cg_box_x) == 2 else Decimal("-0.200")
    cg_x_max = _norm_dec(cg_box_x[1], "m", "m") if len(cg_box_x) == 2 else Decimal("0.220")

    cad_mass = _extract_param_from_cad_cae(
        cad, names=("mass_kg", "total_mass", "mass"), target_unit="kg"
    )
    fem_mass = _extract_param_from_cad_cae(
        fem, names=("mass_kg", "total_mass", "conm2"), target_unit="kg"
    )
    f06_mass = _extract_param_from_cad_cae(fem_f06, names=("mass_kg",), target_unit="kg")

    cad_cg_x = _extract_param_from_cad_cae(cad, names=("cg_x_m", "cg_x", "x_cg"), target_unit="m")
    fem_cg_x = _extract_param_from_cad_cae(fem, names=("cg_x_m", "cg_x", "x_cg"), target_unit="m")
    f06_cg_x = _extract_param_from_cad_cae(fem_f06, names=("cg_x_m",), target_unit="m")

    fem_force = _extract_param_from_cad_cae(
        fem, names=("thrust_n", "resultant_force_n"), target_unit="N"
    )
    f06_load = _extract_param_from_cad_cae(
        fem_f06, names=("thrust_n", "oload_resultant_n"), target_unit="N"
    )
    f06_spc = _extract_param_from_cad_cae(fem_f06, names=("spc_reaction_n",), target_unit="N")

    rep = _extract_from_report(report)
    rep_ev = rep.get("evidence") or {}

    discrepancies: list[dict[str, Any]] = []
    tel = get_telemetry()

    def _add_discrepancy(
        *,
        category: str,
        severity: str,
        title: str,
        summary: str,
        before: dict[str, Any],
        after: dict[str, Any],
        delta: str,
        unit: str,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        seed = f"{category}:{title}:{before}:{after}"
        disc_id = "disc_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        tel.record_discrepancy(severity)
        discrepancies.append(
            {
                "discrepancy_id": disc_id,
                "category": category,
                "severity": severity,
                "title": title,
                "summary": summary,
                "before": before,
                "after": after,
                "delta": delta,
                "unit": unit,
                "provenance": provenance or {},
            }
        )

    # Check 1: Mass cross-consistency across Report PDF <-> FEM (.bdf/.inp/.f06) <-> CAD <-> Req
    mass_readings: list[tuple[str, Decimal]] = []
    if "mass" in rep:
        mass_readings.append(("PDF/Memoria", rep["mass"]))
    if fem_mass is not None:
        mass_readings.append(("FEM (.bdf/.inp)", fem_mass["value"]))
    if f06_mass is not None:
        mass_readings.append(("FEM (.f06 GPWG)", f06_mass["value"]))
    if cad_mass is not None:
        mass_readings.append(("CAD (STEP/CATIA)", cad_mass["value"]))

    if len(mass_readings) >= 2:
        min_src, min_val = min(mass_readings, key=lambda x: x[1])
        max_src, max_val = max(mass_readings, key=lambda x: x[1])
        mass_delta = max_val - min_val
        if mass_delta > tol["mass_kg"]:
            pct = (
                ((mass_delta / min_val) * Decimal("100")).quantize(Decimal("0.01"))
                if min_val > 0
                else Decimal("0")
            )
            _add_discrepancy(
                category="cross_artifact_mass_mismatch",
                severity="CRITICAL" if mass_delta >= Decimal("20") else "HIGH",
                title=f"Divergencia de Masa: {min_src} vs {max_src} (+{mass_delta} kg)",
                summary=(
                    f"{min_src} declara {min_val} kg mientras {max_src} suma {max_val} kg "
                    f"(diferencia +{mass_delta} kg / {pct}% > tol {tol['mass_kg']} kg)."
                ),
                before={"source": min_src, "mass_kg": str(min_val), "evidence": rep_ev.get("mass")},
                after={"source": max_src, "mass_kg": str(max_val)},
                delta=f"+{mass_delta}",
                unit="kg",
                provenance=rep_ev.get("mass") or {},
            )

    for label, m_val in mass_readings:
        if mass_max is not None and m_val > mass_max:
            over = m_val - mass_max
            _add_discrepancy(
                category="requirement_mass_exceedance",
                severity="CRITICAL",
                title=f"Masa excede MTOM certificado ({label}: {m_val} > {mass_max} kg)",
                summary=(
                    f"{label} pesa {m_val} kg frente a limite maximo certificado "
                    f"{mass_max} kg (+{over} kg)."
                ),
                before={"requirement_mass_max_kg": str(mass_max)},
                after={"source": label, "mass_kg": str(m_val)},
                delta=f"+{over}",
                unit="kg",
            )
        if mass_min is not None and m_val < mass_min:
            under = mass_min - m_val
            _add_discrepancy(
                category="requirement_mass_below_min",
                severity="HIGH",
                title=f"Masa bajo minimo ({label}: {m_val} < {mass_min} kg)",
                summary=f"{label} pesa {m_val} kg < minimo {mass_min} kg (-{under} kg).",
                before={"requirement_mass_min_kg": str(mass_min)},
                after={"source": label, "mass_kg": str(m_val)},
                delta=f"-{under}",
                unit="kg",
            )

    # Check 2: CG Shift between departments & outside certified CG box
    cg_readings: list[tuple[str, Decimal]] = []
    if cad_cg_x is not None:
        cg_readings.append(("CAD (STEP/CATIA)", cad_cg_x["value"]))
    if fem_cg_x is not None:
        cg_readings.append(("FEM (.bdf CONM2)", fem_cg_x["value"]))
    if f06_cg_x is not None:
        cg_readings.append(("FEM (.f06 GPWG)", f06_cg_x["value"]))
    if "cg_x" in rep:
        cg_readings.append(("PDF/Memoria", rep["cg_x"]))

    for label, cg_val in cg_readings:
        if cg_x_max is not None and cg_val > cg_x_max:
            exc_mm = ((cg_val - cg_x_max) * Decimal("1000")).quantize(Decimal("0.1"))
            _add_discrepancy(
                category="cg_envelope_exceedance",
                severity="CRITICAL",
                title=f"CG fuera de caja certificada ({label}: +{exc_mm} mm)",
                summary=(
                    f"{label} ubica cg_x = {cg_val} m, excediendo el limite posterior {cg_x_max} m "
                    f"en +{exc_mm} mm."
                ),
                before={
                    "certified_cg_x_max_m": str(cg_x_max),
                    "box_m": [str(cg_x_min), str(cg_x_max)],
                },
                after={"source": label, "cg_x_m": str(cg_val), "exceedance_mm": str(exc_mm)},
                delta=f"+{exc_mm}",
                unit="mm",
            )
        elif cg_x_min is not None and cg_val < cg_x_min:
            exc_mm = ((cg_x_min - cg_val) * Decimal("1000")).quantize(Decimal("0.1"))
            _add_discrepancy(
                category="cg_envelope_exceedance",
                severity="CRITICAL",
                title=f"CG adelantado fuera de caja certificada ({label}: -{exc_mm} mm)",
                summary=(
                    f"{label} ubica cg_x = {cg_val} m < limite anterior "
                    f"{cg_x_min} m (-{exc_mm} mm)."
                ),
                before={
                    "certified_cg_x_min_m": str(cg_x_min),
                    "box_m": [str(cg_x_min), str(cg_x_max)],
                },
                after={"source": label, "cg_x_m": str(cg_val), "exceedance_mm": f"-{exc_mm}"},
                delta=f"-{exc_mm}",
                unit="mm",
            )

    if len(cg_readings) >= 2:
        c_min_src, c_min_val = min(cg_readings, key=lambda x: x[1])
        c_max_src, c_max_val = max(cg_readings, key=lambda x: x[1])
        if (c_max_val - c_min_val) > tol["cg_m"]:
            shift_mm = ((c_max_val - c_min_val) * Decimal("1000")).quantize(Decimal("0.1"))
            _add_discrepancy(
                category="cross_artifact_cg_drift",
                severity="HIGH",
                title=f"Deriva de CG entre departamentos (+{shift_mm} mm)",
                summary=(
                    f"{c_min_src} cg_x={c_min_val} m vs {c_max_src} "
                    f"cg_x={c_max_val} m (+{shift_mm} mm)."
                ),
                before={"source": c_min_src, "cg_x_m": str(c_min_val)},
                after={"source": c_max_src, "cg_x_m": str(c_max_val)},
                delta=f"+{shift_mm}",
                unit="mm",
            )

    # Check 3: FEM applied forces vs .f06 OLOAD/SPCFORCE reactions & PDF load claims
    if fem_force is not None and f06_spc is not None:
        diff_n = (fem_force["value"] - f06_spc["value"]).copy_abs()
        if diff_n > tol["force_n"]:
            _add_discrepancy(
                category="fem_load_reaction_imbalance",
                severity="CRITICAL",
                title=f"Desequilibrio Cargas .bdf vs Reacciones SPC .f06 ({diff_n} N)",
                summary=(
                    f"Carga aplicada .bdf={fem_force['value']} N no equilibra con reaccion "
                    f"SPCFORCE .f06={f06_spc['value']} N "
                    f"(residual {diff_n} N > {tol['force_n']} N)."
                ),
                before={"source": "FEM (.bdf)", "applied_force_n": str(fem_force["value"])},
                after={"source": "FEM (.f06 SPCFORCE)", "reaction_n": str(f06_spc["value"])},
                delta=str(diff_n),
                unit="N",
            )
    if fem_force is not None and f06_load is not None:
        diff_oload = (fem_force["value"] - f06_load["value"]).copy_abs()
        if diff_oload > tol["force_n"]:
            _add_discrepancy(
                category="fem_bdf_f06_oload_mismatch",
                severity="HIGH",
                title=f"Carga .bdf difiere de OLOAD .f06 ({diff_oload} N)",
                summary=f"Carga .bdf={fem_force['value']} N vs .f06 OLOAD={f06_load['value']} N.",
                before={"source": "FEM (.bdf)", "applied_force_n": str(fem_force["value"])},
                after={"source": "FEM (.f06 OLOAD)", "oload_n": str(f06_load["value"])},
                delta=str(diff_oload),
                unit="N",
            )
    if "force" in rep and fem_force is not None:
        diff_pdf_n = (rep["force"] - fem_force["value"]).copy_abs()
        if diff_pdf_n > tol["force_n"]:
            _add_discrepancy(
                category="pdf_fem_load_mismatch",
                severity="HIGH",
                title=f"Memoria PDF declara {rep['force']} N vs .bdf {fem_force['value']} N",
                summary=(
                    f"PDF ({rep['force']} N) no coincide con carga aplicada en .bdf "
                    f"({fem_force['value']} N)."
                ),
                before={
                    "source": "PDF/Memoria",
                    "force_n": str(rep["force"]),
                    "evidence": rep_ev.get("force"),
                },
                after={"source": "FEM (.bdf)", "force_n": str(fem_force["value"])},
                delta=str(diff_pdf_n),
                unit="N",
                provenance=rep_ev.get("force") or {},
            )

    if isinstance(fem_f06, dict):
        f06_node = fem_f06.get("cad_cae") if isinstance(fem_f06.get("cad_cae"), dict) else fem_f06
        fatals = f06_node.get("fatal_errors") or []
        if fatals:
            _add_discrepancy(
                category="nastran_f06_fatal_error",
                severity="CRITICAL",
                title=f"NASTRAN .f06 reporta {len(fatals)} USER FATAL MESSAGE",
                summary=str(fatals[0]),
                before={"expected": "0 FATAL diagnostics"},
                after={"fatal_count": len(fatals), "sample": str(fatals[0])},
                delta=str(len(fatals)),
                unit="errors",
            )

    invalidated_cell_ids: list[str] = []
    invalidated_events: list[str] = []
    webhook_deliveries: list[dict[str, Any]] = []

    if discrepancies and invalidate_cells and ledger is not None:
        cells: list[Cell] = generate_cells()
        statuses = list_cells_with_status(ledger.events(), cells=cells)
        calc_cells = [c["cell_id"] for c in statuses if c["status"] == "calc"]
        target_cells = calc_cells if calc_cells else [c.cell_id for c in cells[:2]]
        reason_ids = [d["discrepancy_id"] for d in discrepancies]
        for cid in target_cells:
            src_digest = hashlib.sha256(f"{cid}:{','.join(reason_ids)}".encode()).hexdigest()
            envelope = make_envelope(
                sources=[
                    project_source(
                        "cross_artifact_auditor",
                        "https://aeroregu.local/cross-artifact",
                        "VERIFIED",
                        content_hash=src_digest,
                    )
                ],
                method_version="cross_artifact_auditor@1.0.0",
                inputs={"cell_id": cid, "discrepancy_ids": reason_ids},
                confidence="deterministic",
                result={"cell_id": cid, "status": "invalidated"},
            )
            ev_h = record(
                ledger,
                {
                    "event_type": "invalidated",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "cell_id": cid,
                        "reason": "cross_artifact_inconsistency",
                        "discrepancy_ids": reason_ids,
                    },
                    "envelope": envelope,
                },
            )
            invalidated_cell_ids.append(cid)
            invalidated_events.append(ev_h)

        subs = ledger.list_webhooks(include_secret=True) if hasattr(ledger, "list_webhooks") else []
        if subs:
            webhook_deliveries = dispatch_webhook_with_retry(
                subs,
                event_name="envelope_invalidated",
                payload={
                    "reason": "cross_artifact_inconsistency",
                    "invalidated_cells": invalidated_cell_ids,
                    "discrepancy_ids": reason_ids,
                },
                ledger=ledger,
                transport=webhook_transport,
            )

    return {
        "consistent": len(discrepancies) == 0,
        "discrepancy_count": len(discrepancies),
        "critical_count": sum(1 for d in discrepancies if d["severity"] == "CRITICAL"),
        "discrepancies": discrepancies,
        "invalidated_cell_ids": invalidated_cell_ids,
        "invalidated_event_hashes": invalidated_events,
        "webhook_deliveries": webhook_deliveries,
        "observed": {
            "cad_mass_kg": str(cad_mass["value"]) if cad_mass else None,
            "fem_mass_kg": str(fem_mass["value"]) if fem_mass else None,
            "f06_mass_kg": str(f06_mass["value"]) if f06_mass else None,
            "pdf_mass_kg": str(rep["mass"]) if "mass" in rep else None,
            "cad_cg_x_m": str(cad_cg_x["value"]) if cad_cg_x else None,
            "fem_cg_x_m": str(fem_cg_x["value"]) if fem_cg_x else None,
            "fem_force_n": str(fem_force["value"]) if fem_force else None,
            "f06_spcforce_n": str(f06_spc["value"]) if f06_spc else None,
        },
    }
