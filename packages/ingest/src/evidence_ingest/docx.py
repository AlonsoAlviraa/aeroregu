from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text


class DecompressionLimitExceeded(IngestAbstain, ValueError):
    def __init__(self, reason: str = "archive_decompression_limit_exceeded") -> None:
        super().__init__(reason)
        self.reason = reason


class CorruptedArchive(IngestAbstain, ValueError):
    def __init__(self, reason: str = "corrupted_archive") -> None:
        super().__init__(reason)
        self.reason = reason


def _guard_archive_safety(raw: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(raw), "r") as archive:
            total_uncompressed = 0
            for info in archive.infolist():
                total_uncompressed += info.file_size
                if total_uncompressed > 64 * 1024 * 1024:
                    raise DecompressionLimitExceeded("archive_decompression_limit_exceeded")
                if info.file_size > 65536:
                    if info.compress_size <= 0 or (info.file_size / info.compress_size) > 100:
                        raise DecompressionLimitExceeded("archive_decompression_limit_exceeded")
    except zipfile.BadZipFile as exc:
        raise CorruptedArchive("corrupted_archive") from exc


def ingest_docx(path: Path) -> list[Block]:
    return ingest_docx_bytes(Path(path).read_bytes())


def ingest_docx_bytes(raw: bytes) -> list[Block]:
    source_hash = hashlib.sha256(raw).hexdigest()
    _guard_archive_safety(raw)
    document = Document(BytesIO(raw))
    lines: list[str] = [
        paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()
    ]
    for table in document.tables:
        for row in table.rows:
            seen_cells: set[Any] = set()
            row_cells: list[str] = []
            for cell in row.cells:
                if cell._tc in seen_cells:
                    continue
                seen_cells.add(cell._tc)
                cell_text = " ".join(cell.text.split())
                if cell_text:
                    row_cells.append(cell_text)
            if row_cells:
                lines.append(" | ".join(row_cells))
    return blocks_from_text("\n".join(lines), source_hash)
