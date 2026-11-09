from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document

from evidence_ingest.blocks import Block, blocks_from_text


def ingest_docx(path: Path) -> list[Block]:
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    document = Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return blocks_from_text("\n".join(lines), source_hash)
