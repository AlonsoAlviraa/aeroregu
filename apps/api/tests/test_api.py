import io
import json
import zipfile

import pytest
from evidence_api.__main__ import main
from evidence_api.app import create_app
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import verify_chain_document
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    return TestClient(create_app())


def _login(client: TestClient, actor: str = "author") -> None:
    response = client.post(
        "/auth/login", json={"actor_id": actor, "password": f"{actor}-local"}
    )
    assert response.status_code == 200


def test_storyboard_path(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    health = client.get("/health").json()
    assert health["result"]["gateway"] == "fixture"
    requirements = client.get("/requirements").json()["result"]["requirements"]
    assert len(requirements) == 8
    assert requirements[0]["source_file_hash_label"] == "NOT_VERIFIED"
    aircraft = client.get("/aircraft").json()["result"]
    assert aircraft["provenance"]["origin"] == "synthetic"
    assert client.post("/export/zip").status_code == 401
    assert client.post("/calc/run", json={"example": "first_cell"}).status_code == 401
    _login(client)
    first = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    second = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    assert first.status_code == 200
    assert first.json()["inputs_hash"] == second.json()["inputs_hash"]
    assert first.json()["confidence"] == "deterministic"
    gaps = client.get("/coverage/gaps").json()["result"]
    assert gaps["cell_count"] == "135"
    assert int(gaps["calc_count"]) >= 1
    assert int(gaps["gap_count"]) >= 1
    unit = client.post("/notes/check", json={"example": "unit_scale"}).json()
    assert unit["result"]["flag"] == "unit_scale"
    missing = client.post("/notes/check", json={"example": "missing_input"}).json()
    assert missing["confidence"] == "abstain"
    assert "result" not in missing
    page = client.get("/").text
    assert "This tool assists a human reviewer. It does not determine compliance." in page
    assert "compliant" not in page.lower()
    assert "100" not in page
    archive = client.post("/export/zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        chain = json.loads(bundle.read("chain.json"))
        readme = bundle.read("README.txt").decode()
    assert verify_chain_document(chain)
    assert "compliant" not in readme.lower()
    assert "evidence_kernel verify" in readme
    login = client.post("/auth/login", json={"actor_id": "reviewer", "password": "reviewer-local"})
    assert login.status_code == 200
    target = chain[-1]["event_hash"]
    signoff = {
        "event_type": "human_signoff",
        "tenant_id": "demo",
        "actor_id": "reviewer",
        "created_at": "2026-11-03T18:05:00Z",
        "payload": {
            "actor_id": "reviewer",
            "statement": "reviewed this event",
            "target_event_hash": target,
        },
        "envelope": make_envelope(
            sources=[
                project_source("reviewer", "https://aeroregu.local/reviewer", "ASSUMPTION")
            ],
            method_version="human_signoff@1.0.0",
            inputs={"target_event_hash": target},
            confidence="quoted",
            result={"statement": "reviewed this event"},
        ),
    }
    recorded = client.post("/ledger/append", json=signoff)
    assert recorded.status_code == 200
    again = client.post("/export/zip")
    with zipfile.ZipFile(io.BytesIO(again.content)) as bundle:
        signed = json.loads(bundle.read("chain.json"))
    assert verify_chain_document(signed)
    assert signed[-1]["body"]["payload"]["statement"] == "reviewed this event"


def test_the_demo_process_refuses_a_short_session_secret(monkeypatch) -> None:
    monkeypatch.delenv("EVIDENCE_SESSION_SECRET", raising=False)
    with pytest.raises(SystemExit):
        main()


def test_the_demo_process_binds_the_loopback_interface(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "loopback-bind-check-secret")
    captured: dict[str, str] = {}

    def fake_run(*_args: object, **kwargs: object) -> None:
        captured["host"] = str(kwargs["host"])

    monkeypatch.setattr("evidence_api.__main__.uvicorn.run", fake_run)
    main()
    assert captured["host"] == "127.0.0.1"


def _chain_length() -> int:
    from evidence_api.app import open_ledger

    return len(open_ledger().events())


def _record_body() -> dict:
    from evidence_coverage.grid import calc_inputs_for, generate_cells

    return {
        "method_id": "rigid_body_point_mass",
        "inputs": calc_inputs_for(generate_cells()[0]),
        "record": True,
        "created_at": "2026-11-03T18:00:00Z",
    }


def test_recorded_calc_without_a_session_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 401
    assert _chain_length() == before


def test_recorded_calc_with_a_bad_cookie_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.cookies.set("el_session", "author.not-valid")
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 401
    assert _chain_length() == before


def test_first_cell_without_a_session_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    before = _chain_length()
    response = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    assert response.status_code == 401
    assert _chain_length() == before


def test_calc_that_does_not_record_stays_open(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    body = _record_body()
    del body["record"]
    before = _chain_length()
    response = client.post("/calc/run", json=body)
    assert response.status_code == 200
    assert response.json()["confidence"] == "deterministic"
    assert _chain_length() == before


def test_recorded_calc_with_the_session_appends(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 200
    assert _chain_length() == before + 1


def test_export_without_a_session_is_not_a_zip(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post("/export/zip")
    assert response.status_code == 401
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(response.content))


def test_export_with_a_bad_cookie_is_not_a_zip(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.cookies.set("el_session", "author.not-valid")
    response = client.post("/export/zip")
    assert response.status_code == 401
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(response.content))


def test_supervisor_refuter_hit(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/supervisor/run", json={"scenario": "refuter_hit"}).status_code == 401
    _login(client)
    response = client.post(
        "/supervisor/run",
        json={"scenario": "refuter_hit", "created_at": "2026-11-03T18:00:00Z"},
    )
    body = response.json()
    assert body["confidence"] == "abstain"
    assert body["abstain"]["reason"] == "refuter_hit"
    assert "result" not in body
