"""Optional Docling reader. Missing Docling is an abstain, not a guessed parse."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text


def _load_converter() -> Callable:
    from docling.document_converter import DocumentConverter

    return DocumentConverter


def read_document(
    path: Path,
    loader: Callable[[], Callable] = _load_converter,
    page_range: tuple[int, int] = (1, 8),
) -> list[Block]:
    raw = Path(path).read_bytes()
    try:
        converter_cls = loader()
    except ImportError as exc:
        raise IngestAbstain("docling_unavailable") from exc
    converted = converter_cls().convert(str(path), page_range=page_range)
    document = converted.document
    text = document.export_to_text() if hasattr(document, "export_to_text") else ""
    return blocks_from_text(text, hashlib.sha256(raw).hexdigest())
