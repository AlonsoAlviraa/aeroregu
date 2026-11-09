import hashlib
import json

import pytest
from evidence_domain.generate import (
    REQUIREMENT_IDS,
    build_requirements,
    render_aircraft,
    render_requirements,
    write_data_files,
)
from evidence_domain.names import ForbiddenNameError, assert_allowed
from evidence_kernel.schema import validate_instance


def test_aircraft_hash_is_stable() -> None:
    first = render_aircraft()
    second = render_aircraft()
    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()
    write_data_files()
    from evidence_domain.generate import data_dir

    assert (data_dir() / "sl-1.json").read_text(encoding="utf-8") == first
    document = json.loads(first)
    assert document["provenance"]["origin"] == "synthetic"
    assert document["provenance"]["seed"] == 20261103
    assert document["mass_kg"]["label"] == "ASSUMPTION"
    assert document["aircraft_id"] == "SL-1"
    validate_instance("provenance.schema.json", document["provenance"])


def test_requirements_are_unverified_without_a_file_hash() -> None:
    document = build_requirements()
    assert len(document["requirements"]) == 8
    assert [row["id"] for row in document["requirements"][:7]] == list(REQUIREMENT_IDS)
    assert document["requirements"][-1]["id"] == "SUBPART-C"
    assert document["requirements"][-1]["computable"] is False
    assert document["source_urls"][0].endswith("/139945/en")
    assert "easy-access-rules-small-category-vca" in document["source_urls"][1]
    assert document["source_file_hash"] == ""
    assert document["source_file_hash_label"] == "NOT_VERIFIED"
    for row in document["requirements"]:
        assert row["title"] is None
        assert row["title_label"] == "NOT_VERIFIED"
        validate_instance("requirement.schema.json", row)
    write_data_files()
    from evidence_domain.generate import data_dir

    assert (data_dir() / "requirements.json").read_text(encoding="utf-8") == render_requirements()


def test_real_aircraft_names_are_refused() -> None:
    with pytest.raises(ForbiddenNameError):
        assert_allowed("Joby")
    with pytest.raises(ForbiddenNameError):
        assert_allowed("notes", source_path=r"C:\work\AIRBUS\secret.txt")
