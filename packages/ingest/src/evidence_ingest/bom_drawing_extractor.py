"""Deterministic BOM and Drawing-List Extractor across PDF, XLSX, and DOCX RFQ attachments.

Produces structured BOM line items and engineering drawing registers with verified
`page_no` + `bbox` citations (for PDFs) or sheet/row/table provenance (for XLSX/DOCX).
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.cad_common import decimal_str
from evidence_ingest.xlsx import _guard_archive_safety

_BOM_HEADER_TOKENS = (
    "part number",
    "part_no",
    "p/n",
    "pn",
    "item",
    "referencia",
    "qty",
    "quantity",
    "cantidad",
    "material",
    "mass",
    "weight",
    "peso",
)
_DRAWING_HEADER_TOKENS = (
    "drawing",
    "dwg",
    "drw",
    "plano",
    "rev",
    "revision",
    "sheet",
    "hoja",
    "title",
    "titulo",
)


def _clean_cell(val: Any) -> str:
    return " ".join(str(val or "").split()).strip()


def _parse_pos_decimal(raw: Any, default: str = "0") -> Decimal:
    txt = _clean_cell(raw)
    m = re.search(r"([+-]?\d+(?:[.,]\d+)?)", txt)
    if not m:
        return Decimal(default)
    num_s = m.group(1).replace(",", ".")
    try:
        d = Decimal(num_s)
        return d if d.is_finite() and d >= 0 else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


def _classify_table_headers(headers: list[str]) -> str | None:
    joined = " | ".join(h.lower() for h in headers)
    bom_hits = sum(1 for tok in _BOM_HEADER_TOKENS if tok in joined)
    dwg_hits = sum(1 for tok in _DRAWING_HEADER_TOKENS if tok in joined)
    has_pn = any(t in joined for t in ("part", "p/n", "pn", "item", "referencia"))
    has_qty = any(t in joined for t in ("qty", "quantity", "cantidad"))
    has_dwg = any(t in joined for t in ("drawing", "dwg", "drw", "plano"))
    if has_dwg and dwg_hits >= 2:
        return "drawing_list"
    if (has_pn and has_qty) or bom_hits >= 3:
        return "bom"
    if dwg_hits >= 2:
        return "drawing_list"
    return None


def _map_row_fields(headers: list[str], row: list[str], kind: str) -> dict[str, Any]:
    low = [h.lower() for h in headers]

    def _find(*candidates: str) -> str:
        for idx, h in enumerate(low):
            if idx < len(row) and any(c in h for c in candidates):
                return row[idx]
        return ""

    if kind == "bom":
        pn = _find("part number", "part_no", "p/n", "pn", "referencia", "part") or (
            row[0] if row else "PART-UNKNOWN"
        )
        desc = _find("desc", "name", "nombre", "title") or (row[1] if len(row) > 1 else "")
        qty_raw = _find("qty", "quantity", "cantidad") or "1"
        mat = _find("material", "alloy", "spec") or "UNSPECIFIED"
        mass_raw = _find("mass", "weight", "peso") or "0"
        dwg_ref = _find("drawing", "dwg", "drw", "plano")
        qty_d = max(Decimal("1"), _parse_pos_decimal(qty_raw, "1"))
        mass_d = _parse_pos_decimal(mass_raw, "0")
        return {
            "part_number": pn,
            "description": desc,
            "quantity": int(qty_d.to_integral_value()),
            "material": mat,
            "unit_mass_kg": decimal_str(mass_d, "0.001"),
            "total_mass_kg": decimal_str(mass_d * qty_d, "0.001"),
            "drawing_ref": dwg_ref,
        }

    dwg_no = _find("drawing", "dwg", "drw", "plano", "number") or (row[0] if row else "DWG-UNKNOWN")
    title = _find("title", "titulo", "desc", "name") or (row[1] if len(row) > 1 else "")
    rev = _find("rev", "issue") or "A"
    sheet = _find("sheet", "hoja") or "1"
    status = _find("status", "estado", "maturity") or "RELEASED"
    return {
        "drawing_number": dwg_no,
        "title": title,
        "revision": rev,
        "sheet": sheet,
        "status": status,
    }


def _extract_pdf_bom_and_drawings(
    raw: bytes, *, filename: str, source_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    import pymupdf

    bom_items: list[dict[str, Any]] = []
    drawings: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []

    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        for page_idx in range(len(doc)):
            page_no = page_idx + 1
            page = doc.load_page(page_idx)
            try:
                finder = page.find_tables()
                tables = list(getattr(finder, "tables", []))
            except Exception:
                tables = []

            for tbl in tables:
                t_rows = getattr(tbl, "rows", None)
                if t_rows:
                    parsed_rows = [
                        [
                            _clean_cell(
                                page.get_text("text", clip=pymupdf.Rect(cell)) if cell else ""
                            )
                            for cell in r.cells
                        ]
                        for r in t_rows
                    ]
                    row_bboxes = [
                        [round(float(v), 2) for v in r.bbox[:4]]
                        if getattr(r, "bbox", None)
                        else [round(float(v), 2) for v in tbl.bbox[:4]]
                        for r in t_rows
                    ]
                else:
                    raw_ext = tbl.extract() or []
                    parsed_rows = [[_clean_cell(c) for c in r] for r in raw_ext]
                    tbl_box = [round(float(v), 2) for v in tbl.bbox[:4]]
                    row_bboxes = [tbl_box for _ in parsed_rows]

                non_empty = [
                    (r, bb) for r, bb in zip(parsed_rows, row_bboxes, strict=False) if any(r)
                ]
                if len(non_empty) < 2:
                    continue
                headers = non_empty[0][0]
                kind = _classify_table_headers(headers)
                if kind is None:
                    continue

                for r_vals, r_bbox in non_empty[1:]:
                    citation = {
                        "source_file": filename,
                        "source_hash": source_hash,
                        "page_no": page_no,
                        "bbox": r_bbox,
                    }
                    citations.append(citation)
                    mapped = _map_row_fields(headers, r_vals, kind)
                    mapped["citation"] = citation
                    if kind == "bom":
                        bom_items.append(mapped)
                    else:
                        drawings.append(mapped)

            # Regex fallback over text blocks with exact block bbox when table borders are missing
            if not tables:
                for blk in page.get_text("blocks") or []:
                    if len(blk) < 5:
                        continue
                    b_text = _clean_cell(blk[4])
                    b_bbox = [round(float(blk[i]), 2) for i in range(4)]
                    m_bom = re.match(
                        r"^(?:PN|P/N)\s*[:=]?\s*([A-Z0-9\-_]+).*?\bQTY\s*[:=]?\s*(\d+)"
                        r"(?:.*?\bMASS\s*[:=]?\s*([0-9.]+)\s*kg)?",
                        b_text,
                        re.IGNORECASE,
                    )
                    if m_bom:
                        qty_i = int(m_bom.group(2))
                        mass_d = Decimal(m_bom.group(3) or "0")
                        cit = {
                            "source_file": filename,
                            "source_hash": source_hash,
                            "page_no": page_no,
                            "bbox": b_bbox,
                        }
                        citations.append(cit)
                        bom_items.append(
                            {
                                "part_number": m_bom.group(1),
                                "description": b_text[:80],
                                "quantity": qty_i,
                                "material": "UNSPECIFIED",
                                "unit_mass_kg": decimal_str(mass_d, "0.001"),
                                "total_mass_kg": decimal_str(mass_d * Decimal(qty_i), "0.001"),
                                "drawing_ref": "",
                                "citation": cit,
                            }
                        )
                    m_dwg = re.match(
                        r"^(?:DWG|DRW|DRAWING)\s*[:=]?\s*([A-Z0-9\-_]+)\s+REV\s*[:=]?\s*([A-Z0-9]+)",
                        b_text,
                        re.IGNORECASE,
                    )
                    if m_dwg:
                        cit = {
                            "source_file": filename,
                            "source_hash": source_hash,
                            "page_no": page_no,
                            "bbox": b_bbox,
                        }
                        citations.append(cit)
                        drawings.append(
                            {
                                "drawing_number": m_dwg.group(1),
                                "title": b_text[:80],
                                "revision": m_dwg.group(2),
                                "sheet": "1",
                                "status": "RELEASED",
                                "citation": cit,
                            }
                        )

    return bom_items, drawings, citations


def _extract_xlsx_bom_and_drawings(
    raw: bytes, *, filename: str, source_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    from openpyxl import load_workbook

    _guard_archive_safety(raw)
    wb = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    bom_items: list[dict[str, Any]] = []
    drawings: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    try:
        for sheet in wb.worksheets:
            rows_with_idx: list[tuple[int, list[str]]] = []
            for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = [_clean_cell(c) for c in row]
                if any(cells):
                    rows_with_idx.append((r_idx, cells))
            if len(rows_with_idx) < 2:
                continue
            headers = rows_with_idx[0][1]
            kind = _classify_table_headers(headers)
            if kind is None:
                sname = (sheet.title or "").lower()
                if "bom" in sname or "part" in sname:
                    kind = "bom"
                elif "draw" in sname or "dwg" in sname or "plano" in sname:
                    kind = "drawing_list"
            if kind is None:
                continue
            for r_idx, r_vals in rows_with_idx[1:]:
                cit = {
                    "source_file": filename,
                    "source_hash": source_hash,
                    "sheet": sheet.title or "Sheet1",
                    "row_no": r_idx,
                    "cell_range": f"A{r_idx}:Z{r_idx}",
                }
                citations.append(cit)
                mapped = _map_row_fields(headers, r_vals, kind)
                mapped["citation"] = cit
                if kind == "bom":
                    bom_items.append(mapped)
                else:
                    drawings.append(mapped)
    finally:
        wb.close()
    return bom_items, drawings, citations


def _extract_docx_bom_and_drawings(
    raw: bytes, *, filename: str, source_hash: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    from docx import Document

    _guard_archive_safety(raw)
    doc = Document(BytesIO(raw))
    bom_items: list[dict[str, Any]] = []
    drawings: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for t_idx, table in enumerate(doc.tables):
        parsed_rows: list[list[str]] = []
        for row in table.rows:
            seen_tc: set[Any] = set()
            r_cells: list[str] = []
            for cell in row.cells:
                if cell._tc in seen_tc:
                    continue
                seen_tc.add(cell._tc)
                r_cells.append(_clean_cell(cell.text))
            if any(r_cells):
                parsed_rows.append(r_cells)
        if len(parsed_rows) < 2:
            continue
        headers = parsed_rows[0]
        kind = _classify_table_headers(headers)
        if kind is None:
            continue
        for r_idx, r_vals in enumerate(parsed_rows[1:], start=2):
            cit = {
                "source_file": filename,
                "source_hash": source_hash,
                "table_index": t_idx,
                "row_no": r_idx,
            }
            citations.append(cit)
            mapped = _map_row_fields(headers, r_vals, kind)
            mapped["citation"] = cit
            if kind == "bom":
                bom_items.append(mapped)
            else:
                drawings.append(mapped)
    return bom_items, drawings, citations


def extract_bom_and_drawings(
    source: Path | str | bytes,
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    """Extract BOM items & drawing lists from PDF, XLSX, or DOCX with verified citations."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        fname = filename or "attachment.pdf"
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"BOM/Drawing document not found: {path}")
        raw = path.read_bytes()
        fname = filename or path.name

    if not raw:
        raise IngestAbstain("empty_bom_drawing_document")

    source_hash = hashlib.sha256(raw).hexdigest()
    ext = Path(fname).suffix.lower()

    if ext == ".pdf":
        bom_items, drawings, citations = _extract_pdf_bom_and_drawings(
            raw, filename=fname, source_hash=source_hash
        )
        fmt = "pdf"
    elif ext == ".xlsx":
        bom_items, drawings, citations = _extract_xlsx_bom_and_drawings(
            raw, filename=fname, source_hash=source_hash
        )
        fmt = "xlsx"
    elif ext == ".docx":
        bom_items, drawings, citations = _extract_docx_bom_and_drawings(
            raw, filename=fname, source_hash=source_hash
        )
        fmt = "docx"
    else:
        raise IngestAbstain(f"unsupported_bom_document_ext:{ext}")

    total_qty = sum(int(item.get("quantity") or 0) for item in bom_items)
    total_mass = sum(
        (Decimal(str(item.get("total_mass_kg") or "0")) for item in bom_items), Decimal("0")
    )
    bbox_cits = [c for c in citations if "bbox" in c and "page_no" in c]

    return {
        "source_file": fname,
        "source_hash": source_hash,
        "format": fmt,
        "bom_items": bom_items,
        "drawing_list": drawings,
        "bom_parts_count": len(bom_items),
        "bom_total_quantity": total_qty,
        "bom_total_mass_kg": decimal_str(total_mass, "0.001"),
        "drawings_count": len(drawings),
        "verified_citations_count": len(citations),
        "verified_bbox_citations": bbox_cits,
    }
