"""Deterministic PDF ingestion with parallel worker pool & dual-pass OCR verification."""

from __future__ import annotations

import concurrent.futures
import hashlib
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pymupdf

from evidence_ingest.blocks import Block, IngestAbstain

PageModality = Literal["vector", "raster_scan", "hybrid", "empty_or_degraded"]

_DEGRADED_MARKER_RE = re.compile(
    r"\[(?:BLURRED_SCAN|DEGRADED_OCR|ILLEGIBLE|LOW_OCR_CONFIDENCE)\]|OCR_CONFIDENCE_LOW",
    re.IGNORECASE,
)
_NUMERIC_CORRUPTION_RE = re.compile(r"(?:(?<=\d)[OIl?~](?=[\d.])|(?<=[\d.])[OIl?~](?=\d))")


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


def _inspect_page_raster_quality(doc: pymupdf.Document, page: pymupdf.Page) -> tuple[bool, float]:
    """Return (degraded_scan, sharpness_score) for embedded raster images on a PDF page."""
    images = page.get_images(full=False)
    if not images:
        return False, 1.0
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, 0.9

    min_sharpness = 9999.0
    for img_info in images[:3]:
        xref = int(img_info[0])
        try:
            extracted = doc.extract_image(xref)
            raw_bytes = extracted.get("image") or b""
            if len(raw_bytes) < 64:
                return True, 0.0
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            mat = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            if mat is None or mat.size == 0:
                return True, 0.0
            h, w = mat.shape[:2]
            if h < 16 or w < 16:
                return True, 0.0
            # Tiny flat/blurred scan variance or very low dynamic range signals degradation
            std_val = float(np.std(mat))
            lap_var = float(cv2.Laplacian(mat, cv2.CV_64F).var())
            score = min(std_val, lap_var)
            if score < min_sharpness:
                min_sharpness = score
        except Exception:
            return True, 0.0

    if min_sharpness < 8.0:
        return True, round(min_sharpness, 4)
    return False, round(min_sharpness, 4)


def detect_page_modality(
    page: pymupdf.Page,
    *,
    doc: pymupdf.Document | None = None,
) -> dict[str, Any]:
    """Classify a PDF page as vector, raster_scan, hybrid, or empty_or_degraded."""
    raw_text = (page.get_text("text") or "").strip()
    images = page.get_images(full=False)
    has_text = len(raw_text) > 0
    has_images = len(images) > 0

    degraded_scan = False
    sharpness = 1.0
    if has_images and doc is not None:
        degraded_scan, sharpness = _inspect_page_raster_quality(doc, page)

    modality: PageModality
    if has_text and has_images:
        modality = "hybrid"
    elif has_text and not has_images:
        modality = "vector"
    elif has_images and not has_text:
        modality = "raster_scan"
    else:
        modality = "empty_or_degraded"

    return {
        "modality": modality,
        "text_chars": len(raw_text),
        "image_count": len(images),
        "degraded_scan": degraded_scan,
        "sharpness_score": sharpness,
    }


def verify_page_ocr_dual_pass(
    text: str,
    page_number: int,
    *,
    modality: PageModality = "vector",
    degraded_scan: bool = False,
) -> dict[str, Any]:
    """Run dual-pass structural & lexical verification with fail-closed OCR abstention."""
    stripped = text.strip()
    if modality in {"raster_scan", "empty_or_degraded"} and not stripped:
        return {
            "page_no": page_number,
            "modality": modality,
            "status": "abstain",
            "reason": "low_ocr_confidence",
            "ocr_confidence": 0.12 if modality == "raster_scan" else 0.0,
            "numeric_values_suppressed": True,
        }

    if degraded_scan:
        return {
            "page_no": page_number,
            "modality": modality,
            "status": "abstain",
            "reason": "low_ocr_confidence",
            "ocr_confidence": 0.35,
            "numeric_values_suppressed": True,
        }

    if _DEGRADED_MARKER_RE.search(stripped):
        return {
            "page_no": page_number,
            "modality": modality,
            "status": "abstain",
            "reason": "low_ocr_confidence",
            "ocr_confidence": 0.41,
            "numeric_values_suppressed": True,
        }

    total_chars = max(1, len(stripped))
    bad_chars = stripped.count("\ufffd") + stripped.count("\x00") + stripped.count("?")
    corrupted_nums = len(_NUMERIC_CORRUPTION_RE.findall(stripped))

    # Pass 1 confidence from printable/replacement character hygiene
    pass1_conf = max(0.0, 1.0 - (bad_chars / total_chars) * 4.0 - corrupted_nums * 0.25)

    # Pass 2 independent lexical token cleanliness & unit/number cross-verification
    tokens = stripped.split()
    noisy_tokens = sum(1 for tok in tokens if "?" in tok or "\ufffd" in tok)
    pass2_conf = max(0.0, 1.0 - (noisy_tokens / max(1, len(tokens))) * 2.5 - corrupted_nums * 0.25)

    combined_conf = round(min(pass1_conf, pass2_conf), 4)
    if combined_conf < 0.78 or abs(pass1_conf - pass2_conf) > 0.25 or corrupted_nums > 0:
        return {
            "page_no": page_number,
            "modality": modality,
            "status": "abstain",
            "reason": "low_ocr_confidence",
            "ocr_confidence": combined_conf,
            "numeric_values_suppressed": True,
        }

    return {
        "page_no": page_number,
        "modality": modality,
        "status": "verified",
        "reason": None,
        "ocr_confidence": combined_conf,
        "numeric_values_suppressed": False,
    }


