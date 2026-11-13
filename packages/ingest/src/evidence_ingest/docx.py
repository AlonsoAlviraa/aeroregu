from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from docx import Document

from evidence_ingest.blocks import Block, blocks_from_text


def ingest_docx(path: Path) -> list[Block]:
    return ingest_docx_bytes(Path(path).read_bytes())


def ingest_docx_bytes(raw: bytes) -> list[Block]:
    source_hash = hashlib.sha256(raw).hexdigest()
    document = Document(BytesIO(raw))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return blocks_from_text("\n".join(lines), source_hash)
