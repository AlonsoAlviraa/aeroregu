"""Deterministic FEM mesh and load parsers for NASTRAN (.bdf/.dat) and ABAQUS (.inp)."""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from evidence_ingest.blocks import Block, IngestAbstain
from evidence_ingest.cad_common import (
    compute_bbox_and_centroid,
    decimal_str,
    make_param_entry,
    parse_decimal_str,
)

_NASTRAN_ELEM_CARDS = {"CQUAD4", "CTRIA3", "CHEXA", "CTETRA", "CBAR", "CBEAM", "CROD", "CBUSH"}


def _decimal_hypot3(x: Decimal, y: Decimal, z: Decimal) -> Decimal:
    sq = x * x + y * y + z * z
    if sq == 0:
        return Decimal(0)
    return sq.sqrt()


def _nastran_dec(raw: str | None) -> Decimal | None:
    parsed = parse_decimal_str(raw, allow_nastran_short=True)
    return Decimal(parsed) if parsed is not None else None


def _split_nastran_line_fields(line: str) -> tuple[str, list[str], str]:
    """Split a single NASTRAN physical line into (card_or_cont, data_fields, tail_cont)."""
    stripped = line.rstrip("\r\n")
    if "," in stripped and not stripped.lstrip().startswith("$"):
        # Free-field comma-separated
        parts = [p.strip() for p in stripped.split(",")]
        head = parts[0].strip()
        return head, parts[1:9], parts[9] if len(parts) > 9 else ""

    padded = stripped.ljust(80)
    head = padded[0:8].strip()
    if head.endswith("*"):
        # Large-field: 4 x 16-char data fields (cols 9..72), continuation cols 73..80
        fields = [padded[8 + 16 * i : 8 + 16 * (i + 1)].strip() for i in range(4)]
        return head, fields, padded[72:80].strip()

    # Small-field: 8 x 8-char data fields (cols 9..72), continuation cols 73..80
    fields = [padded[8 + 8 * i : 8 + 8 * (i + 1)].strip() for i in range(8)]
    return head, fields, padded[72:80].strip()


_UNIT_COMMENT_RE = re.compile(
    r"^\$\s*UNITS?\s*[:=]\s*([A-Z0-9_\-/]+)",
    re.IGNORECASE,
)