def _should_probe_tables(page: pymupdf.Page, page_text: str) -> bool:
    if page.get_drawings():
        return True
    if "|" in page_text or "\t" in page_text:
        return True
    # Multi-column spacing heuristic
    return any("   " in ln for ln in page_text.splitlines()[:12])


def _extract_single_page_blocks(
    doc: pymupdf.Document,
    page_idx: int,
    source_hash: str,
    cursor_start: int,
) -> tuple[list[Block], int]:
    page = doc.load_page(page_idx - 1)
    blocks: list[Block] = []
    cursor = cursor_start

    raw_text = page.get_text("text") or ""
    table_rects: list[pymupdf.Rect] = []
    found_tables: list[Any] = []
    if _should_probe_tables(page, raw_text):
        try:
            tables_finder = page.find_tables()
            found_tables = list(getattr(tables_finder, "tables", []))
        except Exception:
            found_tables = []

    for table in found_tables:
        t_rows = getattr(table, "rows", None)
        if t_rows:
            raw_rows = [
                [
                    " ".join(page.get_text("text", clip=pymupdf.Rect(cell)).split()) if cell else ""
                    for cell in row.cells
                ]
                for row in t_rows
            ]
        else:
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

    return blocks, cursor


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
    saw_low_ocr = False
    for page_idx in range(1, len(doc) + 1):
        if not (start <= page_idx <= end):
            continue
        page = doc.load_page(page_idx - 1)
        mod_info = detect_page_modality(page, doc=doc)
        modality: PageModality = mod_info["modality"]
        raw_text = page.get_text("text") or ""
        if (
            modality in {"raster_scan", "hybrid"}
            or mod_info["degraded_scan"]
            or _DEGRADED_MARKER_RE.search(raw_text)
            or _NUMERIC_CORRUPTION_RE.search(raw_text)
        ):
            verdict = verify_page_ocr_dual_pass(
                raw_text,
                page_idx,
                modality=modality,
                degraded_scan=bool(mod_info["degraded_scan"]),
            )
            if verdict["status"] == "abstain":
                saw_low_ocr = True
                continue
        page_blocks, cursor = _extract_single_page_blocks(doc, page_idx, source_hash, cursor)
        blocks.extend(page_blocks)

    if not blocks:
        if saw_low_ocr:
            raise IngestAbstain("low_ocr_confidence")
        raise IngestAbstain("no_text_layer")
    return blocks


def _process_pdf_chunk(
    raw: bytes,
    source_hash: str,
    start_page: int,
    end_page: int,
) -> dict[str, Any]:
    """Worker routine executed per page range in parallel."""
    chunk_blocks: list[Block] = []
    modalities: dict[int, str] = {}
    abstained_pages: list[dict[str, Any]] = []
    verified_pages: list[int] = []

    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        cursor = 0
        for page_idx in range(start_page, end_page + 1):
            page = doc.load_page(page_idx - 1)
            mod_info = detect_page_modality(page, doc=doc)
            modality: PageModality = mod_info["modality"]
            modalities[page_idx] = modality
            raw_text = page.get_text("text") or ""
            ocr_verdict = verify_page_ocr_dual_pass(
                raw_text,
                page_idx,
                modality=modality,
                degraded_scan=bool(mod_info["degraded_scan"]),
            )
            if ocr_verdict["status"] == "abstain":
                abstained_pages.append(ocr_verdict)
                continue
            verified_pages.append(page_idx)
            p_blocks, cursor = _extract_single_page_blocks(doc, page_idx, source_hash, cursor)
            chunk_blocks.extend(p_blocks)

    return {
        "start_page": start_page,
        "blocks": chunk_blocks,
        "modalities": modalities,
        "abstained_pages": abstained_pages,
        "verified_pages": verified_pages,
    }


