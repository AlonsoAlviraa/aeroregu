from __future__ import annotations

import hashlib
from pathlib import Path

from openpyxl import load_workbook

from evidence_ingest.blocks import Block, blocks_from_text


def ingest_xlsx(path: Path) -> list[Block]:
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    workbook = load_workbook(path, data_only=True)
    lines: list[str] = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(cell) for cell in row if cell is not None and str(cell).strip()]
            if cells:
                lines.append("\t".join(cells))
    return blocks_from_text("\n".join(lines), source_hash)
