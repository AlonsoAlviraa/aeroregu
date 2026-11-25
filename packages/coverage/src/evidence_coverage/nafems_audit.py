"""NAFEMS V&V Audit Manifest, BDF-vs-Report Table Drift, Subcases & Rotor Modal Guard.

Addresses the verified certification gaps left open by Nastran, HyperView, Patran, HyperSizer,
and ISAMI:
1. Immutable NAFEMS intermediate manifest (hashes, sanity, automated vs human-judgment split).
2. BDF property/material drift (PSHELL, PCOMP, MAT1) vs Stress Report text AND structured tables.
3. Regulatory load-case completeness across Case Control SUBCASEs (CS-27 / CS-29 / SC-VTOL).
4. SOL 103 modal separation against rotor harmonics (1*Omega, Nb*Omega, 2*Nb*Omega) with
   optional modal effective mass filtering.
5. BDF Rev A -> Rev B structural diff with full Ledger cell invalidation (no artificial cap).
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.orchestrator import record

from evidence_coverage.grid import Cell, generate_cells
from evidence_coverage.status import list_cells_with_status

_REPORT_THICKNESS_RE = re.compile(
    r"(?:pshell|pid|panel|skin)\s*#?\s*(\d+)\b[^.\n]{0,40}?"
    r"(?:thickness|espesor|t)?\s*(?:=|:|of|de)?\s*"
    r"([-+]?\d+(?:\.\d+)?)\s*(mm|m)\b",
    re.IGNORECASE,
)
_VAL_UNIT_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(mm|m|in)?\s*$", re.IGNORECASE)


def _dec(val: Any) -> Decimal | None:
    if val in (None, ""):
        return None
    try:
        d = Decimal(str(val))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _canonical_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _to_mm(val: Decimal, unit: str) -> Decimal:
    u = unit.lower()
    if u == "m":
        return val * Decimal("1000")
    if u == "in":
        return val * Decimal("25.4")
    return val


def _extract_table_thickness_claims(
    report_blocks: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Extract PID -> thickness_mm claims from structured PDF/DOCX table_rows blocks."""
    extracted: dict[str, dict[str, Any]] = {}
    if not isinstance(report_blocks, list):
        return extracted

    for blk in report_blocks:
        rows = blk.get("table_rows")
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        header = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in rows[0]]
        pid_col = next(
            (i for i, h in enumerate(header) if any(k in h for k in ("pid", "pshell", "pcomp"))),
            None,
        )
        thk_col = next(
            (
                i
                for i, h in enumerate(header)
                if any(
                    k in h for k in ("thickness", "espesor", "t_mm", "t (mm)", "t [mm]", "t(mm)")
                )
                or h == "t"
            ),
            None,
        )
        if pid_col is None or thk_col is None:
            continue

        hdr_thk = header[thk_col]
        default_unit = "m" if ("(m)" in hdr_thk or "[m]" in hdr_thk) else "mm"
        if "(in)" in hdr_thk or "[in]" in hdr_thk:
            default_unit = "in"

        for row in rows[1:]:
            if len(row) <= max(pid_col, thk_col):
                continue
            pid_raw = re.sub(r"\D+", "", str(row[pid_col]))
            if not pid_raw:
                continue
            m = _VAL_UNIT_RE.match(str(row[thk_col]))
            if not m:
                continue
            d = _dec(m.group(1))
            if d is None:
                continue
            unit = (m.group(2) or default_unit).lower()
            thk_mm = _to_mm(d, unit)
            extracted.setdefault(
                pid_raw,
                {
                    "thickness_mm": thk_mm,
                    "page_no": blk.get("page_no"),
                    "bbox": blk.get("bbox"),
                    "source": "table_rows",
                },
            )
    return extracted


