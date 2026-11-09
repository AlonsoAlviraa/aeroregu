import re
from pathlib import Path


def test_calc_modules_do_not_use_float() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "evidence_calc"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "float" not in text
        stripped = re.sub(r'"""[\s\S]*?"""', "", text)
        stripped = re.sub(r"'[^']*'", "''", stripped)
        stripped = re.sub(r'"[^"]*"', '""', stripped)
        stripped = re.sub(r"#.*", "", stripped)
        assert re.search(r"\b\d+\.\d+\b", stripped) is None
