"""Score this repo's canonical JSON against published JCS vectors.

The vectors are Anders Rundgren's testdata for RFC 8785, Apache-2.0.
Files that contain a JSON number with a fraction are not scored: this
canonicalizer rejects floats. The report names files only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence_kernel.canonical import canonicalize

from evidence_eval.external_public import file_sha256

JCS_SHA256 = {
    "input/arrays.json": "e503b6d71d1afa595b1c74b1016445c944cd89f90418066b23de1aeda7d17563",
    "input/french.json": "03676a951cd8753ac62589f72eb2105cc782c33425418cfe1d517c111f6e5d5a",
    "input/structures.json": "d66893805be1784116af50af3110d08766c70a6b4aad93374723f72346e7aaa6",
    "input/unicode.json": "4621864e014d4a805a563f55b9ea20aba4a2d2dc09c7394f625496998c00702c",
    "input/values.json": "c4a041b503d6bc236036ef44db4dac499272f60fc22c40dc3b7a54870ba6f1c3",
    "input/weird.json": "a3a905266bd4a49a969274ea69baa14ee0c4af0ead926d6fa2b7612b4af75387",
    "output/arrays.json": "099601b171cafed97c333f8878d68e7f8c8f795412adb34b2fdcf0e7c7beac42",
    "output/french.json": "d99d0ebdcb0033cb858cfa830ae46bc0fb3309413b271f1da828c89901a27ed5",
    "output/structures.json": "605f65004ec2db7692522a0852c22f1c989e036d547e88963d1a3143cf3195d5",
    "output/unicode.json": "0d99aad92a125196ff887876643fd3206786a84ddce2cee52ba4ad256d2381d3",
    "output/values.json": "2d5e01a318d0f0879ab568c4be289c8b1f64ef8921a53c6277d5e069978baacb",
    "output/weird.json": "6af595a9aa80110b964b4de3f82a05fa6ae7423005019bacfa2620dddc4e94d1",
    "outhex/arrays.txt": "e306733ca0c4da9595ebde73ec072c295f0f9ef0ea4aafc4d267d4a04988ce51",
    "outhex/french.txt": "f9b3bfd02f4edb3d0a490703153d836db5ef0a2090a9d3357f8c3797e12d4043",
    "outhex/structures.txt": "063ee2bc6fa3f93b2a131841315f5c6bf0ea7488cc128ed50725cabf5592627b",
    "outhex/unicode.txt": "0471fea1ee0464e435a52510d2c187b216961a5e7e2665402ea9cb1cd04109ca",
    "outhex/values.txt": "b8b802e82c7bead71a7841e27fce6458854eb72ffd0eaa51474dacdfbdf3ab64",
    "outhex/weird.txt": "1061953c7129537722f9abd9de321c787120489d09f34ba58065bd77ba9a84b6",
}


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_float(item) for item in value)
    return False


def score_jcs(folder: Path, *, check_pins: bool = True) -> dict[str, Any]:
    if check_pins:
        for relative, expected in JCS_SHA256.items():
            actual = file_sha256(folder / relative)
            if actual != expected:
                raise ValueError(f"{relative} hash does not match the pin")
    matched: list[str] = []
    skipped: list[str] = []
    mismatched: list[str] = []
    byte_matched: list[str] = []
    byte_mismatched: list[str] = []
    for path in sorted((folder / "input").glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if _has_float(loaded):
            skipped.append(path.name)
            continue
        expected = (folder / "output" / path.name).read_text(encoding="utf-8")
        got = canonicalize(loaded)
        if got == expected:
            matched.append(path.name)
        else:
            mismatched.append(path.name)
        image = _outhex_bytes(folder / "outhex" / f"{path.stem}.txt")
        if got.encode("utf-8") == image:
            byte_matched.append(path.name)
        else:
            byte_mismatched.append(path.name)
    return {
        "dataset": "cyberphone/json-canonicalization testdata",
        "spec": "RFC 8785",
        "license": "Apache-2.0",
        "matched": matched,
        "byte_matched": byte_matched,
        "byte_mismatched": byte_mismatched,
        "float_skipped": skipped,
        "mismatched": mismatched,
        "label": "ESTIMATE",
        "note": (
            "A file with a fractional JSON number is skipped. This canonicalizer "
            "rejects floats. byte_matched means the UTF-8 bytes equal the published "
            "outhex image. The ledger hashes those bytes."
        ),
    }


def _outhex_bytes(path: Path) -> bytes:
    return bytes(int(part, 16) for part in path.read_text(encoding="utf-8").split())
