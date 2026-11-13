"""Optional Docling reader with unbounded page support and structured table/bbox provenance."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text


def _load_converter() -> Callable:
    from docling.document_converter import DocumentConverter

    return DocumentConverter


def _extract_docling_tables(document: object, source_hash: str, start_offset: int) -> list[Block]:
    tables = getattr(document, "tables", None) or []
    table_blocks: list[Block] = []
    cursor = start_offset
    for table in tables:
        data = getattr(table, "data", None)
        cells = getattr(data, "table_cells", None) or []
        if not cells:
            continue
        rows_map: dict[int, dict[int, str]] = {}
        for cell in cells:
            r_idx = int(getattr(cell, "start_row_offset_idx", 0))
            c_idx = int(getattr(cell, "start_col_offset_idx", 0))
            rows_map.setdefault(r_idx, {})[c_idx] = str(getattr(cell, "text", "")).strip()
        if not rows_map:
            continue
        clean_rows: list[list[str]] = []
        for r_idx in sorted(rows_map):
            row = [rows_map[r_idx][c_idx] for c_idx in sorted(rows_map[r_idx])]
            if any(row):
                clean_rows.append(row)
        if not clean_rows:
            continue

        prov_list = getattr(table, "prov", None) or []
        page_no: int | None = None
        bbox_val: tuple[float, float, float, float] | None = None
        if prov_list:
            prov0 = prov_list[0]
            page_no = int(getattr(prov0, "page_no", 0)) or None
            bb = getattr(prov0, "bbox", None)
            if bb is not None:
                bbox_val = (float(bb.l), float(bb.t), float(bb.r), float(bb.b))

        rendered = "\n".join(" | ".join(row) for row in clean_rows)
        table_blocks.append(
            Block(
                text=rendered,
                span_start=cursor,
                span_end=cursor + len(rendered),
                source_hash=source_hash,
                page_no=page_no,
                bbox=bbox_val,
                block_kind="table",
                table_rows=clean_rows,
            )
        )
        cursor += len(rendered) + 1
    return table_blocks


def read_document(
    path: Path,
    loader: Callable[[], Callable] = _load_converter,
    page_range: tuple[int, int] | None = None,
) -> list[Block]:
    """Convert full document (or optional page_range) via Docling, preserving tables and bboxes."""
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    try:
        converter_cls = loader()
    except ImportError as exc:
        raise IngestAbstain("docling_unavailable") from exc

    converter = converter_cls()
    converted = (
        converter.convert(str(path), page_range=page_range)
        if page_range is not None
        else converter.convert(str(path))
    )
    document = converted.document
    text = document.export_to_text() if hasattr(document, "export_to_text") else ""

    text_blocks: list[Block] = []
    if text.strip():
        text_blocks = blocks_from_text(text, source_hash)

    next_offset = (text_blocks[-1].span_end + 1) if text_blocks else 0
    table_blocks = _extract_docling_tables(document, source_hash, next_offset)
    combined = [*text_blocks, *table_blocks]
    if not combined:
        raise IngestAbstain("no_text_layer")
    return combined