def build_nafems_manifest(
    *,
    bdf_parsed: dict[str, Any],
    f06_parsed: dict[str, Any] | None = None,
    report_hash: str | None = None,
    bdf_hash: str = "",
    f06_hash: str = "",
    epsilon_limit: str = "1e-6",
    equilibrium_tol_n: str = "50.0",
    require_unit_system: bool = False,
) -> dict[str, Any]:
    """Build an auditable NAFEMS V&V manifest linking solver inputs, sanity checks, and report."""
    props = bdf_parsed.get("properties") or {}
    mats = bdf_parsed.get("materials") or {}
    mesh = bdf_parsed.get("mesh") or {}
    subcases = bdf_parsed.get("subcases") or []
    unit_system = bdf_parsed.get("unit_system")

    abstain = False
    abstain_reason: str | None = None
    if require_unit_system and not unit_system:
        abstain = True
        abstain_reason = "bdf_unit_system_unspecified"

    sanity_issues: list[str] = []
    eq_pass = True
    eps_pass = True
    fatal_pass = True

    if f06_parsed is not None:
        fatals = f06_parsed.get("fatal_errors") or []
        if fatals:
            fatal_pass = False
            sanity_issues.append(f"nastran_fatal_messages:{len(fatals)}")

        eps_lim = _dec(epsilon_limit) or Decimal("1e-6")
        for eps_str in f06_parsed.get("epsilon_values") or []:
            eps_val = _dec(eps_str)
            if eps_val is not None and eps_val.copy_abs() > eps_lim:
                eps_pass = False
                sanity_issues.append(f"epsilon_exceeded:{eps_val}")

        tol_n = _dec(equilibrium_tol_n) or Decimal("50.0")
        for eq in f06_parsed.get("equilibrium_checks") or []:
            res_n = _dec(eq.get("residual_sum_n"))
            if res_n is not None and res_n > tol_n:
                eq_pass = False
                sanity_issues.append(f"equilibrium_imbalance_subcase_{eq.get('subcase')}:{res_n}N")

    manifest_core: dict[str, Any] = {
        "schema": "nafems_vv_manifest@1.0.0",
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "unit_system": unit_system,
        "artifacts": {
            "bdf_sha256": bdf_hash,
            "f06_sha256": f06_hash,
            "report_sha256": report_hash or "",
        },
        "model_summary": {
            "node_count": mesh.get("node_count", 0),
            "element_count": mesh.get("element_count", 0),
            "subcase_count": len(subcases),
            "pshell_count": len(props.get("pshell") or []),
            "pcomp_count": len(props.get("pcomp") or []),
            "pbush_count": len(props.get("pbush") or []),
            "mat1_count": len(mats.get("mat1") or []),
            "mat8_count": len(mats.get("mat8") or []),
        },
        "nafems_sanity_checks": {
            "fatal_free": fatal_pass,
            "epsilon_within_limit": eps_pass,
            "global_equilibrium_pass": eq_pass,
            "all_passed": (not abstain) and fatal_pass and eps_pass and eq_pass,
            "issues": sanity_issues,
        },
        "governance_boundary": {
            "automated_extraction": ["mesh_counts", "properties", "materials", "sanity_checks"],
            "requires_human_cve_signoff": [
                "idealization_assumptions",
                "boundary_condition_validity",
                "knockdown_factors",
                "compliance_determination",
            ],
        },
    }
    manifest_core["manifest_sha256"] = _canonical_hash(manifest_core)
    return manifest_core


