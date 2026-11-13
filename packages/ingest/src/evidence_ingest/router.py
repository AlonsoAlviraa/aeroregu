"""Unified text-layer ingestion dispatch for PDF, DOCX, XLSX, and UTF-8 notes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text
from evidence_ingest.docx import ingest_docx_bytes
from evidence_ingest.pdf import ingest_pdf_bytes
from evidence_ingest.requirements import parse_requirements
from evidence_ingest.xlsx import ingest_xlsx_bytes


def ingest_bytes(raw: bytes, filename: str) -> dict[str, Any]:
    """Extract text blocks and requirement spans from raw bytes without guessing."""
    suffix = Path(filename).suffix.lower()
    source_hash = hashlib.sha256(raw).hexdigest()

    if suffix == ".pdf":
        blocks: list[Block] = ingest_pdf_bytes(raw)
        media_type = "pdf"
    elif suffix == ".docx":
        blocks = ingest_docx_bytes(raw)
        media_type = "docx"
    elif suffix == ".xlsx":
        blocks = ingest_xlsx_bytes(raw)
        media_type = "xlsx"
    elif suffix in {".txt", ".md"}:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestAbstain("invalid_utf8") from exc
        blocks = blocks_from_text(text, source_hash)
        media_type = "text"
    else:
        raise IngestAbstain("unsupported_media_type")

    requirements = parse_requirements(blocks)
    return {
        "filename": Path(filename).name,
        "media_type": media_type,
        "source_hash": source_hash,
        "blocks": [block.as_dict() for block in blocks],
        "requirements": requirements,
    }
