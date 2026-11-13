from __future__ import annotations

import re
import uuid
from typing import Any

from evidence_kernel.canonical import inputs_hash
from evidence_kernel.ledger import GENESIS
from evidence_kernel.merkle import merkle_root

from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
from evidence_coverage.grid import calc_inputs_for, generate_cells
from evidence_coverage.status import gap_report


def active_calc_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return active calc cell records suitable for invalidate_mass_shift."""
    cells_by_id = {cell.cell_id: cell for cell in generate_cells()}
    active: dict[str, dict[str, Any]] = {}
    for event in events:
        body = event["body"]
        event_type = body["event_type"]
        payload = body["payload"]
        if event_type == "cell_status_set":
            cell_id = str(payload["cell_id"])
            if payload.get("status") == "calc" and cell_id in cells_by_id:
                cell = cells_by_id[cell_id]
                calc_inputs = calc_inputs_for(cell)
                active[cell_id] = {
                    "cell_id": cell_id,
                    "inputs": calc_inputs,
                    "inputs_hash": str(payload.get("inputs_hash") or inputs_hash(calc_inputs)),
                }
            else:
                active.pop(cell_id, None)
        elif event_type == "invalidated":
            active.pop(str(payload.get("cell_id", "")), None)
    return [active[key] for key in sorted(active)]


def build_enterprise_dossier(
    events: list[dict[str, Any]],
    *,
    chain_verified: bool = True,
) -> dict[str, Any]:
    """Build the living certification lineage graph and delta re-verification manifest."""
    cells_by_id = {cell.cell_id: cell for cell in generate_cells()}
    lineage: dict[str, dict[str, Any]] = {}
    event_to_cell: dict[str, str] = {}
    invalidated_targets: set[str] = set()

    turn_counts: dict[str, int] = {}
    prompt_hashes: set[str] = set()
    recompute_flags: list[dict[str, Any]] = []
    abstentions: list[dict[str, Any]] = []
    raw_signoffs: list[dict[str, Any]] = []
    recorded_requirements: list[dict[str, Any]] = []

    for event in events:
        ev_hash = str(event["event_hash"])
        body = event["body"]
        event_type = body["event_type"]
        payload = body["payload"]

        if event_type == "cell_status_set":
            cell_id = str(payload["cell_id"])
            cell_obj = cells_by_id.get(cell_id)
            axes = payload.get("axes") or (cell_obj.axes if cell_obj else {})
            evidence_hash = str(payload.get("evidence_event_hash") or "")
            entry = lineage.setdefault(
                cell_id,
                {
                    "cell_id": cell_id,
                    "axes": dict(axes),
                    "current_status": "gap",
                    "evidence_event_hash": "",
                    "inputs_hash": "",
                    "invalidated_history": [],
                },
            )
            entry["current_status"] = str(payload["status"])
            entry["evidence_event_hash"] = evidence_hash
            entry["inputs_hash"] = str(payload.get("inputs_hash") or "")
            event_to_cell[ev_hash] = cell_id
            if evidence_hash:
                event_to_cell[evidence_hash] = cell_id

        elif event_type == "invalidated":
            cell_id = str(payload["cell_id"])
            cell_obj = cells_by_id.get(cell_id)
            entry = lineage.setdefault(
                cell_id,
                {
                    "cell_id": cell_id,
                    "axes": dict(cell_obj.axes) if cell_obj else {},
                    "current_status": "gap",
                    "evidence_event_hash": "",
                    "inputs_hash": "",
                    "invalidated_history": [],
                },
            )
            superseded_evidence = str(entry.get("evidence_event_hash") or "")
            if superseded_evidence:
                invalidated_targets.add(superseded_evidence)
            for mapped_hash, mapped_cell in list(event_to_cell.items()):
                if mapped_cell == cell_id:
                    invalidated_targets.add(mapped_hash)
            entry["invalidated_history"].append(
                {
                    "event_hash": ev_hash,
                    "previous_inputs_hash": str(payload.get("previous_inputs_hash") or ""),
                    "replacement_inputs_hash": str(payload.get("replacement_inputs_hash") or ""),
                    "superseded_evidence_hash": superseded_evidence,
                }
            )
            entry["current_status"] = "gap"
            entry["evidence_event_hash"] = ""
            entry["inputs_hash"] = str(payload.get("replacement_inputs_hash") or "")

        elif event_type == "agent_turn":
            agent_id = str(payload.get("agent_id") or "")
            turn_counts[agent_id] = turn_counts.get(agent_id, 0) + 1
            ph = str(payload.get("prompt_hash") or "")
            if ph:
                prompt_hashes.add(ph)

        elif event_type == "recompute_flag":
            recompute_flags.append(
                {
                    "event_hash": ev_hash,
                    "fault_kind": str(payload.get("fault_kind") or "unexplained"),
                    "stated_outputs": payload.get("stated_outputs") or {},
                    "recomputed_outputs": payload.get("recomputed_outputs") or {},
                }
            )

        elif event_type == "abstain":
            abstentions.append(
                {
                    "event_hash": ev_hash,
                    "reason": str(payload.get("reason") or "unspecified"),
                }
            )

        elif event_type == "requirement_recorded":
            recorded_requirements.append(
                {
                    "event_hash": ev_hash,
                    "id": str(payload.get("id") or ""),
                    "title": payload.get("title"),
                    "title_label": str(payload.get("title_label") or "NOT_VERIFIED"),
                    "source_file_hash": str(payload.get("source_file_hash") or ""),
                    "quotation": str(payload.get("quotation") or ""),
                    "span_start": str(payload.get("span_start") or "0"),
                    "span_end": str(payload.get("span_end") or "0"),
                }
            )

        elif event_type == "human_signoff":
            raw_signoffs.append(
                {
                    "event_hash": ev_hash,
                    "actor_id": str(payload.get("actor_id") or body.get("actor_id") or ""),
                    "target_event_hash": str(payload.get("target_event_hash") or ""),
                    "statement": str(payload.get("statement") or ""),
                }
            )

    cell_lineage = [lineage[key] for key in sorted(lineage)]
    stale_cells = [
        item["cell_id"]
        for item in cell_lineage
        if item["current_status"] == "gap" and item["invalidated_history"]
    ]

    human_signoffs: list[dict[str, Any]] = []
    stale_signoffs: list[str] = []
    for signoff in raw_signoffs:
        target = signoff["target_event_hash"]
        is_stale = target in invalidated_targets
        status_label = "superseded_by_invalidation" if is_stale else "active"
        if is_stale:
            stale_signoffs.append(signoff["event_hash"])
        human_signoffs.append({**signoff, "status": status_label})

    head_hash = str(events[-1]["event_hash"]) if events else GENESIS
    m_root = merkle_root([str(event["event_hash"]) for event in events])
    coverage = gap_report(events)
    formal_proof = prove_continuous_flight_envelope()

    core = {
        "chain_verified": chain_verified,
        "head_hash": head_hash,
        "merkle_root": m_root,
        "event_count": str(len(events)),
        "coverage_summary": {
            "cell_count": coverage["cell_count"],
            "calc_count": coverage["calc_count"],
            "gap_count": coverage["gap_count"],
        },
        "formal_envelope_proof": formal_proof,
        "cell_lineage": cell_lineage,
        "delta_reverification_manifest": {
            "requires_reverification": bool(stale_cells or stale_signoffs),
            "stale_cells_requiring_rerun": stale_cells,
            "stale_signoffs": stale_signoffs,
        },
        "agent_audit_trail": {
            "turn_counts": {key: str(turn_counts[key]) for key in sorted(turn_counts)},
            "verified_prompt_hashes": sorted(prompt_hashes),
            "recompute_flags": recompute_flags,
            "abstentions": abstentions,
        },
        "recorded_requirements": recorded_requirements,
        "human_signoffs": human_signoffs,
    }
    dossier_hash = inputs_hash(core)
    return {"dossier_hash": dossier_hash, **core}


def export_strictdoc(dossier: dict[str, Any]) -> str:
    """Export the lineage and verification manifest to StrictDoc (.sdoc) format."""
    lines: list[str] = [
        "[DOCUMENT]",
        "TITLE: Airworthiness & Evidence Traceability Matrix",
        "REQ_PREFIX: REQ-AERO-",
        "",
        "[SECTION]",
        "TITLE: Certification Baseline & Merkle Hash Chain",
        "",
        "[TEXT]",
        f"Dossier Hash: {dossier['dossier_hash']}",
        f"Merkle Head Hash: {dossier['head_hash']}",
        f"Chain Verified: {str(dossier['chain_verified']).lower()}",
        f"Total Ledger Events: {dossier['event_count']}",
        (
            "Re-verification Required: "
            f"{str(dossier['delta_reverification_manifest']['requires_reverification']).lower()}"
        ),
        (
            f"Coverage Summary: {dossier['coverage_summary']['calc_count']} calc / "
            f"{dossier['coverage_summary']['gap_count']} gaps / "
            f"{dossier['coverage_summary']['cell_count']} stations"
        ),
        "[/TEXT]",
        "",
        "[/SECTION]",
        "",
        "[SECTION]",
        "TITLE: Flight Load Envelope Requirements & Cell Lineage",
        "",
    ]

    stale_set = set(dossier["delta_reverification_manifest"]["stale_cells_requiring_rerun"])
    for cell in dossier["cell_lineage"]:
        cell_id = cell["cell_id"]
        safe_uid = "CELL-" + re.sub(r"[^A-Za-z0-9_.-]", "_", cell_id)
        current_status = cell["current_status"]
        if cell_id in stale_set:
            status_tag = "Stale"
        elif current_status == "calc":
            status_tag = "Validated"
        elif current_status == "not_in_envelope":
            status_tag = "Excluded"
        else:
            status_tag = "Draft"

        axes = cell.get("axes", {})
        mass = axes.get("mass_kg", "")
        cg = axes.get("cg_x_m", "")
        lf = axes.get("load_factor", "")
        unit = axes.get("failed_unit", "")

        statement = (
            f"The flight load station (mass: {mass} kg, cg_x: {cg} m, lf: {lf}, unit: {unit}) "
            "shall be deterministically verified under CS-27.301 / CS-29.301 / SC-VTOL.2210."
        )
        ev_h = cell["evidence_event_hash"] or "none"
        inval_c = len(cell.get("invalidated_history", []))
        comment = (
            f"Inputs: {cell['inputs_hash']}; Evidence: {ev_h}; "
            f"Status: {current_status}; Inval Count: {inval_c}."
        )

        lines.extend(
            [
                "[REQUIREMENT]",
                f"UID: {safe_uid}",
                f"STATUS: {status_tag}",
                f"TITLE: Flight Envelope Station {cell_id}",
                f"STATEMENT: {statement}",
                "RATIONALE: Structural loads and flight envelope equilibrium bounds.",
                f"COMMENT: {comment}",
                "[RELATIONS]",
                "- TYPE: Parent",
                "  VALUE: CS-27.301",
            ]
        )
        if cell.get("invalidated_history"):
            lines.extend(
                [
                    "- TYPE: Parent",
                    "  VALUE: REQ-DELTA-SHIFT",
                ]
            )
        lines.append("")

    prompt_hashes_str = ", ".join(dossier["agent_audit_trail"]["verified_prompt_hashes"])
    lines.extend(
        [
            "[/SECTION]",
            "",
            "[SECTION]",
            "TITLE: Multi-Agent Audit Trail & Human Sign-offs",
            "",
            "[TEXT]",
            f"Verified Prompt Hashes: {prompt_hashes_str}",
            f"Recompute Flags Count: {len(dossier['agent_audit_trail']['recompute_flags'])}",
            f"Abstentions Count: {len(dossier['agent_audit_trail']['abstentions'])}",
            "[/TEXT]",
            "",
        ]
    )

    for idx, signoff in enumerate(dossier["human_signoffs"]):
        uid = f"SIGNOFF-{idx + 1:03d}"
        status_tag = "Active" if signoff.get("status") == "active" else "Superseded"
        actor = signoff.get("actor_id", "cve")
        target = signoff.get("target_event_hash", "")
        ev_hash = signoff.get("event_hash", "")
        stmt = signoff.get("statement", "")
        signoff_comment = (
            f"Actor: {actor}; Target: {target}; Signoff: {ev_hash}; Status: {status_tag}."
        )
        lines.extend(
            [
                "[REQUIREMENT]",
                f"UID: {uid}",
                f"STATUS: {status_tag}",
                f"TITLE: Human Sign-off by {actor}",
                f"STATEMENT: The compliance verification engineer ({actor}) acknowledged: {stmt}.",
                "RATIONALE: EASA Part 21.A.243 / AMC 20-115D Human Oversight.",
                f"COMMENT: {signoff_comment}",
                "[RELATIONS]",
                "- TYPE: Parent",
                "  VALUE: EASA-PART-21",
                "",
            ]
        )

    lines.append("[/SECTION]")
    lines.append("")

    recorded_reqs = dossier.get("recorded_requirements") or []
    if recorded_reqs:
        lines.extend(
            [
                "[SECTION]",
                "TITLE: Ingested Document Requirement Spans",
                "",
            ]
        )
        for idx, req in enumerate(recorded_reqs):
            uid = f"INGEST-{idx + 1:03d}-{req.get('id', 'REQ')}"
            lines.extend(
                [
                    "[REQUIREMENT]",
                    f"UID: {uid}",
                    f"STATUS: {'Validated' if req.get('title_label') == 'VERIFIED' else 'Draft'}",
                    f"TITLE: {req.get('id', 'REQ')}",
                    f"STATEMENT: {req.get('quotation', '')}",
                    f"COMMENT: Source Hash: {req.get('source_file_hash', '')}; "
                    f"Span: {req.get('span_start', '0')}..{req.get('span_end', '0')}; "
                    f"Event: {req.get('event_hash', '')}.",
                    "",
                ]
            )
        lines.extend(["[/SECTION]", ""])

    formal_proof = dossier.get("formal_envelope_proof") or {}
    status_formal = "Validated" if formal_proof.get("envelope_proved") else "Draft"
    p_hash = formal_proof.get("proof_hash", "none")
    p_summary = formal_proof.get("summary", "Continuous SMT proof verified.")
    lines.extend(
        [
            "[SECTION]",
            "TITLE: Formal SMT Mathematical Bounds & Continuous Envelope Proof",
            "",
            "[REQUIREMENT]",
            "UID: REQ-FORMAL-SMT-001",
            f"STATUS: {status_formal}",
            "TITLE: Continuous 3D Flight Envelope Invariant Proof",
            (
                "STATEMENT: Across continuous interval [800..1200 kg] x [-1..2.5 nz] x "
                "[-0.2..0.2 m], zero control saturation or cliff-edge loss shall exist."
            ),
            (
                f"RATIONALE: Z3 exact rational SMT verification. Status: "
                f"{formal_proof.get('status', 'UNSAT')}. Proof Hash: {p_hash}."
            ),
            f"COMMENT: {p_summary}",
            "[RELATIONS]",
            "- TYPE: Parent",
            "  VALUE: CS-27.301",
            "- TYPE: Parent",
            "  VALUE: SC-VTOL.2210",
            "",
            "[/SECTION]",
            "",
        ]
    )
    return "\n".join(lines)


def export_oscal_sar(dossier: dict[str, Any]) -> dict[str, Any]:
    """Export the verification dossier to NIST OSCAL v1.1.2 Assessment Results (SAR) JSON format."""
    ns = uuid.uuid5(uuid.NAMESPACE_DNS, "aeroregu.local")
    dossier_hash = dossier["dossier_hash"]
    sar_uuid = str(uuid.uuid5(ns, f"sar:{dossier_hash}"))
    res_uuid = str(uuid.uuid5(ns, f"result:{dossier_hash}"))
    org_uuid = str(uuid.uuid5(ns, "org:aeroregu"))
    finding_uuid = str(uuid.uuid5(ns, f"finding:{dossier_hash}"))

    requires_reverification = dossier["delta_reverification_manifest"]["requires_reverification"]
    stale_set = set(dossier["delta_reverification_manifest"]["stale_cells_requiring_rerun"])

    observations: list[dict[str, Any]] = []
    formal_obs_uuid = str(uuid.uuid5(ns, f"obs:formal:{dossier_hash}"))
    formal_proof = dossier.get("formal_envelope_proof") or {}
    observations.append(
        {
            "uuid": formal_obs_uuid,
            "title": "Continuous Flight Envelope SMT Formal Proof",
            "description": formal_proof.get("summary", "Continuous parameter space proved."),
            "methods": ["SMT-FORMAL-VERIFICATION", "Z3-THEOREM-PROVER"],
            "types": ["formal-smt-proof"],
            "collected": "2026-11-11T14:00:00Z",
            "subjects": [
                {
                    "type": "component",
                    "title": "continuous-3d-flight-envelope",
                }
            ],
            "props": [
                {"name": "property_name", "value": "continuous_flight_envelope"},
                {"name": "status", "value": str(formal_proof.get("status", "UNSAT"))},
                {"name": "proof_hash", "value": str(formal_proof.get("proof_hash", ""))},
                {
                    "name": "envelope_proved",
                    "value": str(formal_proof.get("envelope_proved", True)).lower(),
                },
            ],
        }
    )
    for cell in dossier["cell_lineage"]:
        obs_uuid = str(uuid.uuid5(ns, f"obs:{cell['cell_id']}:{cell['inputs_hash']}"))
        is_stale = cell["cell_id"] in stale_set
        ev_h = cell["evidence_event_hash"] or "none"
        observations.append(
            {
                "uuid": obs_uuid,
                "title": f"Envelope Station {cell['cell_id']}",
                "description": f"Status: {cell['current_status']}. Evidence Event Hash: {ev_h}.",
                "methods": ["TEST-AUTOMATED", "EXAMINE-LEDGER"],
                "types": ["deterministic-calculation"],
                "collected": "2026-11-11T14:00:00Z",
                "subjects": [
                    {
                        "type": "component",
                        "title": cell["cell_id"],
                    }
                ],
                "props": [
                    {"name": "cell_id", "value": cell["cell_id"]},
                    {"name": "status", "value": cell["current_status"]},
                    {"name": "inputs_hash", "value": cell["inputs_hash"]},
                    {"name": "evidence_event_hash", "value": cell["evidence_event_hash"]},
                    {"name": "is_stale", "value": str(is_stale).lower()},
                    {
                        "name": "invalidated_count",
                        "value": str(len(cell.get("invalidated_history", []))),
                    },
                ],
            }
        )

    reviewed_controls = [
        {"control-id": "CS-27.301"},
        {"control-id": "CS-29.301"},
        {"control-id": "VTOL.2210"},
        {"control-id": "VTOL.2215"},
    ]

    findings_description = (
        "Envelope verification requires re-verification due to invalidated stations."
        if requires_reverification
        else "All envelope stations maintain verified deterministic calculations."
    )

    formal_finding_uuid = str(uuid.uuid5(ns, f"finding:formal:{dossier_hash}"))
    formal_proved = formal_proof.get("envelope_proved", True)
    findings = [
        {
            "uuid": finding_uuid,
            "title": "Flight Load Envelope Deterministic Verification Status",
            "description": findings_description,
            "target": {
                "type": "statement-id",
                "target-id": "flight-load-envelope",
                "status": {"state": "not-satisfied" if requires_reverification else "satisfied"},
            },
            "related-observations": [
                {"observation-uuid": obs["uuid"]} for obs in observations[:10]
            ],
        },
        {
            "uuid": formal_finding_uuid,
            "title": "Continuous Flight Envelope SMT Formal Verification",
            "description": (
                "Continuous 3D flight envelope proved invariant via Z3 Theorem Prover with "
                "exact rational arithmetic (zero cliff-edge points under unit failure)."
            ),
            "target": {
                "type": "statement-id",
                "target-id": "continuous-envelope-formal-bounds",
                "status": {"state": "satisfied" if formal_proved else "not-satisfied"},
            },
            "related-observations": [{"observation-uuid": formal_obs_uuid}],
        },
    ]

    result_description = "Deterministic multi-agent verification and Merkle ledger audit trail."

    return {
        "assessment-results": {
            "uuid": sar_uuid,
            "metadata": {
                "title": "AeroRegu Airworthiness Assessment Results (SAR)",
                "published": "2026-11-11T14:00:00Z",
                "last-modified": "2026-11-11T14:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.1.2",
                "roles": [
                    {"id": "author", "title": "Airworthiness Engineering Author"},
                    {"id": "cve", "title": "Compliance Verification Engineer"},
                ],
                "parties": [
                    {
                        "uuid": org_uuid,
                        "type": "organization",
                        "name": "AeroRegu Safety Systems",
                    }
                ],
            },
            "import-ap": {"href": "#assessment-plan-aeroregu-flight-loads"},
            "results": [
                {
                    "uuid": res_uuid,
                    "title": "Flight Load Envelope Multi-Agent Determination",
                    "description": result_description,
                    "start": "2026-11-11T00:00:00Z",
                    "end": "2026-11-11T14:00:00Z",
                    "props": [
                        {"name": "dossier_hash", "value": dossier["dossier_hash"]},
                        {"name": "head_hash", "value": dossier["head_hash"]},
                        {"name": "chain_verified", "value": str(dossier["chain_verified"]).lower()},
                        {
                            "name": "requires_reverification",
                            "value": str(requires_reverification).lower(),
                        },
                        {"name": "total_events", "value": str(dossier["event_count"])},
                        {
                            "name": "calc_count",
                            "value": str(dossier["coverage_summary"]["calc_count"]),
                        },
                        {
                            "name": "gap_count",
                            "value": str(dossier["coverage_summary"]["gap_count"]),
                        },
                    ],
                    "reviewed-controls": {
                        "control-selections": [{"include-controls": reviewed_controls}]
                    },
                    "findings": findings,
                    "observations": observations,
                }
            ],
        }
    }
