"""Write a CycloneDX 1.5 SBOM from uv.lock. Not a vulnerability scan."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    components = []
    for package in lock.get("package", []):
        components.append(
            {
                "type": "library",
                "name": package["name"],
                "version": package.get("version", "0"),
            }
        )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": components,
    }
    (root / "sbom.cdx.json").write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(components)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
