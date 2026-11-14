from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

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


def ingest_xlsx(path: Path) -> list[Block]:
    return ingest_xlsx_bytes(Path(path).read_bytes())


def ingest_xlsx_bytes(raw: bytes) -> list[Block]:
    source_hash = hashlib.sha256(raw).hexdigest()
    _guard_archive_safety(raw)
    workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in workbook.worksheets:
            sheet_title = sheet.title or "Sheet"
            row_idx = 1
            for row in sheet.iter_rows(values_only=True):
                cells = [
                    str(cell).strip() for cell in row if cell is not None and str(cell).strip()
                ]
                if cells:
                    row_text = "\t".join(cells)
                    lines.append(f"[Sheet: {sheet_title} R{row_idx}] {row_text}")
                row_idx += 1
    finally:
        workbook.close()
    return blocks_from_text("\n".join(lines), source_hash)
