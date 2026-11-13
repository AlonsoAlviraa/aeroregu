from __future__ import annotations

import time

import pymupdf
from evidence_ingest.blocks import blocks_from_text
from evidence_ingest.pdf import ingest_pdf_bytes


def _build_12_page_pdf_with_table() -> bytes:
    doc = pymupdf.open()
    for idx in range(1, 13):
        page = doc.new_page(width=595, height=842)
        if idx == 1:
            # Draw explicit 2x2 vector table grid + insert cell text
            shape = page.new_shape()
            for y in (100, 140, 180):
                shape.draw_line((50, y), (450, y))
            for x in (50, 250, 450):
                shape.draw_line((x, 100), (x, 180))
            shape.finish(color=(0, 0, 0), width=1)
            shape.commit()
            page.insert_text((65, 125), "Parameter")
            page.insert_text((265, 125), "Limit")
            page.insert_text((65, 165), "Mass")
            page.insert_text((265, 165), "800 kg")
        page.insert_text((50, 220), f"Page {idx} deterministic structural evidence.")
    raw = doc.tobytes()
    doc.close()
    return raw


def test_pymupdf_extracts_beyond_8_pages_with_tables_and_bboxes() -> None:
    raw = _build_12_page_pdf_with_table()
    blocks = ingest_pdf_bytes(raw)
    pages_seen = {b.page_no for b in blocks if b.page_no is not None}
    assert pages_seen == set(range(1, 13))

    table_blocks = [b for b in blocks if b.block_kind == "table"]
    assert len(table_blocks) >= 1
    tbl = table_blocks[0]
    assert tbl.page_no == 1
    assert tbl.bbox is not None and len(tbl.bbox) == 4
    assert tbl.table_rows is not None
    flat_cells = [cell for row in tbl.table_rows for cell in row]
    assert any("Mass" in cell for cell in flat_cells)
    assert any("800 kg" in cell for cell in flat_cells)

    as_dicts = [b.as_dict() for b in table_blocks]
    assert as_dicts[0]["block_kind"] == "table"
    assert len(as_dicts[0]["bbox"]) == 4


def test_blocks_from_text_linear_scaling() -> None:
    # 20,000 lines would take seconds under O(N^2) line counting; under O(N) takes < 0.25s
    large_text = "\n".join(f"Line {i}: structural margin verified" for i in range(20_000))
    t0 = time.perf_counter()
    blocks = blocks_from_text(large_text, "a" * 64)
    elapsed = time.perf_counter() - t0
    assert len(blocks) == 20_000
    assert blocks[0].span_start == 0
    assert large_text[blocks[1234].span_start : blocks[1234].span_end] == blocks[1234].text
    assert elapsed < 1.0
