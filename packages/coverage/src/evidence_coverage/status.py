from __future__ import annotations

from typing import Any

from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

from evidence_coverage.grid import Cell, calc_inputs_for, generate_cells, plus_five_percent


class StatusError(PermissionError):
    pass


def gap_report(events: list[dict[str, Any]], cells: list[Cell] | None = None) -> dict[str, Any]:
    chosen = cells or generate_cells()
    status = _latest_status(events)
    gaps = [cell.cell_id for cell in chosen if status.get(cell.cell_id, "gap") == "gap"]
    calc_cells = [cell.cell_id for cell in chosen if status.get(cell.cell_id) == "calc"]
    excluded = [cell.cell_id for cell in chosen if status.get(cell.cell_id) == "not_in_envelope"]
    justified = [
        cell.cell_id for cell in chosen if status.get(cell.cell_id) == "justified_not_critical"
    ]
    return {
        "cell_count": str(len(chosen)),
        "gap_count": str(len(gaps)),
        "calc_count": str(len(calc_cells)),
        "gaps": gaps,
        "calc_cells": calc_cells,
        "not_in_envelope": excluded,
        "justified_not_critical": justified,
    }


def set_cell_status(
    ledger: Ledger,
    *,
    cell: Cell,
    status: str,
    actor_id: str,
    actor_role: str,
    created_at: str,
    evidence_event_hash: str = "",
) -> str:
    if status == "not_in_envelope" and actor_role != "human":
        raise StatusError("only a human actor can set not_in_envelope")
    if status == "justified_not_critical" and actor_role != "human":
        raise StatusError("only a human actor can set justified_not_critical")
    calc_inputs = calc_inputs_for(cell)
    digest = inputs_hash(calc_inputs)
    payload = {
        "cell_id": cell.cell_id,
        "status": status,
        "inputs_hash": digest,
        "actor_role": actor_role,
        "evidence_event_hash": evidence_event_hash,
        "axes": cell.axes,
    }
    envelope = make_envelope(
        sources=[
            project_source(
                "coverage",
                "https://aeroregu.local/coverage",
                "ASSUMPTION",
            )
        ],
        method_version="coverage_grid@1.0.0",
        inputs=calc_inputs,
        confidence="deterministic",
        result={"cell_id": cell.cell_id, "status": status, "inputs_hash": digest},
    )
    return record(
        ledger,
        {
            "event_type": "cell_status_set",
            "tenant_id": ledger.tenant_id,
            "actor_id": actor_id,
            "created_at": created_at,
            "payload": payload,
            "envelope": envelope,
        },
    )


def invalidate_mass_shift(
    ledger: Ledger,
    records: list[dict[str, Any]],
    *,
    actor_id: str,
    created_at: str,
) -> list[str]:
    written: list[str] = []
    for row in records:
        shifted_inputs = dict(row["inputs"])
        shifted_inputs["mass_kg"] = plus_five_percent(str(row["inputs"]["mass_kg"]))
        new_hash = inputs_hash(shifted_inputs)
        old_hash = str(row["inputs_hash"])
        if new_hash == old_hash:
            continue
        envelope = make_envelope(
            sources=[
                project_source(
                    "coverage",
                    "https://aeroregu.local/coverage",
                    "ASSUMPTION",
                )
            ],
            method_version="coverage_grid@1.0.0",
            inputs={"cell_id": row["cell_id"], "previous_inputs_hash": old_hash},
            confidence="deterministic",
            result={"cell_id": row["cell_id"], "status": "invalidated"},
        )
        written.append(
            record(
                ledger,
                {
                    "event_type": "invalidated",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "cell_id": row["cell_id"],
                        "previous_inputs_hash": old_hash,
                        "replacement_inputs_hash": new_hash,
                    },
                    "envelope": envelope,
                },
            )
        )
    return written


def _latest_status(events: list[dict[str, Any]]) -> dict[str, str]:
    status: dict[str, str] = {}
    for event in events:
        body = event["body"]
        if body["event_type"] == "cell_status_set":
            status[body["payload"]["cell_id"]] = body["payload"]["status"]
        elif body["event_type"] == "invalidated":
            status[body["payload"]["cell_id"]] = "gap"
    return status
