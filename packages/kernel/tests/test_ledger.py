import sqlite3
from pathlib import Path

import pytest
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import GENESIS, Ledger, LedgerError


def _envelope(result: dict | None = None, *, abstain: str | None = None) -> dict:
    return make_envelope(
        sources=[project_source("test", "https://aeroregu.local/test", "ASSUMPTION")],
        method_version="ledger-test@1.0.0",
        inputs={"marker": "alpha"},
        confidence="abstain" if abstain else "deterministic",
        result=result,
        abstain_reason=abstain,
    )


def _body(tenant: str, event_type: str, payload: dict, envelope: dict) -> dict:
    return {
        "event_type": event_type,
        "tenant_id": tenant,
        "actor_id": "author",
        "created_at": "2026-11-03T18:00:00Z",
        "payload": payload,
        "envelope": envelope,
    }


def test_append_and_verify(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    assert ledger.head_hash() == GENESIS
    first = ledger.append(
        _body("tenant-a", "calc", {"marker": "one"}, _envelope({"marker": "one"}))
    )
    second = ledger.append(
        _body("tenant-a", "calc", {"marker": "two"}, _envelope({"marker": "two"}))
    )
    assert first != second
    assert ledger.verify()
    assert ledger.head_hash() == second


def test_inputs_hash_is_stable() -> None:
    left = {"mass_kg": "800.000", "gravity_m_s2": "10.000"}
    right = {"gravity_m_s2": "10.000", "mass_kg": "800.000"}
    assert inputs_hash(left) == inputs_hash(right)
    assert inputs_hash(left) == inputs_hash(dict(left))


def test_update_and_delete_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.sqlite3"
    ledger = Ledger(path, "tenant-a")
    ledger.append(_body("tenant-a", "calc", {"marker": "one"}, _envelope({"marker": "one"})))
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE events SET body_json = '{}' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events WHERE seq = 1")
    conn.close()
    assert ledger.verify()


def test_tamper_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "a.sqlite3"
    ledger = Ledger(path, "tenant-a")
    ledger.append(_body("tenant-a", "calc", {"marker": "one"}, _envelope({"marker": "one"})))
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET body_json = '{\"tampered\":true}' WHERE seq = 1")
    conn.commit()
    conn.close()
    assert ledger.verify() is False


def test_tenants_are_isolated(tmp_path: Path) -> None:
    alpha = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    beta = Ledger(tmp_path / "b.sqlite3", "tenant-b")
    alpha.append(_body("tenant-a", "calc", {"marker": "a"}, _envelope({"marker": "a"})))
    beta.append(_body("tenant-b", "calc", {"marker": "b"}, _envelope({"marker": "b"})))
    alpha_hashes = {event["event_hash"] for event in alpha.events()}
    beta_hashes = {event["event_hash"] for event in beta.events()}
    assert alpha_hashes.isdisjoint(beta_hashes)
    with pytest.raises(LedgerError):
        alpha.append(_body("tenant-b", "calc", {"marker": "nope"}, _envelope({"marker": "nope"})))


def test_human_signoff_statement(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    target = ledger.append(
        _body("tenant-a", "calc", {"marker": "one"}, _envelope({"marker": "one"}))
    )
    signed = ledger.append(
        _body(
            "tenant-a",
            "human_signoff",
            {
                "actor_id": "author",
                "statement": "reviewed this event",
                "target_event_hash": target,
            },
            _envelope({"statement": "reviewed this event"}),
        )
    )
    assert ledger.verify()
    stored = ledger.events()[-1]
    assert stored["event_hash"] == signed
    assert stored["body"]["payload"]["statement"] == "reviewed this event"
    assert "compliant" not in stored["body"]["payload"]["statement"]


def test_signoff_rejects_compliant_word(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    target = ledger.append(
        _body("tenant-a", "calc", {"marker": "one"}, _envelope({"marker": "one"}))
    )
    with pytest.raises(LedgerError):
        ledger.append(
            _body(
                "tenant-a",
                "human_signoff",
                {
                    "actor_id": "author",
                    "statement": "reviewed this event and it is compliant",
                    "target_event_hash": target,
                },
                _envelope({"statement": "reviewed"}),
            )
        )


def test_abstain_rejects_an_integer_key_and_reason(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    with pytest.raises(LedgerError):
        ledger.append(
            _body(
                "tenant-a",
                "abstain",
                {"800": "missing_input"},
                _envelope(abstain="missing_input"),
            )
        )
    envelope = _envelope(abstain="missing_input")
    envelope["abstain"]["reason"] = "the load is 800 N"
    with pytest.raises(LedgerError):
        ledger.append(
            _body(
                "tenant-a",
                "abstain",
                {"reason": "missing_input"},
                envelope,
            )
        )


def test_abstain_rejects_an_integer_payload(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    with pytest.raises(LedgerError):
        ledger.append(
            _body(
                "tenant-a",
                "abstain",
                {"reason": "missing_input", "value": "800"},
                _envelope(abstain="missing_input"),
            )
        )


def test_abstain_rejects_numeric_payload(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    with pytest.raises(LedgerError):
        ledger.append(
            _body(
                "tenant-a",
                "abstain",
                {"reason": "missing_input", "value": "1.250"},
                _envelope(abstain="missing_input"),
            )
        )
    digest = ledger.append(
        _body(
            "tenant-a", "abstain", {"reason": "missing_input"}, _envelope(abstain="missing_input")
        )
    )
    assert digest
    assert "result" not in ledger.events()[-1]["body"]["envelope"]


def test_a_new_actor_salt_is_not_the_tenant_hash(tmp_path: Path) -> None:
    import hashlib

    ledger = Ledger(tmp_path / "a.sqlite3", "tenant-a")
    ledger.ensure_actor("author", "human", "author-local")
    other = Ledger(tmp_path / "b.sqlite3", "tenant-a")
    other.ensure_actor("author", "human", "author-local")
    predictable = hashlib.sha256(b"tenant-a:author").hexdigest()
    with sqlite3.connect(tmp_path / "a.sqlite3") as conn:
        salt_a = conn.execute("SELECT password_salt FROM actors").fetchone()[0]
    with sqlite3.connect(tmp_path / "b.sqlite3") as conn:
        salt_b = conn.execute("SELECT password_salt FROM actors").fetchone()[0]
    assert salt_a != predictable
    assert salt_b != predictable
    assert salt_a != salt_b
    assert ledger.check_password("author", "author-local")
    assert not ledger.check_password("author", "other-password")


def test_a_predictable_salt_is_replaced_when_the_password_matches(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "a.sqlite3"
    ledger = Ledger(path, "tenant-a")
    predictable = hashlib.sha256(b"tenant-a:author").hexdigest()
    digest = hashlib.pbkdf2_hmac(
        "sha256", b"author-local", predictable.encode("ascii"), 20_000
    ).hex()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO actors (actor_id, role, password_hash, password_salt) VALUES (?, ?, ?, ?)",
            ("author", "human", digest, predictable),
        )
    ledger.ensure_actor("author", "human", "author-local")
    with sqlite3.connect(path) as conn:
        salt = conn.execute("SELECT password_salt FROM actors").fetchone()[0]
    assert salt != predictable
    assert ledger.check_password("author", "author-local")


def test_ledger_releases_the_sqlite_file(tmp_path: Path) -> None:
    import shutil
    import tempfile

    folder = Path(tempfile.mkdtemp())
    ledger = Ledger(folder / "quotes.sqlite3", "bench")
    assert ledger.events() == []
    shutil.rmtree(folder)
