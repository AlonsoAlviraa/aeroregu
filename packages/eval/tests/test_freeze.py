from evidence_eval.b2 import dev_sha256
from evidence_eval.b3 import gold_sha256
from evidence_kernel.paths import repo_root


def test_b2_dev_cases_are_frozen() -> None:
    frozen = (repo_root() / "bench" / "b2" / "dev_cases.sha256").read_text(encoding="utf-8")
    assert dev_sha256() == frozen.strip()


def test_b3_dev_gold_is_frozen() -> None:
    frozen = (repo_root() / "bench" / "b3" / "dev_gold.sha256").read_text(encoding="utf-8")
    assert gold_sha256() == frozen.strip()
