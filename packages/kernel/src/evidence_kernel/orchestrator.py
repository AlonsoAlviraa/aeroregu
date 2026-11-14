"""Deterministic ledger writer.

Specialist agents do not import this module. Product code records an event
by calling record. The ledger class remains the storage engine.
"""

from __future__ import annotations

from typing import Any

from evidence_kernel.ledger import Ledger


def record(ledger: Ledger, body: dict[str, Any]) -> str:
    return ledger.append(body)


def record_many(ledger: Ledger, bodies: list[dict[str, Any]]) -> list[str]:
    return ledger.append_many(bodies)
