from __future__ import annotations

FORBIDDEN_NAMES = (
    "airbus",
    "vahana",
    "lilium",
    "joby",
    "volocopter",
    "cityairbus",
    "ehang",
    "archer",
    "wisk",
    "pipistrel",
    "autoflight",
    "skydrive",
    "volocity",
    "cityhawk",
)


class ForbiddenNameError(ValueError):
    pass


def assert_allowed(text: str, source_path: str | None = None) -> None:
    if source_path and "AIRBUS" in source_path.replace("/", "\\").upper():
        raise ForbiddenNameError("refusing an employer workspace path")
    lowered = text.lower()
    for name in FORBIDDEN_NAMES:
        if name in lowered:
            raise ForbiddenNameError(f"refusing a real-world name: {name}")
