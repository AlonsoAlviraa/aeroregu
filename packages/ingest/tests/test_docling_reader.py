from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.docling_reader import read_document


def test_missing_docling_abstains(tmp_path) -> None:
    path = tmp_path / "note.pdf"
    path.write_bytes(b"%PDF-1.4")

    def _missing() -> object:
        raise ImportError("docling")

    try:
        read_document(path, loader=_missing)
    except IngestAbstain as exc:
        assert exc.reason == "docling_unavailable"
        return
    raise AssertionError("expected docling_unavailable")
