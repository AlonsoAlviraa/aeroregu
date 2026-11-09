from pathlib import Path

from evidence_eval.detect import assess
from evidence_eval.quarantine import duplicate_citation_artifact, quarantine_status


def test_duplicate_citation_is_not_detected() -> None:
    verdict = assess(duplicate_citation_artifact())["verdict"]
    assert verdict == "clean"
    source = Path(__file__).resolve().parents[1] / "src" / "evidence_eval" / "detect.py"
    assert "duplicate_citation" not in source.read_text(encoding="utf-8")
    status = quarantine_status()
    assert status["detected"] is False
    assert status["verdict"] == "clean"
    assert status["system_verdict"] == "abstain"
    assert status["queue"] == "human_engineer"
    assert status["event_type"] == "abstain"
    assert status["protocol_abstain"] is True
    assert status["abstention_matches_gold"] is False
    assert status["event_hash"] is not None
    assert len(status["event_hash"]) == 64
    assert status["recall"] == "0/1"
    assert status["recall_ci95"]["method"] == "wilson"
    assert status["challenger_reason_ignored"] is True
