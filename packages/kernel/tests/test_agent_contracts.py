import pytest
from evidence_kernel.contracts import (
    ChallengerOutput,
    ExtractorOutput,
    JudgeInput,
    ScribeOutput,
    SpanQuote,
)
from evidence_kernel.disagreement import decide, enqueue
from evidence_kernel.ledger import Ledger
from pydantic import ValidationError


def _extractor() -> ExtractorOutput:
    return ExtractorOutput(
        fields=[
            SpanQuote(
                name="mass",
                value_text="800.000",
                unit_text="kg",
                span_start=0,
                span_end=7,
            )
        ],
        clause_ids=["REQ.1"],
        assumptions=[],
    )


def test_judge_rejects_reasoning() -> None:
    with pytest.raises(ValidationError):
        JudgeInput.model_validate(
            {"case_id": "a", "verdict": "clean", "gold_label": "clean", "reasoning": "because"}
        )


def test_scribe_requires_a_ledger_hash() -> None:
    with pytest.raises(ValidationError):
        ScribeOutput.model_validate(
            {"sentences": [{"text": "See the record.", "ledger_event_hash": "not-a-hash"}]}
        )


def test_disagreement_goes_to_the_human_queue(tmp_path) -> None:
    challenger = ChallengerOutput(attack="hit", reason="span", evidence_span="800.000")
    assert decide(_extractor(), challenger) == "human_queue"
    ledger = Ledger(tmp_path / "tenant.sqlite3", "demo")
    digest = enqueue(
        ledger,
        tenant_id="demo",
        actor_id="orchestrator",
        created_at="2026-11-03T18:00:00Z",
        reason="agent_disagreement",
    )
    assert len(digest) == 64
    rows = ledger.events()
    body = rows[-1]["body"]
    assert body["event_type"] == "abstain"
    assert body["payload"]["queue"] == "human_engineer"


def test_agreement_does_not_queue() -> None:
    challenger = ChallengerOutput(attack="miss", reason="none", evidence_span="")
    assert decide(_extractor(), challenger) == "continue"


def test_low_confidence_goes_to_the_human_queue() -> None:
    agreed = ChallengerOutput(attack="miss", reason="none", evidence_span="")
    low_extractor = _extractor().model_copy(update={"confidence": "low"})
    low_challenger = agreed.model_copy(update={"confidence": "low"})
    assert decide(low_extractor, agreed) == "human_queue"
    assert decide(_extractor(), low_challenger) == "human_queue"