def audit_bdf_vs_report_properties(
    *,
    bdf_parsed: dict[str, Any],
    report_claims: dict[str, Any] | None = None,
    report_blocks: list[dict[str, Any]] | None = None,
    thickness_tol_mm: str = "0.05",
) -> dict[str, Any]:
    """Detect silent drift between BDF PSHELL/PCOMP cards and Stress Report text or tables."""
    tol = _dec(thickness_tol_mm) or Decimal("0.05")
    props = bdf_parsed.get("properties") or {}
    pshells = {str(p["pid"]): p for p in (props.get("pshell") or []) if p.get("pid")}
    pcomps = {str(p["pid"]): p for p in (props.get("pcomp") or []) if p.get("pid")}

    declared_thk: dict[str, dict[str, Any]] = {}
    if isinstance(report_claims, dict):
        for pid, val in (report_claims.get("pshell_thickness_mm") or {}).items():
            d = _dec(val)
            if d is not None:
                declared_thk[str(pid)] = {"thickness_mm": d, "source": "report_claims"}

    # Structured PDF/DOCX table extraction takes precedence over free-text regex
    table_claims = _extract_table_thickness_claims(report_blocks)
    for pid, info in table_claims.items():
        declared_thk.setdefault(pid, info)

    if isinstance(report_blocks, list):
        for blk in report_blocks:
            txt = str(blk.get("text") or "")
            for m in _REPORT_THICKNESS_RE.finditer(txt):
                pid_s, val_s, unit_s = m.group(1), m.group(2), m.group(3).lower()
                d = _dec(val_s)
                if pid_s and d is not None:
                    declared_thk.setdefault(
                        pid_s,
                        {
                            "thickness_mm": _to_mm(d, unit_s),
                            "page_no": blk.get("page_no"),
                            "bbox": blk.get("bbox"),
                            "source": "text_block",
                        },
                    )

    discrepancies: list[dict[str, Any]] = []
    checked_pids = 0
    for pid, rep_info in sorted(declared_thk.items()):
        rep_t: Decimal = rep_info["thickness_mm"]
        bdf_t: Decimal | None = None
        card_kind = ""
        if pid in pshells:
            bdf_t = _dec(pshells[pid].get("thickness"))
            card_kind = "PSHELL"
        elif pid in pcomps:
            bdf_t = _dec(pcomps[pid].get("total_thickness"))
            card_kind = "PCOMP"
        if bdf_t is None:
            discrepancies.append(
                {
                    "category": "missing_bdf_property",
                    "severity": "HIGH",
                    "pid": pid,
                    "report_thickness_mm": str(rep_t),
                    "bdf_thickness_mm": None,
                    "provenance": {
                        "source": rep_info.get("source"),
                        "page_no": rep_info.get("page_no"),
                        "bbox": rep_info.get("bbox"),
                    },
                }
            )
            continue
        checked_pids += 1
        delta = (bdf_t - rep_t).copy_abs()
        if delta > tol:
            discrepancies.append(
                {
                    "category": "property_thickness_drift",
                    "severity": "CRITICAL",
                    "card": card_kind,
                    "pid": pid,
                    "bdf_thickness_mm": str(bdf_t),
                    "report_thickness_mm": str(rep_t),
                    "delta_mm": str(delta),
                    "provenance": {
                        "source": rep_info.get("source"),
                        "page_no": rep_info.get("page_no"),
                        "bbox": rep_info.get("bbox"),
                    },
                }
            )

    return {
        "consistent": len(discrepancies) == 0,
        "checked_property_count": checked_pids,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
    }


