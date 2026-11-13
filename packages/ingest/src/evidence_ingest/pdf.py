"""Deterministic algorithmic PDF ingestion via PyMuPDF (text blocks + tables + bboxes)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pymupdf

from evidence_ingest.blocks import Block, IngestAbstain


def page_texts(doc: Any, page_range: tuple[int, int] | None = None) -> list[str]:
    """Extract 1-indexed inclusive page texts from a PyMuPDF document or PdfReader."""
    total_pages = len(doc) if hasattr(doc, "__len__") else len(doc.pages)
    start = 1
    end = total_pages
    if page_range is not None:
        start, end = page_range
    texts: list[str] = []
    for index in range(1, total_pages + 1):
        if not (start <= index <= end):
            continue
        if hasattr(doc, "load_page"):
            texts.append(doc.load_page(index - 1).get_text("text") or "")
        else:
            texts.append(doc.pages[index - 1].extract_text() or "")
    return texts


def read_pdf_pages(path: Path, page_range: tuple[int, int] | None = None) -> list[str]:
    with pymupdf.open(str(path)) as doc:
        return page_texts(doc, page_range)


def _extract_document_blocks(
    doc: pymupdf.Document,
    source_hash: str,
    page_range: tuple[int, int] | None = None,
) -> list[Block]:
    """Extract deterministic line and table blocks with page numbers and exact PDF bboxes."""
    start = 1
    end = len(doc)
    if page_range is not None:
        start, end = page_range

    blocks: list[Block] = []
    cursor = 0

    for page_idx in range(1, len(doc) + 1):
        if not (start <= page_idx <= end):
            continue
        page = doc.load_page(page_idx - 1)

        table_rects: list[pymupdf.Rect] = []
        try:
            tables_finder = page.find_tables()
            found_tables = list(getattr(tables_finder, "tables", []))
        except Exception:
            found_tables = []

        for table in found_tables:
            raw_rows = table.extract() or []
            clean_rows = [
                [str(cell or "").strip() for cell in row]
                for row in raw_rows
                if any(str(cell or "").strip() for cell in row)
            ]
            if not clean_rows:
                continue
            bbox_tuple = tuple(float(v) for v in table.bbox[:4])
            table_rects.append(pymupdf.Rect(*bbox_tuple))
            rendered = "\n".join(" | ".join(row) for row in clean_rows)
            blocks.append(
                Block(
                    text=rendered,
                    span_start=cursor,
                    span_end=cursor + len(rendered),
                    source_hash=source_hash,
                    page_no=page_idx,
                    bbox=(bbox_tuple[0], bbox_tuple[1], bbox_tuple[2], bbox_tuple[3]),
                    block_kind="table",
                    table_rows=clean_rows,
                )
            )
            cursor += len(rendered) + 1

        page_dict = page.get_text("dict")
        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            b_rect_vals = raw_block.get("bbox")
            if b_rect_vals and len(b_rect_vals) == 4 and table_rects:
                b_rect = pymupdf.Rect(*b_rect_vals)
                if any(
                    b_rect.intersects(t_rect)
                    and b_rect.intersect(t_rect).get_area() > 0.5 * b_rect.get_area()
                    for t_rect in table_rects
                ):
                    continue
            for line in raw_block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(str(s.get("text", "")) for s in spans).rstrip("\r\n")
                if not line_text.strip():
                    continue
                lb = line.get("bbox") or raw_block.get("bbox")
                bbox_val = (
                    (float(lb[0]), float(lb[1]), float(lb[2]), float(lb[3]))
                    if lb and len(lb) == 4
                    else None
                )
                blocks.append(
                    Block(
                        text=line_text,
                        span_start=cursor,
                        span_end=cursor + len(line_text),
                        source_hash=source_hash,
                        page_no=page_idx,
                        bbox=bbox_val,
                        block_kind="text",
                    )
                )
                cursor += len(line_text) + 1

    if not blocks:
        raise IngestAbstain("no_text_layer")
    return blocks


def ingest_pdf(path: Path, page_range: tuple[int, int] | None = None) -> list[Block]:
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        return _extract_document_blocks(doc, source_hash, page_range=page_range)


def ingest_pdf_bytes(raw: bytes, page_range: tuple[int, int] | None = None) -> list[Block]:
    source_hash = hashlib.sha256(raw).hexdigest()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        return _extract_document_blocks(doc, source_hash, page_range=page_range)