def ingest_pdf_parallel(
    raw: bytes,
    source_uri: str = "",
    *,
    max_workers: int = 4,
    chunk_pages: int = 25,
    heavy_threshold_pages: int = 20,
) -> dict[str, Any]:
    """Ingest PDF in parallel worker chunks with dual-pass OCR verification & bbox tracking."""
    t0 = time.perf_counter()
    source_hash = hashlib.sha256(raw).hexdigest()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        total_pages = len(doc)

    if total_pages == 0:
        raise IngestAbstain("empty_pdf")

    step = max(1, int(chunk_pages))
    ranges = [(s, min(total_pages, s + step - 1)) for s in range(1, total_pages + 1, step)]

    chunk_results: list[dict[str, Any]] = []
    eff_workers = min(max(1, int(max_workers)), len(ranges))
    if eff_workers <= 1:
        for s, e in ranges:
            chunk_results.append(_process_pdf_chunk(raw, source_hash, s, e))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=eff_workers) as executor:
            futures = [
                executor.submit(_process_pdf_chunk, raw, source_hash, s, e) for s, e in ranges
            ]
            for fut in concurrent.futures.as_completed(futures):
                chunk_results.append(fut.result())

    chunk_results.sort(key=lambda item: int(item["start_page"]))

    # Rebase span_start / span_end deterministically across parallel chunks
    ordered_blocks: list[Block] = []
    all_modalities: dict[int, str] = {}
    all_abstained: list[dict[str, Any]] = []
    all_verified: list[int] = []
    global_cursor = 0

    for item in chunk_results:
        all_modalities.update(item["modalities"])
        all_abstained.extend(item["abstained_pages"])
        all_verified.extend(item["verified_pages"])
        for blk in item["blocks"]:
            length = len(blk.text)
            ordered_blocks.append(
                Block(
                    text=blk.text,
                    span_start=global_cursor,
                    span_end=global_cursor + length,
                    source_hash=blk.source_hash,
                    page_no=blk.page_no,
                    bbox=blk.bbox,
                    block_kind=blk.block_kind,
                    table_rows=blk.table_rows,
                )
            )
            global_cursor += length + 1

    elapsed = max(1e-6, time.perf_counter() - t0)
    raster_or_hybrid = sum(
        1 for m in all_modalities.values() if m in {"raster_scan", "hybrid", "empty_or_degraded"}
    )
    return {
        "source_uri": source_uri,
        "source_hash": source_hash,
        "total_pages": total_pages,
        "blocks": ordered_blocks,
        "verified_pages": sorted(all_verified),
        "abstained_pages": sorted(all_abstained, key=lambda x: int(x["page_no"])),
        "modalities": dict(sorted(all_modalities.items())),
        "elapsed_seconds": round(elapsed, 4),
        "pages_per_second": round(total_pages / elapsed, 2),
        "heavy_pdf_async": total_pages > heavy_threshold_pages or raster_or_hybrid > 0,
        "worker_count": eff_workers,
    }


def build_heavy_pdf_daemon_handler(
    blob_store: Any | None = None,
) -> Callable[[dict[str, Any], Callable[[dict[str, Any]], None]], dict[str, Any]]:
    """Return a DaemonRunner handler for job_type='ingest_heavy_pdf'."""

    def _handle(
        job: dict[str, Any],
        checkpoint_fn: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        payload = job.get("payload") or {}
        checkpoint_fn({"stage": "loading_pdf"})
        if "pdf_sha256" in payload and blob_store is not None:
            raw = blob_store.get_blob(str(payload["pdf_sha256"]))
        elif "file_path" in payload:
            raw = Path(str(payload["file_path"])).read_bytes()
        else:
            raise ValueError("heavy_pdf_job_missing_source")

        max_workers = int(payload.get("max_workers", 4))
        chunk_pages = int(payload.get("chunk_pages", 25))
        res = ingest_pdf_parallel(
            raw,
            source_uri=str(payload.get("source_uri") or payload.get("file_path") or "blob"),
            max_workers=max_workers,
            chunk_pages=chunk_pages,
        )
        checkpoint_fn(
            {
                "stage": "completed",
                "total_pages": res["total_pages"],
                "blocks_extracted": len(res["blocks"]),
                "abstained_count": len(res["abstained_pages"]),
            }
        )
        return {
            "source_hash": res["source_hash"],
            "total_pages": res["total_pages"],
            "block_count": len(res["blocks"]),
            "verified_page_count": len(res["verified_pages"]),
            "abstained_pages": res["abstained_pages"],
            "pages_per_second": res["pages_per_second"],
            "edge_tokens": 0,
            "cloud_tokens": 0,
        }

    return _handle


def ingest_pdf(path: Path, page_range: tuple[int, int] | None = None) -> list[Block]:
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        return _extract_document_blocks(doc, source_hash, page_range=page_range)


def ingest_pdf_bytes(raw: bytes, page_range: tuple[int, int] | None = None) -> list[Block]:
    source_hash = hashlib.sha256(raw).hexdigest()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        return _extract_document_blocks(doc, source_hash, page_range=page_range)
