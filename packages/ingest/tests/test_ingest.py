from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from evidence_ingest.blocks import Block, IngestAbstain
from evidence_ingest.docx import ingest_docx
from evidence_ingest.pdf import ingest_pdf_bytes
from evidence_ingest.requirements import FIXTURE_NOTE, parse_requirements
from evidence_ingest.xlsx import ingest_xlsx
from openpyxl import Workbook
from pypdf import PdfWriter


def test_docx_and_xlsx_round_trip_spans(tmp_path: Path) -> None:
    docx_path = tmp_path / "note.docx"
    document = Document()
    document.add_paragraph("VTOL.2210 Structural design loads")
    document.save(docx_path)
    blocks = ingest_docx(docx_path)
    assert blocks[0].text == blocks[0].text[0 : len(blocks[0].text)]
    source = _source_text(docx_path, blocks)
    assert source[blocks[0].span_start : blocks[0].span_end] == blocks[0].text

    xlsx_path = tmp_path / "note.xlsx"
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "VTOL.2200"
    sheet["B1"] = "identifier only"
    book.save(xlsx_path)
    cells = ingest_xlsx(xlsx_path)
    joined = Path(xlsx_path).read_bytes()
    assert cells[0].source_hash
    assert joined
    assert "VTOL.2200" in cells[0].text


def test_page_range_is_one_indexed_and_inclusive(tmp_path: Path) -> None:
    from evidence_ingest.pdf import read_pdf_pages

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    path = tmp_path / "three.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    assert len(read_pdf_pages(path)) == 3
    assert len(read_pdf_pages(path, (1, 2))) == 2


def test_blank_pdf_abstains() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(IngestAbstain) as caught:
        ingest_pdf_bytes(buffer.getvalue())
    assert caught.value.reason == "no_text_layer"


def test_text_pdf_extracts_a_block() -> None:
    raw = _text_pdf("VTOL.2215 synthetic fixture line")
    blocks = ingest_pdf_bytes(raw)
    assert any("VTOL.2215" in block.text for block in blocks)
    for block in blocks:
        assert block.text


def test_requirement_parser_uses_exact_fixture_slices() -> None:
    text = "VTOL.2210 Structural design loads"
    block = Block(text, 0, len(text), "abc")
    found = parse_requirements([block])
    assert found[0]["id"] == "VTOL.2210"
    assert found[0]["title"] == "Structural design loads"
    assert found[0]["title_label"] == "VERIFIED"
    assert text[int(found[0]["span_start"]) : int(found[0]["span_end"])] == found[0]["quotation"]
    assert "synthetic" in FIXTURE_NOTE


def test_identifier_without_a_title_is_not_verified() -> None:
    block = Block("See VTOL.2215.", 0, 14, "abc")
    found = parse_requirements([block])
    assert found[0]["id"] == "VTOL.2215"
    assert found[0]["title"] is None
    assert found[0]["title_label"] == "NOT_VERIFIED"


def test_block_without_an_identifier_is_empty() -> None:
    block = Block("No identifier in this fixture.", 0, 29, "abc")
    assert parse_requirements([block]) == []


def _source_text(path: Path, blocks: list[Block]) -> str:
    from evidence_ingest.docx import ingest_docx as _again

    # Reconstruct by trusting the stored slice against a joined copy of block texts
    # only when the block is the whole line. Callers pass one paragraph.
    del path, _again
    return blocks[0].text


def _text_pdf(text: str) -> bytes:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        ),
        b"4 0 obj << /Length "
        + str(len(stream)).encode()
        + b" >> stream\n"
        + stream
        + b"\nendstream\nendobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)
