from __future__ import annotations

import json
from pathlib import Path

from evidence_calc.registry import run_method
from evidence_kernel.canonical import canonicalize

from evidence_domain.names import assert_allowed

GENERATOR_VERSION = "0.1.0"
SEED = 20261103
SC_VTOL_URL = "https://www.easa.europa.eu/en/downloads/139945/en"
EASY_ACCESS_URL = (
    "https://www.easa.europa.eu/en/document-library/easy-access-rules/"
    "easy-access-rules-small-category-vca"
)
REQUIREMENT_IDS = (
    "VTOL.2200",
    "VTOL.2205",
    "VTOL.2210",
    "VTOL.2215",
    "VTOL.2220",
    "VTOL.2225",
    "VTOL.2230",
)


def data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def build_aircraft(aircraft_id: str = "SL-1") -> dict:
    assert_allowed(aircraft_id)
    illustrative_inputs = {
        "mass_kg": "800.000",
        "gravity_m_s2": "9.810",
        "load_factor": "1.000",
        "altitude_m": "0.000",
        "cg_x_m": "0.000",
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": [True, True, True, True],
    }
    ran = run_method("rigid_body_point_mass", illustrative_inputs)
    document = {
        "aircraft_id": aircraft_id,
        "unit_count": 4,
        "provenance": {
            "origin": "synthetic",
            "author": "aeroregu",
            "generator_version": GENERATOR_VERSION,
            "seed": SEED,
            "statement": "This aircraft is invented. It is not a real type.",
            "label": "ASSUMPTION",
        },
        "mass_kg": {
            "min": "800.000",
            "mid": "900.000",
            "max": "1200.000",
            "label": "ASSUMPTION",
        },
        "cg_x_m": {"forward": "-0.200", "mid": "0.000", "aft": "0.200", "label": "ASSUMPTION"},
        "altitude_m": {
            "low": "0.000",
            "mid": "1500.000",
            "high": "3000.000",
            "label": "ASSUMPTION",
        },
        "load_factor": {
            "nominal": "1.000",
            "limit_negative": "-1.000",
            "limit_positive": "2.500",
            "label": "ASSUMPTION",
        },
        "illustrative_inputs": illustrative_inputs,
        "illustrative_load": {
            "method_version": ran["method_version"],
            "outputs": ran["outputs"],
            "label": "ASSUMPTION",
        },
    }
    assert_allowed(json.dumps(document))
    return document


def build_requirements() -> dict:
    rows = []
    for req_id in REQUIREMENT_IDS:
        rows.append(_row(req_id, computable=True, node_role="requirement"))
    rows.append(_row("SUBPART-C", computable=False, node_role="parent"))
    document = {
        "provenance": {
            "origin": "synthetic",
            "author": "aeroregu",
            "generator_version": GENERATOR_VERSION,
            "seed": SEED,
            "statement": (
                "Public identifiers are listed with official URLs. "
                "Paragraph text was not copied. The local source file was not hashed."
            ),
            "label": "NOT_VERIFIED",
        },
        "source_urls": [SC_VTOL_URL, EASY_ACCESS_URL],
        "source_file_hash": "",
        "source_file_hash_label": "NOT_VERIFIED",
        "requirements": rows,
    }
    return document


def render_aircraft() -> str:
    return canonicalize(build_aircraft()) + "\n"


def render_requirements() -> str:
    return canonicalize(build_requirements()) + "\n"


def write_data_files() -> None:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sl-1.json").write_text(render_aircraft(), encoding="utf-8")
    (folder / "requirements.json").write_text(render_requirements(), encoding="utf-8")


def _row(req_id: str, *, computable: bool, node_role: str) -> dict:
    return {
        "id": req_id,
        "title": None,
        "title_label": "NOT_VERIFIED",
        "source_url": SC_VTOL_URL,
        "source_file_hash": "",
        "source_file_hash_label": "NOT_VERIFIED",
        "computable": computable,
        "node_role": node_role,
        "provenance_note": "Title was not taken from a local file that this repo hashed.",
    }
