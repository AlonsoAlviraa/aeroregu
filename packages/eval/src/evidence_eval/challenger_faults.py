"""Seeded faults proposed by the challenger.

The checker must not learn these faults in the same change that adds them.
The proposal reason is not a verdict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_kernel.contracts import ChallengerOutput

from evidence_eval.faults import clean_artifact
from evidence_eval.generate import _bolt


def propose_duplicate_citation() -> dict[str, Any]:
    artifact = clean_artifact("bolt_screen", _bolt(Decimal("3000")))
    artifact["citation_requirement_ids"] = ["VTOL.2210", "VTOL.2215"]
    proposal = ChallengerOutput(
        attack="hit",
        reason="duplicate_citation",
        evidence_span="VTOL.2210",
    )
    return {"artifact": artifact, "proposal": proposal}
