import importlib.util
from pathlib import Path


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_kernel_denylist_and_no_domain_import() -> None:
    root = Path(__file__).resolve().parents[1]
    denylist = _load(root / "tools" / "security" / "denylist_kernel.py", "denylist_kernel")
    assert denylist.scan_kernel(root) == []
    kernel = root / "packages" / "kernel"
    for path in kernel.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "evidence_domain" not in text


def test_reader_and_refuter_prompts_differ() -> None:
    root = Path(__file__).resolve().parents[1] / "packages" / "kernel" / "prompts"
    assert (root / "reader.md").read_bytes() != (root / "refuter.md").read_bytes()


def test_ci_does_not_set_model_base_url() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "MODEL_BASE_URL" not in text
    assert "ubuntu-latest" in text
    assert "windows-latest" in text


def test_demo_template_and_gate() -> None:
    page = Path("apps/api/src/evidence_api/static/demo.html").read_text(encoding="utf-8")
    assert "This tool assists a human reviewer. It does not determine compliance." in page
    assert "compliant" not in page.lower()
    assert "100" not in page
    gate = Path("docs/legal/gate.md").read_text(encoding="utf-8")
    assert "FOUNDER DIRECTED START" in gate
    assert "NOT a record that employment counsel was consulted" in gate
    assert "NOT legal advice" in gate


def test_skills_and_adrs_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    skills = sorted(path.parent.name for path in (root / ".cursor" / "skills").glob("*/SKILL.md"))
    assert len(skills) == 20
    adrs = list((root / "docs" / "adr").glob("ADR-*.md"))
    assert len(adrs) == 21


def test_secret_scan_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    scanner = _load(root / "tools" / "security" / "secret_scan.py", "secret_scan")
    assert scanner.scan(root) == []


def test_metrics_cite_the_measured_test_and_holdout_hash() -> None:
    root = Path(__file__).resolve().parents[1]
    metrics = (root / "docs" / "demo" / "metrics.md").read_text(encoding="utf-8")
    freeze = (root / "bench" / "holdout" / "SHA256.txt").read_text(encoding="utf-8").strip()
    assert freeze in metrics
    assert "test_dev_deterministic_recall_is_one" in metrics
    assert "NOT VERIFIED" in metrics
