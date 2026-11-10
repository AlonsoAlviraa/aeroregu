import re
from pathlib import Path

from evidence_kernel.paths import repo_root

_LINK = re.compile(r"\[\[([^\]|#]+)")


def _vault() -> Path:
    return repo_root().parent / "regulacion" / "_vault-read" / "obsidian-regulacion"


def _targets(text: str) -> list[str]:
    visible: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        visible.extend(match.strip() for match in _LINK.findall(line))
    return visible


def test_every_vault_note_is_named_in_the_index_and_every_link_resolves() -> None:
    root = _vault()
    notes = list(root.rglob("*.md"))
    stems = {path.stem for path in notes}
    index = (root / "00-Indice.md").read_text(encoding="utf-8")
    missing = sorted(stem for stem in stems if stem not in index)
    broken: list[str] = []
    for path in notes:
        for target in _targets(path.read_text(encoding="utf-8")):
            if target not in stems:
                broken.append(f"{path.relative_to(root).as_posix()} -> {target}")
    assert missing == []
    assert broken == []
