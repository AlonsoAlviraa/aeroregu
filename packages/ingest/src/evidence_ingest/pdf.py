from __future__ import annotations

import hashlib
from pathlib import Path

from pypdf import PdfReader

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text


def page_texts(reader: PdfReader, page_range: tuple[int, int] | None = None) -> list[str]:
    start = 1
    end = len(reader.pages)
    if page_range is not None:
        start, end = page_range
    texts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        if start <= index <= end:
            texts.append(page.extract_text() or "")
    return texts


def read_pdf_pages(path: Path, page_range: tuple[int, int] | None = None) -> list[str]:
    return page_texts(PdfReader(str(path)), page_range)


def ingest_pdf(path: Path, page_range: tuple[int, int] | None = None) -> list[Block]:
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    return blocks_from_text("\n".join(read_pdf_pages(path, page_range)), source_hash)


def ingest_pdf_bytes(raw: bytes) -> list[Block]:
    from io import BytesIO

    source_hash = hashlib.sha256(raw).hexdigest()
    reader = PdfReader(BytesIO(raw))
    try:
        return blocks_from_text("\n".join(page_texts(reader)), source_hash)
    except IngestAbstain:
        raise
