from pathlib import Path

from evidence_kernel.paths import repo_root

REQUIRED = (
    "This tool assists a human reviewer. It does not determine compliance.",
    "SL-1",
    "sintético",
    "rigid_body_point_mass@1.0.0",
    "7848.000",
    "58382e0520df8fc774e878c77112b0f1b8b3914f159daedf546907dfdd62def4",
    "m800.000-cg-0.200-lf1.000-unone",
    "m800.000-cg-0.200-lf1.000-u0",
    "gap",
    "unit_scale",
    "Sin resultado",
    "reviewed this event",
)
FORBIDDEN = (
    "DO-330",
    "tool qualification level",
    "7000/7000",
)


def test_caption_source_covers_the_demo_and_makes_no_certification_claim() -> None:
    text = (repo_root() / "docs" / "demo" / "shorts" / "frames.html").read_text(encoding="utf-8")
    missing = [line for line in REQUIRED if line not in text]
    present = [line for line in FORBIDDEN if line in text]
    assert missing == []
    assert present == []