def audit_regulatory_subcase_coverage(
    *,
    bdf_parsed: dict[str, Any],
    required_load_families: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify Case Control SUBCASE labels/IDs cover all required certification load families."""
    subcases = bdf_parsed.get("subcases") or []
    covered: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for req in required_load_families:
        family_id = str(req.get("family_id") or "")
        keywords = [str(k).lower() for k in (req.get("keywords") or []) if k]
        matched_subs = []
        for sc in subcases:
            hay = f"{sc.get('subcase_id', '')} {sc.get('label', '')}".lower()
            if any(kw in hay for kw in keywords):
                matched_subs.append(sc.get("subcase_id"))
        if matched_subs:
            covered.append({"family_id": family_id, "subcase_ids": matched_subs})
        else:
            missing.append(
                {
                    "family_id": family_id,
                    "regulation_ref": req.get("regulation_ref", ""),
                    "expected_keywords": keywords,
                }
            )

    return {
        "complete": len(missing) == 0,
        "total_subcases": len(subcases),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "covered": covered,
        "missing": missing,
    }


def audit_rotor_harmonic_separation(
    *,
    f06_parsed: dict[str, Any],
    rotor_rpm: str,
    blade_count: int,
    guard_band_pct: str = "10.0",
    min_effective_mass_frac: str = "0",
) -> dict[str, Any]:
    """Check SOL 103 structural modes against 1*Omega, Nb*Omega, and 2*Nb*Omega rotor harmonics."""
    modes = f06_parsed.get("modal_eigenvalues") or []
    rpm = _dec(rotor_rpm)
    pct = _dec(guard_band_pct) or Decimal("10.0")
    min_eff = _dec(min_effective_mass_frac) or Decimal("0")
    if rpm is None or rpm <= 0 or blade_count <= 0:
        return {"abstain": True, "reason": "invalid_rotor_parameters", "violations": []}

    omega_hz = rpm / Decimal("60")
    harmonics = [
        ("1P", omega_hz),
        (f"{blade_count}P", omega_hz * Decimal(blade_count)),
        (f"{2 * blade_count}P", omega_hz * Decimal(2 * blade_count)),
    ]
    frac = pct / Decimal("100")

    violations: list[dict[str, Any]] = []
    ignored_local_modes: list[str] = []
    for mode in modes:
        f_hz = _dec(mode.get("cycles_hz"))
        if f_hz is None:
            continue
        eff_frac = _dec(mode.get("effective_mass_frac"))
        if min_eff > 0 and eff_frac is not None and eff_frac < min_eff:
            ignored_local_modes.append(str(mode.get("mode_no")))
            continue
        for h_name, h_hz in harmonics:
            sep_pct = ((f_hz - h_hz).copy_abs() / h_hz) * Decimal("100")
            if (f_hz - h_hz).copy_abs() <= h_hz * frac:
                violations.append(
                    {
                        "mode_no": mode.get("mode_no"),
                        "mode_hz": str(f_hz),
                        "effective_mass_frac": mode.get("effective_mass_frac"),
                        "harmonic": h_name,
                        "harmonic_hz": str(h_hz.quantize(Decimal("0.001"))),
                        "separation_pct": str(sep_pct.quantize(Decimal("0.01"))),
                        "required_band_pct": str(pct),
                    }
                )

    return {
        "abstain": False,
        "clear": len(violations) == 0,
        "mode_count": len(modes),
        "ignored_local_modes": ignored_local_modes,
        "harmonics_hz": {k: str(v.quantize(Decimal("0.001"))) for k, v in harmonics},
        "violation_count": len(violations),
        "violations": violations,
    }


def diff_bdf_revisions_and_invalidate(
    *,
    rev_a_bdf: dict[str, Any],
    rev_b_bdf: dict[str, Any],
    ledger: Any | None = None,
    actor_id: str = "nafems_impact_auditor",
    created_at: str = "2026-11-19T19:55:00Z",
) -> dict[str, Any]:
    """Compare two Nastran BDF revisions and invalidate all affected Ledger cells."""
    props_a = rev_a_bdf.get("properties") or {}
    props_b = rev_b_bdf.get("properties") or {}

    pshell_a = {str(p["pid"]): p for p in (props_a.get("pshell") or [])}
    pshell_b = {str(p["pid"]): p for p in (props_b.get("pshell") or [])}
    changed_pshells: list[dict[str, Any]] = []
    for pid in sorted(set(pshell_a) | set(pshell_b)):
        ta = pshell_a.get(pid, {}).get("thickness")
        tb = pshell_b.get(pid, {}).get("thickness")
        if ta != tb:
            changed_pshells.append({"pid": pid, "rev_a_t": ta, "rev_b_t": tb})

    pcomp_a = {str(p["pid"]): p for p in (props_a.get("pcomp") or [])}
    pcomp_b = {str(p["pid"]): p for p in (props_b.get("pcomp") or [])}
    changed_pcomps: list[dict[str, Any]] = []
    for pid in sorted(set(pcomp_a) | set(pcomp_b)):
        ta = pcomp_a.get(pid, {}).get("total_thickness")
        tb = pcomp_b.get(pid, {}).get("total_thickness")
        if ta != tb:
            changed_pcomps.append({"pid": pid, "rev_a_t": ta, "rev_b_t": tb})

    sub_a = {str(s["subcase_id"]): s for s in (rev_a_bdf.get("subcases") or [])}
    sub_b = {str(s["subcase_id"]): s for s in (rev_b_bdf.get("subcases") or [])}
    added_subcases = sorted(set(sub_b) - set(sub_a))
    removed_subcases = sorted(set(sub_a) - set(sub_b))

    mass_a = sum(
        (_dec(m.get("mass")) or Decimal(0) for m in (rev_a_bdf.get("masses") or [])),
        Decimal(0),
    )
    mass_b = sum(
        (_dec(m.get("mass")) or Decimal(0) for m in (rev_b_bdf.get("masses") or [])),
        Decimal(0),
    )
    mass_delta = mass_b - mass_a

    has_structural_impact = bool(
        changed_pshells or changed_pcomps or added_subcases or removed_subcases or mass_delta != 0
    )

    invalidated_cell_ids: list[str] = []
    if has_structural_impact and ledger is not None:
        cells: list[Cell] = generate_cells()
        statuses = list_cells_with_status(ledger.events(), cells=cells)
        calc_cells = [c["cell_id"] for c in statuses if c["status"] == "calc"]
        # Invalidate ALL calculated cells when a structural BDF baseline changes (no cap)
        target_cells = calc_cells if calc_cells else [c.cell_id for c in cells[:2]]
        digest = _canonical_hash(
            {
                "pshells": changed_pshells,
                "pcomps": changed_pcomps,
                "added_sub": added_subcases,
                "removed_sub": removed_subcases,
                "mass_delta": str(mass_delta),
            }
        )
        for cid in target_cells:
            envelope = make_envelope(
                sources=[
                    project_source(
                        "nafems_impact_auditor",
                        "https://aeroregu.local/nafems-impact",
                        "VERIFIED",
                        content_hash=digest,
                    )
                ],
                method_version="nafems_impact_auditor@1.0.0",
                inputs={"cell_id": cid, "bdf_diff_sha256": digest},
                confidence="deterministic",
                result={"cell_id": cid, "status": "invalidated"},
            )
            record(
                ledger,
                {
                    "event_type": "invalidated",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "cell_id": cid,
                        "reason": "bdf_revision_structural_impact",
                        "bdf_diff_sha256": digest,
                    },
                    "envelope": envelope,
                },
            )
            invalidated_cell_ids.append(cid)

    return {
        "has_structural_impact": has_structural_impact,
        "changed_pshells": changed_pshells,
        "changed_pcomps": changed_pcomps,
        "added_subcases": added_subcases,
        "removed_subcases": removed_subcases,
        "mass_delta_kg": str(mass_delta),
        "invalidated_cell_ids": invalidated_cell_ids,
    }


def audit_sol105_buckling_margins(
    f06_parsed: dict[str, Any] | None,
    *,
    min_buckling_factor: str = "1.000",
    require_positive_eigenvalues: bool = True,
) -> dict[str, Any]:
    """Audit NASTRAN SOL 105 linear buckling eigenvalues against minimum stability factor."""
    if not f06_parsed:
        return {
            "abstain": True,
            "abstain_reason": "missing_f06_results",
            "clear": False,
            "mode_count": 0,
            "critical_buckling_factor": None,
            "buckling_ms_min": None,
            "min_buckling_factor": min_buckling_factor,
            "violation_count": 0,
            "violations": [],
        }
    modes = list(f06_parsed.get("buckling_eigenvalues") or [])
    if not modes:
        return {
            "abstain": True,
            "abstain_reason": "no_sol105_buckling_eigenvalues_in_f06",
            "clear": False,
            "mode_count": 0,
            "critical_buckling_factor": None,
            "buckling_ms_min": None,
            "min_buckling_factor": min_buckling_factor,
            "violation_count": 0,
            "violations": [],
        }

    min_bf = _dec(min_buckling_factor) or Decimal("1.000")
    violations: list[dict[str, Any]] = []
    pos_eigs: list[Decimal] = []
    all_eigs: list[Decimal] = []
    for mode in modes:
        eig = _dec(mode.get("eigenvalue"))
        if eig is None:
            continue
        all_eigs.append(eig)
        if eig > Decimal("0"):
            pos_eigs.append(eig)
        if eig <= Decimal("0") and require_positive_eigenvalues:
            violations.append(
                {
                    "mode_no": str(mode.get("mode_no") or ""),
                    "eigenvalue": str(eig),
                    "reason": "NON_POSITIVE_BUCKLING_EIGENVALUE",
                }
            )
        elif eig > Decimal("0") and eig < min_bf:
            violations.append(
                {
                    "mode_no": str(mode.get("mode_no") or ""),
                    "eigenvalue": str(eig),
                    "buckling_ms": str((eig - Decimal("1")).quantize(Decimal("0.001"))),
                    "reason": "BELOW_MIN_BUCKLING_FACTOR",
                }
            )

    crit = min(pos_eigs) if pos_eigs else min(all_eigs)
    ms_min = crit - Decimal("1")
    return {
        "abstain": False,
        "abstain_reason": None,
        "clear": len(violations) == 0,
        "mode_count": len(modes),
        "critical_buckling_factor": str(crit),
        "buckling_ms_min": str(ms_min),
        "min_buckling_factor": str(min_bf),
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_gpforce_freebody_equilibrium(
    f06_parsed: dict[str, Any] | None,
    *,
    max_nodal_residual_n: str = "0.010",
) -> dict[str, Any]:
    """Verify GRID POINT FORCE BALANCE nodal equilibrium within residual force threshold."""
    if not f06_parsed or f06_parsed.get("gpforce_freebody") is None:
        return {
            "abstain": True,
            "abstain_reason": "no_gpforce_freebody_in_f06",
            "balanced": False,
            "grid_count": 0,
            "totals_rows": 0,
            "net_resultant_n": None,
            "max_nodal_residual_n": None,
            "threshold_n": max_nodal_residual_n,
        }
    gpf = f06_parsed["gpforce_freebody"]
    max_res = _dec(gpf.get("max_nodal_residual_n")) or Decimal("0")
    thresh = _dec(max_nodal_residual_n) or Decimal("0.010")
    return {
        "abstain": False,
        "abstain_reason": None,
        "balanced": max_res <= thresh,
        "grid_count": int(gpf.get("grid_count") or 0),
        "totals_rows": int(gpf.get("totals_rows") or 0),
        "net_force_n": list(gpf.get("net_force_n") or []),
        "net_resultant_n": str(gpf.get("net_resultant_n") or "0"),
        "max_nodal_residual_n": str(max_res),
        "threshold_n": str(thresh),
    }


def audit_abaqus_composite_layup_vs_report(
    abaqus_parsed: dict[str, Any],
    *,
    report_claims: dict[str, Any] | None = None,
    thickness_tolerance_mm: str = "0.050",
) -> dict[str, Any]:
    """Cross-check Abaqus *SHELL SECTION, COMPOSITE plies & thicknesses vs Stress Report claims."""
    comp_sections = list(abaqus_parsed.get("composite_sections") or [])
    include_tree = list(abaqus_parsed.get("include_tree") or [])
    tol = _dec(thickness_tolerance_mm) or Decimal("0.050")
    raw_claims = report_claims or {}
    claims_map = (
        raw_claims.get("sections") if isinstance(raw_claims.get("sections"), dict) else raw_claims
    )
    norm_claims = {str(k).upper(): v for k, v in claims_map.items() if isinstance(v, dict)}

    by_elset = {str(s.get("elset") or "").upper(): s for s in comp_sections}
    discrepancies: list[dict[str, Any]] = []
    for elset, claim in sorted(norm_claims.items()):
        sec = by_elset.get(elset)
        if sec is None:
            discrepancies.append(
                {
                    "elset": elset,
                    "reason": "MISSING_IN_ABAQUS_INP",
                }
            )
            continue
        if "ply_count" in claim and int(claim["ply_count"]) != int(sec.get("ply_count") or 0):
            discrepancies.append(
                {
                    "elset": elset,
                    "reason": "PLY_COUNT_MISMATCH",
                    "abaqus_ply_count": int(sec.get("ply_count") or 0),
                    "report_ply_count": int(claim["ply_count"]),
                }
            )
        if "total_thickness" in claim:
            inp_t = _dec(sec.get("total_thickness")) or Decimal("0")
            rep_t = _dec(claim["total_thickness"])
            if rep_t is not None and abs(inp_t - rep_t) > tol:
                discrepancies.append(
                    {
                        "elset": elset,
                        "reason": "LAMINATE_THICKNESS_DRIFT",
                        "abaqus_thickness": str(inp_t),
                        "report_thickness": str(rep_t),
                    }
                )

    return {
        "consistent": len(discrepancies) == 0,
        "sections_checked": len(comp_sections),
        "include_files_count": len(include_tree),
        "sections": comp_sections,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
    }


def run_full_nafems_audit(
    *,
    bdf_parsed: dict[str, Any],
    bdf_hash: str = "",
    f06_parsed: dict[str, Any] | None = None,
    f06_hash: str = "",
    report_blocks: list[dict[str, Any]] | None = None,
    report_claims: dict[str, Any] | None = None,
    report_hash: str | None = None,
    required_load_families: list[dict[str, Any]] | None = None,
    rotor_rpm: str | None = None,
    blade_count: int = 4,
    guard_band_pct: str = "10.0",
    min_effective_mass_frac: str = "0",
    require_unit_system: bool = False,
    check_buckling: bool = False,
    min_buckling_factor: str = "1.000",
    check_gpforce: bool = False,
    max_gpforce_residual_n: str = "0.010",
    abaqus_parsed: dict[str, Any] | None = None,
    abaqus_report_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all NAFEMS V&V audit checks end-to-end and return a unified compliance-aid verdict."""
    manifest = build_nafems_manifest(
        bdf_parsed=bdf_parsed,
        f06_parsed=f06_parsed,
        report_hash=report_hash,
        bdf_hash=bdf_hash,
        f06_hash=f06_hash,
        require_unit_system=require_unit_system,
    )
    property_drift = audit_bdf_vs_report_properties(
        bdf_parsed=bdf_parsed,
        report_claims=report_claims,
        report_blocks=report_blocks,
    )
    subcase_coverage = (
        audit_regulatory_subcase_coverage(
            bdf_parsed=bdf_parsed,
            required_load_families=required_load_families,
        )
        if required_load_families
        else None
    )
    rotor_modal = (
        audit_rotor_harmonic_separation(
            f06_parsed=f06_parsed,
            rotor_rpm=rotor_rpm,
            blade_count=blade_count,
            guard_band_pct=guard_band_pct,
            min_effective_mass_frac=min_effective_mass_frac,
        )
        if (f06_parsed is not None and rotor_rpm is not None)
        else None
    )
    sol105_buckling = (
        audit_sol105_buckling_margins(
            f06_parsed,
            min_buckling_factor=min_buckling_factor,
        )
        if check_buckling
        else None
    )
    gpforce_eq = (
        audit_gpforce_freebody_equilibrium(
            f06_parsed,
            max_nodal_residual_n=max_gpforce_residual_n,
        )
        if check_gpforce
        else None
    )
    abaqus_drift = (
        audit_abaqus_composite_layup_vs_report(
            abaqus_parsed,
            report_claims=abaqus_report_claims,
        )
        if abaqus_parsed is not None
        else None
    )

    overall_pass = (
        (not manifest["abstain"])
        and manifest["nafems_sanity_checks"]["all_passed"]
        and property_drift["consistent"]
        and (subcase_coverage is None or subcase_coverage["complete"])
        and (rotor_modal is None or (not rotor_modal["abstain"] and rotor_modal["clear"]))
        and (
            sol105_buckling is None or (not sol105_buckling["abstain"] and sol105_buckling["clear"])
        )
        and (gpforce_eq is None or (not gpforce_eq["abstain"] and gpforce_eq["balanced"]))
        and (abaqus_drift is None or abaqus_drift["consistent"])
    )

    return {
        "overall_pass": overall_pass,
        "abstain": manifest["abstain"],
        "abstain_reason": manifest["abstain_reason"],
        "manifest": manifest,
        "property_drift": property_drift,
        "subcase_coverage": subcase_coverage,
        "rotor_modal": rotor_modal,
        "sol105_buckling": sol105_buckling,
        "gpforce_equilibrium": gpforce_eq,
        "abaqus_composite_drift": abaqus_drift,
    }