def _iter_nastran_lines(
    raw: bytes,
    *,
    base_dir: Path | None = None,
    current_dir: Path | None = None,
    _visited: set[Path] | None = None,
    _depth: int = 0,
    include_records: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    """Stream physical NASTRAN lines and safely expand nested INCLUDE directives."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    visited = _visited if _visited is not None else set()
    resolved_base = base_dir.resolve() if base_dir is not None else None
    active_dir = (current_dir or base_dir).resolve() if (current_dir or base_dir) else None

    for line in io.StringIO(text):
        stripped = line.strip()
        if stripped.upper().startswith("INCLUDE"):
            if resolved_base is None or active_dir is None or _depth >= 12:
                continue
            m_inc = re.match(r"^INCLUDE\s+['\"]?([^'\"]+)['\"]?", stripped, re.IGNORECASE)
            if not m_inc:
                continue
            rel = m_inc.group(1).strip()
            candidate_local = (active_dir / rel).resolve()
            candidate_root = (resolved_base / rel).resolve()
            candidate: Path | None = None
            for cand in (candidate_local, candidate_root):
                if cand.is_relative_to(resolved_base) and cand.is_file():
                    candidate = cand
                    break
            if candidate is None or candidate in visited:
                continue
            visited.add(candidate)
            inc_bytes = candidate.read_bytes()
            if include_records is not None:
                try:
                    rel_display = str(candidate.relative_to(resolved_base)).replace("\\", "/")
                except ValueError:
                    rel_display = candidate.name
                include_records.append(
                    {
                        "relative_path": rel_display,
                        "depth": _depth + 1,
                        "sha256": hashlib.sha256(inc_bytes).hexdigest(),
                        "line_count": len(inc_bytes.splitlines()),
                    }
                )
            yield from _iter_nastran_lines(
                inc_bytes,
                base_dir=resolved_base,
                current_dir=candidate.parent,
                _visited=visited,
                _depth=_depth + 1,
                include_records=include_records,
            )
            continue
        yield line


def _iter_nastran_cards(
    raw: bytes,
    *,
    base_dir: Path | None = None,
    include_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None, Iterator[tuple[str, list[str]]]]:
    """Stream Case Control SUBCASEs, optional unit comment, and bulk cards in O(1) card RAM."""
    subcases: list[dict[str, Any]] = []
    detected_unit_system: str | None = None
    cur_sub: dict[str, Any] | None = None
    in_bulk = False

    # Peek Case Control until BEGIN BULK (or first bulk card if no BEGIN BULK)
    header_lines: list[str] = []
    stream = _iter_nastran_lines(
        raw,
        base_dir=base_dir,
        include_records=include_records,
    )
    for line in stream:
        m_u = _UNIT_COMMENT_RE.match(line.strip())
        if m_u and detected_unit_system is None:
            detected_unit_system = m_u.group(1).upper()
        code_part = line.split("$", 1)[0].strip()
        if not code_part:
            continue
        upper = code_part.upper()
        if upper.startswith("BEGIN BULK"):
            in_bulk = True
            break
        m_sub = re.match(r"^SUBCASE\s+(\d+)", upper)
        if m_sub:
            if cur_sub is not None:
                subcases.append(cur_sub)
            cur_sub = {
                "subcase_id": m_sub.group(1),
                "label": "",
                "load_sid": "",
                "spc_sid": "",
                "method": "",
            }
            continue
        if cur_sub is not None:
            if upper.startswith("LABEL"):
                _, _, val = code_part.partition("=")
                cur_sub["label"] = val.strip()
                continue
            if upper.startswith("LOAD"):
                _, _, val = code_part.partition("=")
                cur_sub["load_sid"] = val.strip()
                continue
            if upper.startswith("SPC"):
                _, _, val = code_part.partition("=")
                cur_sub["spc_sid"] = val.strip()
                continue
            if upper.startswith("METHOD"):
                _, _, val = code_part.partition("=")
                cur_sub["method"] = val.strip()
                continue
        # If this looks like a direct bulk card without BEGIN BULK, push back into bulk phase
        head_tok = code_part.split(",")[0][:8].strip().rstrip("*").upper()
        if (
            head_tok
            in {
                "GRID",
                "FORCE",
                "MOMENT",
                "PLOAD4",
                "GRAV",
                "LOAD",
                "CONM2",
                "PSHELL",
                "PCOMP",
                "PCOMPG",
                "PBAR",
                "PBARL",
                "PBEAM",
                "PBEAML",
                "PSOLID",
                "PBUSH",
                "MAT1",
                "MAT8",
                "CORD2R",
                "CORD2C",
                "CORD2S",
                "CORD1R",
                "CORD1C",
                "CORD1S",
                "SPC",
                "SPC1",
                "RBE2",
                "RBE3",
                "MPC",
            }
            | _NASTRAN_ELEM_CARDS
        ):
            header_lines.append(line)
            in_bulk = True
            break

    if cur_sub is not None:
        subcases.append(cur_sub)

    def _card_gen() -> Iterator[tuple[str, list[str]]]:
        cur_name = ""
        cur_fields: list[str] = []

        def _chain() -> Iterator[str]:
            yield from header_lines
            if in_bulk:
                yield from stream

        for raw_line in _chain():
            code_part = raw_line.split("$", 1)[0].rstrip("\r\n")
            if not code_part.strip():
                continue
            upper = code_part.strip().upper()
            if upper.startswith("ENDDATA"):
                break
            head, fields, _ = _split_nastran_line_fields(code_part)
            is_cont = (
                head == ""
                or head == "*"
                or head.startswith("+")
                or (head.startswith("*") and len(head) > 1 and not head[:-1].isalpha())
            )
            if is_cont and cur_name:
                cur_fields.extend(fields)
            else:
                if cur_name:
                    yield cur_name, cur_fields
                cur_name = head.rstrip("*").upper()
                cur_fields = list(fields)
        if cur_name:
            yield cur_name, cur_fields

    return subcases, detected_unit_system, _card_gen()


def parse_nastran_bdf(
    raw: bytes,
    source_hash: str,
    *,
    base_dir: Path | None = None,
    unit_system: str | None = None,
) -> dict[str, Any]:
    """Stream-parse NASTRAN .bdf/.dat bulk data (GRID, loads, GRAV/LOAD, CONM2, props, mats)."""
    include_records: list[dict[str, Any]] = []
    subcases, comment_units, cards_iter = _iter_nastran_cards(
        raw, base_dir=base_dir, include_records=include_records
    )
    resolved_unit_system = unit_system or comment_units

    grids: dict[str, dict[str, str]] = {}
    grid_pts: list[tuple[Decimal, Decimal, Decimal]] = []
    local_cp_grid_count = 0
    coordinate_systems: list[dict[str, str]] = []
    forces: list[dict[str, Any]] = []
    moments: list[dict[str, Any]] = []
    pload4s: list[dict[str, Any]] = []
    grav_cards: list[dict[str, Any]] = []
    load_combos: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    conm2_masses: list[dict[str, Any]] = []
    pshells: list[dict[str, Any]] = []
    pcomps: list[dict[str, Any]] = []
    pbushes: list[dict[str, Any]] = []
    pbars: list[dict[str, Any]] = []
    pbeams: list[dict[str, Any]] = []
    psolids: list[dict[str, Any]] = []
    mat1s: list[dict[str, Any]] = []
    mat8s: list[dict[str, Any]] = []
    spc_constrained_dofs = 0
    mpc_rbe_dependent_dofs = 0
    rbe2_count = 0
    rbe3_count = 0
    mpc_count = 0
    card_count = 0

    def _f(fields: list[str], idx: int) -> str:
        return fields[idx].strip() if idx < len(fields) else ""

    def _dof_count(digits: str) -> int:
        return len({ch for ch in digits if ch in "123456"})

    for name, fields in cards_iter:
        card_count += 1
        if name == "GRID":
            gid = _f(fields, 0)
            cp = _f(fields, 1) or "0"
            x = _nastran_dec(_f(fields, 2))
            y = _nastran_dec(_f(fields, 3))
            z = _nastran_dec(_f(fields, 4))
            ps_dof = _f(fields, 6)
            if gid and x is not None and y is not None and z is not None:
                sx, sy, sz = decimal_str(x), decimal_str(y), decimal_str(z)
                grids[gid] = {"id": gid, "cp": cp, "x": sx, "y": sy, "z": sz}
                grid_pts.append((x, y, z))
                if cp not in ("", "0"):
                    local_cp_grid_count += 1
                if ps_dof:
                    spc_constrained_dofs += _dof_count(ps_dof)

        elif name in {"CORD2R", "CORD2C", "CORD2S", "CORD1R", "CORD1C", "CORD1S"}:
            cid = _f(fields, 0)
            rid = _f(fields, 1) or "0"
            if cid:
                coordinate_systems.append({"cid": cid, "card_type": name, "rid": rid})

        elif name == "FORCE":
            sid = _f(fields, 0) or "1"
            gid = _f(fields, 1)
            cid = _f(fields, 2) or "0"
            scale = _nastran_dec(_f(fields, 3))
            n1 = _nastran_dec(_f(fields, 4)) or Decimal(0)
            n2 = _nastran_dec(_f(fields, 5)) or Decimal(0)
            n3 = _nastran_dec(_f(fields, 6)) or Decimal(0)
            if gid and scale is not None:
                fx, fy, fz = scale * n1, scale * n2, scale * n3
                mag = _decimal_hypot3(fx, fy, fz)
                forces.append(
                    {
                        "sid": sid,
                        "grid_id": gid,
                        "cid": cid,
                        "scale": decimal_str(scale),
                        "direction": [decimal_str(n1), decimal_str(n2), decimal_str(n3)],
                        "vector_n": [decimal_str(fx), decimal_str(fy), decimal_str(fz)],
                        "magnitude_n": decimal_str(mag),
                    }
                )

        elif name == "MOMENT":
            sid = _f(fields, 0) or "1"
            gid = _f(fields, 1)
            cid = _f(fields, 2) or "0"
            scale = _nastran_dec(_f(fields, 3))
            n1 = _nastran_dec(_f(fields, 4)) or Decimal(0)
            n2 = _nastran_dec(_f(fields, 5)) or Decimal(0)
            n3 = _nastran_dec(_f(fields, 6)) or Decimal(0)
            if gid and scale is not None:
                mx, my, mz = scale * n1, scale * n2, scale * n3
                mag = _decimal_hypot3(mx, my, mz)
                moments.append(
                    {
                        "sid": sid,
                        "grid_id": gid,
                        "cid": cid,
                        "scale": decimal_str(scale),
                        "direction": [decimal_str(n1), decimal_str(n2), decimal_str(n3)],
                        "vector_n_m": [decimal_str(mx), decimal_str(my), decimal_str(mz)],
                        "magnitude_n_m": decimal_str(mag),
                    }
                )

        elif name == "PLOAD4":
            sid = _f(fields, 0) or "1"
            eid = _f(fields, 1)
            p1 = _nastran_dec(_f(fields, 2))
            p2 = _nastran_dec(_f(fields, 3))
            p3 = _nastran_dec(_f(fields, 4))
            p4 = _nastran_dec(_f(fields, 5))
            g1 = _f(fields, 6)
            g34 = _f(fields, 7)
            cid = _f(fields, 8) or "0"
            n1 = _nastran_dec(_f(fields, 9))
            n2 = _nastran_dec(_f(fields, 10))
            n3 = _nastran_dec(_f(fields, 11))
            if eid and p1 is not None:
                pressures = [p for p in (p1, p2, p3, p4) if p is not None]
                p_avg = sum(pressures, Decimal(0)) / Decimal(len(pressures))
                pload4s.append(
                    {
                        "sid": sid,
                        "eid": eid,
                        "pressures": [decimal_str(p) for p in pressures],
                        "mean_pressure": decimal_str(p_avg),
                        "g1": g1,
                        "g3_or_g4": g34,
                        "cid": cid,
                        "vector": (
                            [decimal_str(n1), decimal_str(n2), decimal_str(n3)]
                            if n1 is not None and n2 is not None and n3 is not None
                            else None
                        ),
                    }
                )

        elif name == "CONM2":
            eid = _f(fields, 0)
            gid = _f(fields, 1)
            cid = _f(fields, 2) or "0"
            mass = _nastran_dec(_f(fields, 3))
            ox = _nastran_dec(_f(fields, 4)) or Decimal(0)
            oy = _nastran_dec(_f(fields, 5)) or Decimal(0)
            oz = _nastran_dec(_f(fields, 6)) or Decimal(0)
            if eid and gid and mass is not None:
                base = grids.get(gid)
                gx = Decimal(base["x"]) + ox if base else ox
                gy = Decimal(base["y"]) + oy if base else oy
                gz = Decimal(base["z"]) + oz if base else oz
                conm2_masses.append(
                    {
                        "eid": eid,
                        "grid_id": gid,
                        "cid": cid,
                        "mass": decimal_str(mass),
                        "cg": [decimal_str(gx), decimal_str(gy), decimal_str(gz)],
                    }
                )

        elif name in _NASTRAN_ELEM_CARDS:
            eid = _f(fields, 0)
            pid = _f(fields, 1)
            node_ids = [f for f in fields[2:] if f and f.isdigit()]
            if eid and node_ids:
                elements.append({"eid": eid, "type": name, "pid": pid, "node_ids": node_ids})

        elif name == "GRAV":
            sid = _f(fields, 0) or "1"
            cid = _f(fields, 1) or "0"
            scale_a = _nastran_dec(_f(fields, 2))
            n1 = _nastran_dec(_f(fields, 3)) or Decimal(0)
            n2 = _nastran_dec(_f(fields, 4)) or Decimal(0)
            n3 = _nastran_dec(_f(fields, 5)) or Decimal(0)
            if scale_a is not None:
                grav_cards.append(
                    {
                        "sid": sid,
                        "cid": cid,
                        "scale": decimal_str(scale_a),
                        "direction": [decimal_str(n1), decimal_str(n2), decimal_str(n3)],
                    }
                )

        elif name == "LOAD":
            sid = _f(fields, 0)
            global_s = _nastran_dec(_f(fields, 1)) or Decimal(1)
            terms: list[dict[str, str]] = []
            idx_l = 2
            while idx_l + 1 < len(fields):
                si = _nastran_dec(_f(fields, idx_l))
                li = _f(fields, idx_l + 1)
                if si is not None and li:
                    terms.append({"scale": decimal_str(si), "sid": li})
                idx_l += 2
            if sid and terms:
                load_combos.append(
                    {"sid": sid, "global_scale": decimal_str(global_s), "terms": terms}
                )

        elif name == "PSHELL":
            pid = _f(fields, 0)
            mid1 = _f(fields, 1)
            t = _nastran_dec(_f(fields, 2))
            if pid and t is not None:
                pshells.append({"pid": pid, "mid1": mid1, "thickness": decimal_str(t)})

        elif name in {"PCOMP", "PCOMPG"}:
            pid = _f(fields, 0)
            lam_opt = _f(fields, 7).upper()
            symmetric = lam_opt == "SYM"
            step_w = 5 if name == "PCOMPG" else 4
            plies: list[dict[str, Any]] = []
            total_t = Decimal(0)
            idx_p = 8
            while idx_p + 1 < len(fields):
                if name == "PCOMPG":
                    mid_p = _f(fields, idx_p + 1)
                    t_p = _nastran_dec(_f(fields, idx_p + 2))
                    theta_p = _nastran_dec(_f(fields, idx_p + 3)) or Decimal(0)
                else:
                    mid_p = _f(fields, idx_p)
                    t_p = _nastran_dec(_f(fields, idx_p + 1))
                    theta_p = _nastran_dec(_f(fields, idx_p + 2)) or Decimal(0)
                if mid_p and t_p is not None:
                    plies.append(
                        {
                            "mid": mid_p,
                            "thickness": decimal_str(t_p),
                            "theta_deg": decimal_str(theta_p),
                        }
                    )
                    total_t += t_p
                idx_p += step_w
            if pid:
                eff_plies = len(plies) * 2 if symmetric else len(plies)
                eff_total_t = total_t * Decimal(2) if symmetric else total_t
                pcomps.append(
                    {
                        "pid": pid,
                        "symmetric": symmetric,
                        "lam": lam_opt or "FULL",
                        "ply_count": eff_plies,
                        "total_thickness": decimal_str(eff_total_t),
                        "plies": plies,
                    }
                )

        elif name in {"PBAR", "PBARL"}:
            pid = _f(fields, 0)
            mid = _f(fields, 1)
            if pid:
                if name == "PBAR":
                    area = _nastran_dec(_f(fields, 2))
                    pbars.append(
                        {
                            "pid": pid,
                            "mid": mid,
                            "card_type": name,
                            "area": decimal_str(area) if area is not None else None,
                        }
                    )
                else:
                    pbars.append(
                        {
                            "pid": pid,
                            "mid": mid,
                            "card_type": name,
                            "section_type": _f(fields, 3) or _f(fields, 2),
                        }
                    )

        elif name in {"PBEAM", "PBEAML"}:
            pid = _f(fields, 0)
            mid = _f(fields, 1)
            if pid:
                pbeams.append({"pid": pid, "mid": mid, "card_type": name})

        elif name == "PSOLID":
            pid = _f(fields, 0)
            mid = _f(fields, 1)
            if pid:
                psolids.append({"pid": pid, "mid": mid})

        elif name == "PBUSH":
            pid = _f(fields, 0)
            # K values follow "K" keyword in fields[1:]
            k_vals: list[str] = []
            if len(fields) > 2 and _f(fields, 1).upper() == "K":
                for kf in fields[2:8]:
                    kd = _nastran_dec(kf)
                    k_vals.append(decimal_str(kd) if kd is not None else "0")
            if pid:
                pbushes.append({"pid": pid, "stiffness_k": k_vals})

        elif name == "SPC":
            for g_idx, c_idx in ((1, 2), (4, 5)):
                if _f(fields, g_idx) and _f(fields, c_idx):
                    spc_constrained_dofs += _dof_count(_f(fields, c_idx))

        elif name == "SPC1":
            d_cnt = _dof_count(_f(fields, 1))
            if d_cnt > 0:
                toks = [t for t in fields[2:] if t]
                grid_cnt = 0
                i_t = 0
                while i_t < len(toks):
                    if (
                        i_t + 2 < len(toks)
                        and toks[i_t + 1].upper() == "THRU"
                        and toks[i_t].isdigit()
                        and toks[i_t + 2].isdigit()
                    ):
                        grid_cnt += max(1, int(toks[i_t + 2]) - int(toks[i_t]) + 1)
                        i_t += 3
                    elif toks[i_t].isdigit():
                        grid_cnt += 1
                        i_t += 1
                    else:
                        i_t += 1
                spc_constrained_dofs += d_cnt * grid_cnt

        elif name == "RBE2":
            rbe2_count += 1
            cm_digits = _dof_count(_f(fields, 2)) or 6
            dep_grids = [t for t in fields[3:] if t and t.isdigit()]
            mpc_rbe_dependent_dofs += cm_digits * max(1, len(dep_grids))

        elif name == "RBE3":
            rbe3_count += 1
            refc_digits = _dof_count(_f(fields, 2)) or 6
            mpc_rbe_dependent_dofs += refc_digits

        elif name == "MPC":
            mpc_count += 1
            mpc_rbe_dependent_dofs += 1

        elif name == "MAT1":
            mid = _f(fields, 0)
            e_val = _nastran_dec(_f(fields, 1))
            g_val = _nastran_dec(_f(fields, 2))
            nu_val = _nastran_dec(_f(fields, 3))
            rho_val = _nastran_dec(_f(fields, 4))
            if mid:
                mat1s.append(
                    {
                        "mid": mid,
                        "e": decimal_str(e_val) if e_val is not None else None,
                        "g": decimal_str(g_val) if g_val is not None else None,
                        "nu": decimal_str(nu_val) if nu_val is not None else None,
                        "rho": decimal_str(rho_val) if rho_val is not None else None,
                    }
                )

        elif name == "MAT8":
            mid = _f(fields, 0)
            e1 = _nastran_dec(_f(fields, 1))
            e2 = _nastran_dec(_f(fields, 2))
            nu12 = _nastran_dec(_f(fields, 3))
            g12 = _nastran_dec(_f(fields, 4))
            rho_val = _nastran_dec(_f(fields, 7))
            if mid:
                mat8s.append(
                    {
                        "mid": mid,
                        "e1": decimal_str(e1) if e1 is not None else None,
                        "e2": decimal_str(e2) if e2 is not None else None,
                        "nu12": decimal_str(nu12) if nu12 is not None else None,
                        "g12": decimal_str(g12) if g12 is not None else None,
                        "rho": decimal_str(rho_val) if rho_val is not None else None,
                    }
                )

    if card_count == 0 or (
        not grids
        and not forces
        and not moments
        and not pload4s
        and not grav_cards
        and not pshells
        and not pcomps
        and not pbars
        and not pbeams
        and not psolids
    ):
        raise IngestAbstain("empty_nastran_bulk")

    # Mass & CG from CONM2 first so GRAV inertial forces can be evaluated
    cg_points: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    total_mass = sum((Decimal(c["mass"]) for c in conm2_masses), Decimal(0))

    # Summarize direct loads per SID (FORCE + MOMENT + PLOAD4 + GRAV)
    direct_sids = sorted(
        {f["sid"] for f in forces}
        | {m["sid"] for m in moments}
        | {p["sid"] for p in pload4s}
        | {g["sid"] for g in grav_cards}
    )
    direct_force_by_sid: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    direct_moment_by_sid: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    load_cases: list[dict[str, Any]] = []

    for sid in direct_sids:
        sf = [f for f in forces if f["sid"] == sid]
        sm = [m for m in moments if m["sid"] == sid]
        sp = [p for p in pload4s if p["sid"] == sid]
        sg = [g for g in grav_cards if g["sid"] == sid]
        fx = sum((Decimal(f["vector_n"][0]) for f in sf), Decimal(0))
        fy = sum((Decimal(f["vector_n"][1]) for f in sf), Decimal(0))
        fz = sum((Decimal(f["vector_n"][2]) for f in sf), Decimal(0))
        for g in sg:
            g_scale = Decimal(g["scale"])
            fx += total_mass * g_scale * Decimal(g["direction"][0])
            fy += total_mass * g_scale * Decimal(g["direction"][1])
            fz += total_mass * g_scale * Decimal(g["direction"][2])
        mx = sum((Decimal(m["vector_n_m"][0]) for m in sm), Decimal(0))
        my = sum((Decimal(m["vector_n_m"][1]) for m in sm), Decimal(0))
        mz = sum((Decimal(m["vector_n_m"][2]) for m in sm), Decimal(0))
        direct_force_by_sid[sid] = (fx, fy, fz)
        direct_moment_by_sid[sid] = (mx, my, mz)
        peak_f = max((Decimal(f["magnitude_n"]) for f in sf), default=Decimal(0))
        peak_p = max((Decimal(p["mean_pressure"]) for p in sp), default=Decimal(0))
        load_cases.append(
            {
                "sid": sid,
                "is_combination": False,
                "force_count": len(sf),
                "moment_count": len(sm),
                "pload4_count": len(sp),
                "grav_count": len(sg),
                "total_force_n": [decimal_str(fx), decimal_str(fy), decimal_str(fz)],
                "resultant_force_n": decimal_str(_decimal_hypot3(fx, fy, fz)),
                "total_moment_n_m": [decimal_str(mx), decimal_str(my), decimal_str(mz)],
                "peak_nodal_force_n": decimal_str(peak_f),
                "peak_pload4_pressure": decimal_str(peak_p),
            }
        )

    # Resolve linear LOAD combinations: F_total = S * sum(S_i * F_{L_i})
    for combo in load_combos:
        csid = combo["sid"]
        gs = Decimal(combo["global_scale"])
        fx, fy, fz = Decimal(0), Decimal(0), Decimal(0)
        mx, my, mz = Decimal(0), Decimal(0), Decimal(0)
        for term in combo["terms"]:
            si = Decimal(term["scale"])
            li = term["sid"]
            df = direct_force_by_sid.get(li, (Decimal(0), Decimal(0), Decimal(0)))
            dm = direct_moment_by_sid.get(li, (Decimal(0), Decimal(0), Decimal(0)))
            fx += gs * si * df[0]
            fy += gs * si * df[1]
            fz += gs * si * df[2]
            mx += gs * si * dm[0]
            my += gs * si * dm[1]
            mz += gs * si * dm[2]
        load_cases.append(
            {
                "sid": csid,
                "is_combination": True,
                "terms": combo["terms"],
                "force_count": 0,
                "moment_count": 0,
                "pload4_count": 0,
                "grav_count": 0,
                "total_force_n": [decimal_str(fx), decimal_str(fy), decimal_str(fz)],
                "resultant_force_n": decimal_str(_decimal_hypot3(fx, fy, fz)),
                "total_moment_n_m": [decimal_str(mx), decimal_str(my), decimal_str(mz)],
                "peak_nodal_force_n": "0",
                "peak_pload4_pressure": "0",
            }
        )
    if total_mass > 0:
        cx = (
            sum((Decimal(c["mass"]) * Decimal(c["cg"][0]) for c in conm2_masses), Decimal(0))
            / total_mass
        )
        cy = (
            sum((Decimal(c["mass"]) * Decimal(c["cg"][1]) for c in conm2_masses), Decimal(0))
            / total_mass
        )
        cz = (
            sum((Decimal(c["mass"]) * Decimal(c["cg"][2]) for c in conm2_masses), Decimal(0))
            / total_mass
        )
        cg_coords = [decimal_str(cx), decimal_str(cy), decimal_str(cz)]
        cg_points.append(
            {
                "label": "NASTRAN_CONM2_CG",
                "coords": cg_coords,
                "unit": "m",
                "source_kind": "nastran_conm2",
            }
        )
        parameters.append(
            make_param_entry(
                path="NASTRAN\\CONM2\\mass_kg",
                name="mass_kg",
                value=decimal_str(total_mass),
                unit="kg",
                source_kind="nastran_bdf",
            )
        )
        parameters.append(
            make_param_entry(
                path="NASTRAN\\CONM2\\cg_x_m",
                name="cg_x_m",
                value=cg_coords[0],
                unit="m",
                source_kind="nastran_bdf",
            )
        )

    if load_cases:
        lc0 = load_cases[0]
        parameters.append(
            make_param_entry(
                path=f"NASTRAN\\SID_{lc0['sid']}\\resultant_force_n",
                name="thrust_n",
                value=lc0["resultant_force_n"],
                unit="N",
                source_kind="nastran_bdf",
            )
        )
        # Shear (X-Y plane resultant) & tensile (Z) for fastener/bolt screening bindings
        fx0, fy0, fz0 = (Decimal(v) for v in lc0["total_force_n"])
        shear_xy = (fx0 * fx0 + fy0 * fy0).sqrt() if (fx0 != 0 or fy0 != 0) else Decimal(0)
        parameters.append(
            make_param_entry(
                path=f"NASTRAN\\SID_{lc0['sid']}\\shear_force_n",
                name="shear_force_n",
                value=decimal_str(shear_xy),
                unit="N",
                source_kind="nastran_bdf",
            )
        )
        parameters.append(
            make_param_entry(
                path=f"NASTRAN\\SID_{lc0['sid']}\\tensile_force_n",
                name="tensile_force_n",
                value=decimal_str(fz0.copy_abs()),
                unit="N",
                source_kind="nastran_bdf",
            )
        )

    bbox, geo_centroid = compute_bbox_and_centroid(grid_pts)
    if not cg_points and geo_centroid is not None:
        cg_points.append(
            {
                "label": "NASTRAN_Mesh_Centroid_ESTIMATE",
                "coords": geo_centroid,
                "unit": "m",
                "source_kind": "nastran_estimate",
            }
        )

    block_lines = [
        f"NASTRAN Bulk Data: GRID={len(grids)}, ELEMENTS={len(elements)}, "
        f"FORCE={len(forces)}, MOMENT={len(moments)}, PLOAD4={len(pload4s)}, "
        f"CONM2={len(conm2_masses)}"
    ]
    for lc in load_cases:
        block_lines.append(
            f"NASTRAN SID={lc['sid']}: Resultant={lc['resultant_force_n']} N "
            f"F={lc['total_force_n']} M={lc['total_moment_n_m']} PLOAD4={lc['pload4_count']}"
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
                block_kind="nastran_bdf",
            )
        )
        offset += len(line) + 1

    raw_dofs = 6 * len(grids)
    active_dofs = max(0, raw_dofs - spc_constrained_dofs - mpc_rbe_dependent_dofs)
    cbush_elem_count = sum(1 for el in elements if el.get("type") == "CBUSH")
    structural_elem_count = len(elements) - cbush_elem_count

    return {
        "format": "nastran_bdf",
        "unit_system": resolved_unit_system,
        "subcases": subcases,
        "include_tree": include_records,
        "coordinate_systems": coordinate_systems,
        "local_cp_grid_count": local_cp_grid_count,
        "dof_summary": {
            "node_count": len(grids),
            "raw_dofs": raw_dofs,
            "spc_constrained_dofs": spc_constrained_dofs,
            "mpc_rbe_dependent_dofs": mpc_rbe_dependent_dofs,
            "active_dofs": active_dofs,
            "rbe2_count": rbe2_count,
            "rbe3_count": rbe3_count,
            "mpc_count": mpc_count,
        },
        "mesh": {
            "node_count": len(grids),
            "element_count": len(elements),
            "structural_element_count": structural_elem_count,
            "cbush_element_count": cbush_elem_count,
            "nodes": list(grids.values())[:2500],
            "elements": elements[:2500],
            "bbox": bbox,
        },
        "properties": {
            "pshell": pshells,
            "pcomp": pcomps,
            "pbush": pbushes,
            "pbar": pbars,
            "pbeam": pbeams,
            "psolid": psolids,
        },
        "materials": {
            "mat1": mat1s,
            "mat8": mat8s,
        },
        "loads": {
            "forces": forces,
            "moments": moments,
            "pload4": pload4s,
            "grav": grav_cards,
            "load_combinations": load_combos,
            "load_cases": load_cases,
        },
        "masses": conm2_masses,
        "cg_points": cg_points,
        "parameters": parameters,
        "blocks": blocks,
    }


def _iter_abaqus_lines(
    raw: bytes,
    *,
    base_dir: Path | None = None,
    current_dir: Path | None = None,
    _visited: set[Path] | None = None,
    _depth: int = 0,
    include_records: list[dict[str, Any]] | None = None,
) -> Iterator[str]:
    """Stream Abaqus .inp lines and safely expand sandboxed *INCLUDE directives."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    visited = _visited if _visited is not None else set()
    resolved_base = base_dir.resolve() if base_dir is not None else None
    active_dir = (current_dir or base_dir).resolve() if (current_dir or base_dir) else None

    for line in io.StringIO(text):
        stripped = line.strip()
        if stripped.upper().startswith("*INCLUDE"):
            if resolved_base is None or active_dir is None or _depth >= 12:
                continue
            _, params = _parse_abaqus_header(stripped)
            rel = str(params.get("INPUT", "")).strip().strip("'\"")
            if not rel:
                continue
            candidate_local = (active_dir / rel).resolve()
            candidate_root = (resolved_base / rel).resolve()
            candidate: Path | None = None
            for cand in (candidate_local, candidate_root):
                if cand.is_relative_to(resolved_base) and cand.is_file():
                    candidate = cand
                    break
            if candidate is None or candidate in visited:
                continue
            visited.add(candidate)
            inc_bytes = candidate.read_bytes()
            if include_records is not None:
                try:
                    rel_display = str(candidate.relative_to(resolved_base)).replace("\\", "/")
                except ValueError:
                    rel_display = candidate.name
                include_records.append(
                    {
                        "relative_path": rel_display,
                        "depth": _depth + 1,
                        "sha256": hashlib.sha256(inc_bytes).hexdigest(),
                        "line_count": len(inc_bytes.splitlines()),
                    }
                )
            yield from _iter_abaqus_lines(
                inc_bytes,
                base_dir=resolved_base,
                current_dir=candidate.parent,
                _visited=visited,
                _depth=_depth + 1,
                include_records=include_records,
            )
            continue
        yield line


def _split_abaqus_logical_lines(text: str) -> list[str]:
    """Join Abaqus comma-continued lines and strip ** comments."""
    logical: list[str] = []
    buf = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        if stripped.startswith("*"):
            if buf:
                logical.append(buf)
                buf = ""
            logical.append(stripped)
            continue
        if buf:
            buf += " " + stripped
        else:
            buf = stripped
        if not stripped.endswith(","):
            logical.append(buf)
            buf = ""
    if buf:
        logical.append(buf)
    return logical


def _parse_abaqus_header(line: str) -> tuple[str, dict[str, str]]:
    parts = [p.strip() for p in line.split(",") if p.strip()]
    kw = parts[0].upper()
    params: dict[str, str] = {}
    for item in parts[1:]:
        if "=" in item:
            k, v = item.split("=", 1)
            params[k.strip().upper()] = v.strip()
        else:
            params[item.upper()] = "true"
    return kw, params


def parse_abaqus_inp(
    raw: bytes,
    source_hash: str,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Parse ABAQUS .inp mesh, *INCLUDE tree, composite shells, BCs, *MASS, and loads."""
    include_tree: list[dict[str, Any]] = []
    expanded_text = "".join(
        _iter_abaqus_lines(raw, base_dir=base_dir, include_records=include_tree)
    )

    lines = _split_abaqus_logical_lines(expanded_text)
    if not lines:
        raise IngestAbstain("empty_abaqus_inp")

    nodes: dict[str, dict[str, str]] = {}
    node_pts: list[tuple[Decimal, Decimal, Decimal]] = []
    elements: list[dict[str, Any]] = []
    nsets: dict[str, list[str]] = {}
    elsets: dict[str, list[str]] = {}
    cloads: list[dict[str, Any]] = []
    dloads: list[dict[str, Any]] = []
    masses: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    composite_sections: list[dict[str, Any]] = []
    current_composite: dict[str, Any] | None = None
    heading_lines: list[str] = []

    current_kw = ""
    current_params: dict[str, str] = {}
    current_step = "STEP_0"
    step_idx = 0

    def _flush_composite() -> None:
        nonlocal current_composite
        if current_composite is not None:
            current_composite["ply_count"] = len(current_composite["plies"])
            composite_sections.append(current_composite)
            current_composite = None

    for line in lines:
        if line.startswith("*"):
            _flush_composite()
            current_kw, current_params = _parse_abaqus_header(line)
            if current_kw == "*STEP":
                step_idx += 1
                current_step = current_params.get("NAME") or f"STEP_{step_idx}"
            elif current_kw == "*END STEP":
                current_step = "MODEL"
            elif current_kw == "*SHELL SECTION" and "COMPOSITE" in current_params:
                current_composite = {
                    "elset": current_params.get("ELSET", ""),
                    "layup": current_params.get("LAYUP", ""),
                    "plies": [],
                    "ply_count": 0,
                    "total_thickness": "0",
                }
            continue

        fields = [f.strip() for f in line.split(",") if f.strip() != ""]
        if not fields:
            continue

        if current_kw == "*HEADING":
            heading_lines.append(line)

        elif current_kw == "*NODE" and len(fields) >= 3:
            nid = fields[0]
            x = parse_decimal_str(fields[1])
            y = parse_decimal_str(fields[2])
            z = parse_decimal_str(fields[3]) if len(fields) > 3 else "0"
            if nid and x is not None and y is not None and z is not None:
                nodes[nid] = {"id": nid, "x": x, "y": y, "z": z}
                node_pts.append((Decimal(x), Decimal(y), Decimal(z)))
                nset_name = current_params.get("NSET")
                if nset_name:
                    nsets.setdefault(nset_name.upper(), []).append(nid)

        elif current_kw == "*ELEMENT" and len(fields) >= 2:
            eid = fields[0]
            etype = current_params.get("TYPE", "UNKNOWN")
            conn = fields[1:]
            elements.append({"eid": eid, "type": etype, "node_ids": conn})
            elset_name = current_params.get("ELSET")
            if elset_name:
                elsets.setdefault(elset_name.upper(), []).append(eid)

        elif current_kw == "*NSET":
            sname = current_params.get("NSET", "").upper()
            if sname:
                bucket = nsets.setdefault(sname, [])
                if "GENERATE" in current_params and len(fields) >= 2:
                    try:
                        start, stop = int(fields[0]), int(fields[1])
                        step = int(fields[2]) if len(fields) > 2 else 1
                        bucket.extend(str(i) for i in range(start, stop + 1, max(1, step)))
                    except ValueError:
                        pass
                else:
                    bucket.extend(fields)

        elif current_kw == "*ELSET":
            sname = current_params.get("ELSET", "").upper()
            if sname:
                bucket = elsets.setdefault(sname, [])
                if "GENERATE" in current_params and len(fields) >= 2:
                    try:
                        start, stop = int(fields[0]), int(fields[1])
                        step = int(fields[2]) if len(fields) > 2 else 1
                        bucket.extend(str(i) for i in range(start, stop + 1, max(1, step)))
                    except ValueError:
                        pass
                else:
                    bucket.extend(fields)

        elif current_kw == "*MASS":
            elset_ref = current_params.get("ELSET", "").upper()
            mval = parse_decimal_str(fields[0])
            if mval is not None:
                target_eids = elsets.get(elset_ref, [elset_ref or "MASS"])
                for teid in target_eids:
                    # Find element node if exists
                    elem = next((e for e in elements if e["eid"] == teid), None)
                    nid = elem["node_ids"][0] if elem and elem["node_ids"] else teid
                    n_rec = nodes.get(nid)
                    cg = [n_rec["x"], n_rec["y"], n_rec["z"]] if n_rec else ["0", "0", "0"]
                    masses.append({"eid": teid, "elset": elset_ref, "mass": mval, "cg": cg})

        elif current_kw == "*CLOAD" and len(fields) >= 3:
            target = fields[0]
            try:
                dof = int(fields[1])
            except ValueError:
                continue
            mag = parse_decimal_str(fields[2])
            if mag is None:
                continue
            expanded_nodes = nsets.get(target.upper(), [target])
            cloads.append(
                {
                    "step": current_step,
                    "target": target,
                    "node_count": len(expanded_nodes),
                    "dof": dof,
                    "magnitude": mag,
                }
            )

        elif current_kw in {"*DLOAD", "*DSLOAD"} and len(fields) >= 3:
            target = fields[0]
            load_type = fields[1]
            mag = parse_decimal_str(fields[2])
            if mag is not None:
                dloads.append(
                    {
                        "step": current_step,
                        "keyword": current_kw,
                        "target": target,
                        "load_type": load_type,
                        "magnitude": mag,
                    }
                )

        elif current_kw == "*BOUNDARY" and len(fields) >= 2:
            boundaries.append({"target": fields[0], "dofs": fields[1:]})

        elif current_kw == "*SHELL SECTION" and current_composite is not None:
            thk_str = parse_decimal_str(fields[0])
            if thk_str is not None:
                int_pts = "3"
                mat_name = ""
                angle_deg = "0"
                if len(fields) >= 4 and fields[1].isdigit():
                    int_pts = fields[1]
                    mat_name = fields[2]
                    angle_deg = parse_decimal_str(fields[3]) or "0"
                elif len(fields) == 3:
                    if fields[1].isdigit() and parse_decimal_str(fields[2]) is None:
                        int_pts = fields[1]
                        mat_name = fields[2]
                    else:
                        mat_name = fields[1]
                        angle_deg = parse_decimal_str(fields[2]) or "0"
                elif len(fields) == 2:
                    mat_name = fields[1]
                current_composite["plies"].append(
                    {
                        "thickness": thk_str,
                        "integration_points": int_pts,
                        "material": mat_name,
                        "angle_deg": angle_deg,
                    }
                )
                prev_t = Decimal(str(current_composite["total_thickness"]))
                current_composite["total_thickness"] = decimal_str(prev_t + Decimal(thk_str))

    _flush_composite()
    if not nodes and not cloads and not dloads and not masses:
        raise IngestAbstain("empty_abaqus_inp")

    # Summarize *CLOAD resultants per step
    steps = sorted({c["step"] for c in cloads} | {d["step"] for d in dloads})
    load_cases: list[dict[str, Any]] = []
    for st in steps:
        sc = [c for c in cloads if c["step"] == st]
        sd = [d for d in dloads if d["step"] == st]
        fx = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 1), Decimal(0)
        )
        fy = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 2), Decimal(0)
        )
        fz = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 3), Decimal(0)
        )
        mx = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 4), Decimal(0)
        )
        my = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 5), Decimal(0)
        )
        mz = sum(
            (Decimal(c["magnitude"]) * c["node_count"] for c in sc if c["dof"] == 6), Decimal(0)
        )
        load_cases.append(
            {
                "step": st,
                "cload_count": len(sc),
                "dload_count": len(sd),
                "total_force_n": [decimal_str(fx), decimal_str(fy), decimal_str(fz)],
                "resultant_force_n": decimal_str(_decimal_hypot3(fx, fy, fz)),
                "total_moment_n_m": [decimal_str(mx), decimal_str(my), decimal_str(mz)],
            }
        )

    cg_points: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    total_mass = sum((Decimal(m["mass"]) for m in masses), Decimal(0))
    if total_mass > 0:
        cx = (
            sum((Decimal(m["mass"]) * Decimal(m["cg"][0]) for m in masses), Decimal(0)) / total_mass
        )
        cy = (
            sum((Decimal(m["mass"]) * Decimal(m["cg"][1]) for m in masses), Decimal(0)) / total_mass
        )
        cz = (
            sum((Decimal(m["mass"]) * Decimal(m["cg"][2]) for m in masses), Decimal(0)) / total_mass
        )
        cg_coords = [decimal_str(cx), decimal_str(cy), decimal_str(cz)]
        cg_points.append(
            {
                "label": "ABAQUS_MASS_CG",
                "coords": cg_coords,
                "unit": "m",
                "source_kind": "abaqus_mass",
            }
        )
        parameters.append(
            make_param_entry(
                path="ABAQUS\\MASS\\mass_kg",
                name="mass_kg",
                value=decimal_str(total_mass),
                unit="kg",
                source_kind="abaqus_inp",
            )
        )
        parameters.append(
            make_param_entry(
                path="ABAQUS\\MASS\\cg_x_m",
                name="cg_x_m",
                value=cg_coords[0],
                unit="m",
                source_kind="abaqus_inp",
            )
        )

    if load_cases:
        lc0 = load_cases[0]
        parameters.append(
            make_param_entry(
                path=f"ABAQUS\\{lc0['step']}\\resultant_force_n",
                name="thrust_n",
                value=lc0["resultant_force_n"],
                unit="N",
                source_kind="abaqus_inp",
            )
        )
        fx0, fy0, fz0 = (Decimal(v) for v in lc0["total_force_n"])
        shear_xy = (fx0 * fx0 + fy0 * fy0).sqrt() if (fx0 != 0 or fy0 != 0) else Decimal(0)
        parameters.append(
            make_param_entry(
                path=f"ABAQUS\\{lc0['step']}\\shear_force_n",
                name="shear_force_n",
                value=decimal_str(shear_xy),
                unit="N",
                source_kind="abaqus_inp",
            )
        )
        parameters.append(
            make_param_entry(
                path=f"ABAQUS\\{lc0['step']}\\tensile_force_n",
                name="tensile_force_n",
                value=decimal_str(fz0.copy_abs()),
                unit="N",
                source_kind="abaqus_inp",
            )
        )

    bbox, geo_centroid = compute_bbox_and_centroid(node_pts)
    if not cg_points and geo_centroid is not None:
        cg_points.append(
            {
                "label": "ABAQUS_Mesh_Centroid_ESTIMATE",
                "coords": geo_centroid,
                "unit": "m",
                "source_kind": "abaqus_estimate",
            }
        )

    block_lines = [
        f"ABAQUS Input: {' '.join(heading_lines) or 'Model'} | NODES={len(nodes)}, "
        f"ELEMENTS={len(elements)}, CLOAD={len(cloads)}, DLOAD={len(dloads)}, MASS={len(masses)}"
    ]
    for lc in load_cases:
        block_lines.append(
            f"ABAQUS {lc['step']}: Resultant={lc['resultant_force_n']} N "
            f"F={lc['total_force_n']} M={lc['total_moment_n_m']}"
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
                block_kind="abaqus_inp",
            )
        )
        offset += len(line) + 1

    return {
        "format": "abaqus_inp",
        "heading": " ".join(heading_lines),
        "include_tree": include_tree,
        "composite_sections": composite_sections,
        "mesh": {
            "node_count": len(nodes),
            "element_count": len(elements),
            "nodes": list(nodes.values())[:2500],
            "elements": elements[:2500],
            "nsets": {k: len(v) for k, v in nsets.items()},
            "elsets": {k: len(v) for k, v in elsets.items()},
            "bbox": bbox,
        },
        "loads": {
            "cloads": cloads,
            "dloads": dloads,
            "boundaries": boundaries,
            "load_cases": load_cases,
        },
        "masses": masses,
        "cg_points": cg_points,
        "parameters": parameters,
        "blocks": blocks,
    }


_F06_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?")
_F06_RESULTANT_ROW_RE = re.compile(
    r"^\s*(?:0\s+)?(\d+)\s+([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)\s+"
    r"([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)\s+"
    r"([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)\s+"
    r"([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)\s+"
    r"([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)\s+"
    r"([-+]?\d\.\d+E[-+]\d+|[-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _extract_resultant_vectors(lines: list[str], section_marker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    compact_marker = re.sub(r"\s+", "", section_marker.upper())
    i = 0
    while i < len(lines):
        if compact_marker in re.sub(r"\s+", "", lines[i].upper()):
            for j in range(i + 1, min(i + 10, len(lines))):
                if "SUBCASE" in lines[j].upper() or "TOTAL" in lines[j].upper():
                    continue
                m = _F06_RESULTANT_ROW_RE.match(lines[j])
                if m:
                    vecs = [Decimal(m.group(k).replace("D", "E")) for k in range(2, 8)]
                    rows.append(
                        {
                            "subcase": m.group(1),
                            "force_n": [
                                decimal_str(vecs[0]),
                                decimal_str(vecs[1]),
                                decimal_str(vecs[2]),
                            ],
                            "resultant_force_n": decimal_str(
                                _decimal_hypot3(vecs[0], vecs[1], vecs[2])
                            ),
                            "moment_n_m": [
                                decimal_str(vecs[3]),
                                decimal_str(vecs[4]),
                                decimal_str(vecs[5]),
                            ],
                        }
                    )
                    break
        i += 1
    return rows


def _extract_eigenvalue_tables(
    lines: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Extract SOL 103 modal eigenvalues & SOL 105 linear buckling load factors from .f06."""
    modes: list[dict[str, str]] = []
    buckling_modes: list[dict[str, str]] = []
    eff_mass_by_mode: dict[str, str] = {}
    section_kind: str | None = None
    in_eff_mass = False
    is_sol_105_hint = any("SOL 105" in ln.upper() or "SOL105" in ln.upper() for ln in lines[:120])
    has_cycles_col = True

    for idx, line in enumerate(lines):
        compact = re.sub(r"\s+", "", line.upper())
        if "BUCKLINGEIGENVALUES" in compact or "REALEIGENVALUES" in compact:
            ctx_window = " ".join(lines[max(0, idx - 6) : idx + 3]).upper()
            is_buckling = (
                "BUCKLING" in ctx_window
                or "LOAD FACTOR" in ctx_window
                or (is_sol_105_hint and "CYCLES" not in ctx_window)
            )
            section_kind = "buckling" if is_buckling else "modal"
            has_cycles_col = not is_buckling
            in_eff_mass = False
            continue
        if "MODALEFFECTIVEMASSFRACTION" in compact:
            in_eff_mass = True
            section_kind = None
            continue

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("1") and "NASTRAN" in stripped.upper():
            section_kind = None
            in_eff_mass = False
            continue

        if section_kind is not None:
            up = stripped.upper()
            if "MODE" in up or "NO." in up or "LOAD FACTOR" in up:
                if "CYCLES" in up:
                    has_cycles_col = True
                continue
            m5 = re.match(
                r"^\s*(\d+)\s+(\d+)\s+([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s+"
                r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s+"
                r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
                line,
            )
            m3 = re.match(
                r"^\s*(\d+)\s+(\d+)\s+([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\b",
                line,
            )
            if section_kind == "buckling" and (m3 or m5):
                m_use = m5 or m3
                assert m_use is not None
                eig = Decimal(m_use.group(3).replace("D", "E"))
                buckling_modes.append(
                    {
                        "mode_no": m_use.group(1),
                        "eigenvalue": decimal_str(eig),
                        "buckling_ms": decimal_str(eig - Decimal("1")),
                    }
                )
            elif section_kind == "modal" and m5 and has_cycles_col:
                eig = Decimal(m5.group(3).replace("D", "E"))
                hz = Decimal(m5.group(5).replace("D", "E"))
                modes.append(
                    {
                        "mode_no": m5.group(1),
                        "eigenvalue": decimal_str(eig),
                        "cycles_hz": decimal_str(hz),
                    }
                )
            elif section_kind == "modal" and m3 and not m5:
                # 3-column eigenvalue table without frequency column indicates buckling factor
                eig = Decimal(m3.group(3).replace("D", "E"))
                buckling_modes.append(
                    {
                        "mode_no": m3.group(1),
                        "eigenvalue": decimal_str(eig),
                        "buckling_ms": decimal_str(eig - Decimal("1")),
                    }
                )
            elif modes or buckling_modes:
                section_kind = None

        elif in_eff_mass:
            if "MODE" in stripped.upper() or "TOTAL" in stripped.upper():
                if "TOTAL" in stripped.upper():
                    in_eff_mass = False
                continue
            m_ef = re.match(
                r"^\s*(\d+)\s+([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s+"
                r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s+"
                r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s+"
                r"([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
                line,
            )
            if m_ef:
                fracs = [Decimal(m_ef.group(k).replace("D", "E")).copy_abs() for k in (3, 4, 5)]
                eff_mass_by_mode[m_ef.group(1)] = decimal_str(max(fracs))

    for mode in modes:
        if mode["mode_no"] in eff_mass_by_mode:
            mode["effective_mass_frac"] = eff_mass_by_mode[mode["mode_no"]]
    return modes, buckling_modes


def _extract_modal_eigenvalues(lines: list[str]) -> list[dict[str, str]]:
    """Extract SOL 103 REAL EIGENVALUES and optional MODAL EFFECTIVE MASS FRACTION from .f06."""
    modes, _ = _extract_eigenvalue_tables(lines)
    return modes


def _extract_gpforce_freebody(lines: list[str]) -> dict[str, Any] | None:
    """Parse GRID POINT FORCE BALANCE sections and compute freebody equilibrium summary."""
    in_gpf = False
    grid_ids: set[str] = set()
    sum_fx = Decimal("0")
    sum_fy = Decimal("0")
    sum_fz = Decimal("0")
    sum_mx = Decimal("0")
    sum_my = Decimal("0")
    sum_mz = Decimal("0")
    max_nodal_res = Decimal("0")
    totals_rows = 0

    for line in lines:
        compact = re.sub(r"\s+", "", line.upper())
        if "GRIDPOINTFORCEBALANCE" in compact:
            in_gpf = True
            continue
        if not in_gpf:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith("1")
            and "NASTRAN" in stripped.upper()
            or "SUBCASE" in stripped.upper()
            and "POINT-ID" not in stripped.upper()
        ):
            in_gpf = False
            continue
        upper = stripped.upper()
        if "POINT-ID" in upper or "ELEMENT-ID" in upper:
            continue
        if "TOTALS" in upper:
            m_gid = re.match(r"^\s*(?:0\s+)?(\d+)\s+", line)
            if m_gid:
                grid_ids.add(m_gid.group(1))
            nums = _F06_FLOAT_RE.findall(line.split("TOTALS", 1)[-1])
            if len(nums) >= 6:
                vals = [Decimal(n.replace("D", "E")) for n in nums[:6]]
                sum_fx += vals[0]
                sum_fy += vals[1]
                sum_fz += vals[2]
                sum_mx += vals[3]
                sum_my += vals[4]
                sum_mz += vals[5]
                res_node = _decimal_hypot3(vals[0], vals[1], vals[2])
                if res_node > max_nodal_res:
                    max_nodal_res = res_node
                totals_rows += 1

    if totals_rows == 0:
        return None
    net_res = _decimal_hypot3(sum_fx, sum_fy, sum_fz)
    return {
        "grid_count": len(grid_ids) or totals_rows,
        "totals_rows": totals_rows,
        "net_force_n": [decimal_str(sum_fx), decimal_str(sum_fy), decimal_str(sum_fz)],
        "net_moment_n_m": [decimal_str(sum_mx), decimal_str(sum_my), decimal_str(sum_mz)],
        "net_resultant_n": decimal_str(net_res),
        "max_nodal_residual_n": decimal_str(max_nodal_res),
        "freebody_balanced": max_nodal_res <= Decimal("0.01"),
    }


def parse_nastran_f06(raw: bytes, source_hash: str) -> dict[str, Any]:
    """Deterministically extract OLOAD/SPCFORCE resultants and GPWG mass/CG from .f06."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    lines = text.splitlines()
    if not lines:
        raise IngestAbstain("empty_f06_file")

    oloads = _extract_resultant_vectors(lines, "OLOAD")
    spcforces = _extract_resultant_vectors(lines, "SPCFORCE")
    modal_eigenvalues, buckling_eigenvalues = _extract_eigenvalue_tables(lines)
    gpforce_freebody = _extract_gpforce_freebody(lines)

    gpwg_mass: Decimal | None = None
    gpwg_cg: list[str] | None = None
    epsilon_values: list[str] = []
    fatal_messages: list[str] = []
    warning_messages: list[str] = []

    for idx, line in enumerate(lines):
        upper = line.upper()
        if "USER FATAL MESSAGE" in upper or "SYSTEM FATAL MESSAGE" in upper:
            fatal_messages.append(line.strip()[:200])
        elif "USER WARNING MESSAGE" in upper:
            warning_messages.append(line.strip()[:200])
        elif "EPSILON" in upper:
            nums = _F06_FLOAT_RE.findall(line)
            if nums:
                epsilon_values.append(nums[-1].replace("D", "E"))
        elif "MASS AXIS SYSTEM" in upper or "DIRECTION" in upper and "MASS" in upper:
            # Parse X, Y, Z mass rows right below GPWG header if present
            coords: list[str] = []
            masses_found: list[Decimal] = []
            for j in range(idx + 1, min(idx + 6, len(lines))):
                row_u = lines[j].strip().upper()
                if row_u.startswith(("X ", "Y ", "Z ")):
                    nums = _F06_FLOAT_RE.findall(lines[j])
                    if len(nums) >= 4:
                        masses_found.append(Decimal(nums[0].replace("D", "E")))
                        axis_idx = {"X": 1, "Y": 2, "Z": 3}[row_u[0]]
                        if axis_idx < len(nums):
                            coords.append(decimal_str(Decimal(nums[axis_idx].replace("D", "E"))))
            if masses_found and gpwg_mass is None:
                gpwg_mass = masses_found[0]
            if len(coords) == 3 and gpwg_cg is None:
                gpwg_cg = coords
        elif "TOTAL MASS" in upper and gpwg_mass is None:
            nums = _F06_FLOAT_RE.findall(line)
            if nums:
                gpwg_mass = Decimal(nums[-1].replace("D", "E"))

    if (
        not oloads
        and not spcforces
        and gpwg_mass is None
        and not fatal_messages
        and not modal_eigenvalues
        and not buckling_eigenvalues
        and gpforce_freebody is None
    ):
        raise IngestAbstain("no_f06_engineering_results_found")

    equilibrium_checks: list[dict[str, Any]] = []
    if oloads and spcforces:
        for oload in oloads:
            match = next((s for s in spcforces if s["subcase"] == oload["subcase"]), spcforces[0])
            res_x = Decimal(oload["force_n"][0]) + Decimal(match["force_n"][0])
            res_y = Decimal(oload["force_n"][1]) + Decimal(match["force_n"][1])
            res_z = Decimal(oload["force_n"][2]) + Decimal(match["force_n"][2])
            imbalance = _decimal_hypot3(res_x, res_y, res_z)
            equilibrium_checks.append(
                {
                    "subcase": oload["subcase"],
                    "oload_resultant_n": oload["resultant_force_n"],
                    "spcforce_resultant_n": match["resultant_force_n"],
                    "residual_sum_n": decimal_str(imbalance),
                }
            )

    parameters: list[dict[str, Any]] = []
    cg_points: list[dict[str, Any]] = []
    if gpwg_mass is not None:
        parameters.append(
            make_param_entry(
                path="NASTRAN_F06\\GPWG\\mass_kg",
                name="mass_kg",
                value=decimal_str(gpwg_mass),
                unit="kg",
                source_kind="nastran_f06",
            )
        )
    if gpwg_cg is not None:
        cg_points.append(
            {
                "label": "NASTRAN_F06_GPWG_CG",
                "coords": gpwg_cg,
                "unit": "m",
                "source_kind": "nastran_f06",
            }
        )
        parameters.append(
            make_param_entry(
                path="NASTRAN_F06\\GPWG\\cg_x_m",
                name="cg_x_m",
                value=gpwg_cg[0],
                unit="m",
                source_kind="nastran_f06",
            )
        )
    if oloads:
        parameters.append(
            make_param_entry(
                path=f"NASTRAN_F06\\SUBCASE_{oloads[0]['subcase']}\\oload_resultant_n",
                name="thrust_n",
                value=oloads[0]["resultant_force_n"],
                unit="N",
                source_kind="nastran_f06",
            )
        )
    if spcforces:
        parameters.append(
            make_param_entry(
                path=f"NASTRAN_F06\\SUBCASE_{spcforces[0]['subcase']}\\spcforce_resultant_n",
                name="spc_reaction_n",
                value=spcforces[0]["resultant_force_n"],
                unit="N",
                source_kind="nastran_f06",
            )
        )

    block_lines = [
        f"NASTRAN F06 Output | OLOAD={len(oloads)}, SPCFORCE={len(spcforces)}, "
        f"FATAL={len(fatal_messages)}, WARNING={len(warning_messages)}"
    ]
    if gpwg_mass is not None:
        block_lines.append(f"GPWG Total Mass: {decimal_str(gpwg_mass)} kg")
    if equilibrium_checks:
        eq0 = equilibrium_checks[0]
        block_lines.append(
            f"Subcase {eq0['subcase']} OLOAD={eq0['oload_resultant_n']} N, "
            f"SPCFORCE={eq0['spcforce_resultant_n']} N, Residual={eq0['residual_sum_n']} N"
        )

    blocks: list[Block] = []
    offset = 0
    for ln in block_lines:
        blocks.append(
            Block(
                text=ln,
                span_start=offset,
                span_end=offset + len(ln),
                source_hash=source_hash,
                block_kind="nastran_f06",
            )
        )
        offset += len(ln) + 1

    crit_buckling: str | None = None
    buckling_ms_min: str | None = None
    if buckling_eigenvalues:
        pos_eigs = [
            Decimal(b["eigenvalue"])
            for b in buckling_eigenvalues
            if Decimal(b["eigenvalue"]) > Decimal("0")
        ]
        if pos_eigs:
            crit_val = min(pos_eigs)
        else:
            crit_val = min(Decimal(b["eigenvalue"]) for b in buckling_eigenvalues)
        crit_buckling = decimal_str(crit_val)
        buckling_ms_min = decimal_str(crit_val - Decimal("1"))

    return {
        "format": "nastran_f06",
        "oload_resultants": oloads,
        "spcforce_resultants": spcforces,
        "equilibrium_checks": equilibrium_checks,
        "modal_eigenvalues": modal_eigenvalues,
        "buckling_eigenvalues": buckling_eigenvalues,
        "critical_buckling_factor": crit_buckling,
        "buckling_ms_min": buckling_ms_min,
        "gpforce_freebody": gpforce_freebody,
        "gpwg_mass_kg": decimal_str(gpwg_mass) if gpwg_mass is not None else None,
        "cg_points": cg_points,
        "epsilon_values": epsilon_values,
        "fatal_errors": fatal_messages,
        "warnings": warning_messages,
        "parameters": parameters,
        "blocks": blocks,
    }
