"""Unified Corporate Multi-Page Vector-Table & Ed25519 DSSE/QR PDF Layout Engine.

Eliminates hard string slicing and text/QR overlap across all AeroRegu signed PDF
exporters by wrapping every cell/KPI via PyMuPDF font-width measurement, rendering
vector grids with repeating headers across automatic page breaks, and embedding DSSE
Ed25519 attestations + ISO offline QR codes.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pymupdf
from evidence_kernel.attestation import sign_attestation_dsse
from evidence_kernel.qrcode_iso import render_qr_png

from evidence_coverage.pdf_report import _DSSE_ATTACHMENT_NAME, _PUBKEY_ATTACHMENT_NAME

_PAGE_W = 595.0
_PAGE_H = 842.0
_MARGIN_L = 36.0
_MARGIN_R = 36.0
_CONTENT_W = _PAGE_W - _MARGIN_L - _MARGIN_R  # 523.0 pt
_SAFE_BOTTOM_Y = 786.0
_FONT_NAME = "helv"
_FONT_OBJ = pymupdf.Font(_FONT_NAME)


def _wrap_text(text: str, max_width: float, fontsize: float) -> list[str]:
    """Wrap text cleanly to max_width in points using actual Helvetica metrics."""
    raw = str(text if text is not None else "")
    if not raw:
        return [""]
    paragraphs = raw.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    for para in paragraphs:
        if not para:
            out.append("")
            continue
        words = para.split(" ")
        cur = ""
        for word in words:
            trial = f"{cur} {word}".strip() if cur else word
            if _FONT_OBJ.text_length(trial, fontsize=fontsize) <= max_width:
                cur = trial
                continue
            if cur:
                out.append(cur)
                cur = ""
            # Character-wrap unbroken tokens (SHA hashes, long method IDs, URLs)
            if _FONT_OBJ.text_length(word, fontsize=fontsize) <= max_width:
                cur = word
            else:
                buf = ""
                for ch in word:
                    if _FONT_OBJ.text_length(buf + ch, fontsize=fontsize) <= max_width:
                        buf += ch
                    else:
                        if buf:
                            out.append(buf)
                        buf = ch
                cur = buf
        if cur:
            out.append(cur)
    return out or [""]


def _cell_tone_color(text: str) -> tuple[float, float, float]:
    up = text.upper()
    if any(
        bad in up
        for bad in (
            "COUNTEREXAMPLE",
            "NEGATIVE",
            "POISON",
            "REJECT",
            "ABSTAIN",
            "GAP_",
            "CRITICAL",
        )
    ):
        return (0.68, 0.09, 0.12)
    if any(
        good in up
        for good in (
            "PROVED_UNSAT",
            "ALL_ENVELOPES_POSITIVE",
            "ALL_MARGINS_POSITIVE",
            "READY_FOR_CVE",
            "CVE_SIGNED",
            "SUPPORTED",
            "RECOMMENDED",
            "*REC*",
        )
    ):
        return (0.04, 0.42, 0.18)
    return (0.11, 0.15, 0.24)


class CorporatePDFBuilder:
    """Composable multi-page vector PDF builder with non-overlapping QR & vector tables."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        merkle_root: str,
        qr_payload: str,
        meta_kpis: list[tuple[str, str]],
        creator: str = "aeroregu-corporate-pdf",
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.merkle_root = merkle_root
        self.qr_payload = qr_payload
        self.creator = creator
        self.qr_png = render_qr_png(qr_payload, scale=8, border=6)

        self.doc = pymupdf.open()
        self.page = self.doc.new_page(width=_PAGE_W, height=_PAGE_H)
        self.y = 26.0
        self._draw_hero(meta_kpis)

    def _draw_banner(self, page: Any, title_txt: str, sub_txt: str) -> float:
        banner_rgb = (15 / 255, 23 / 255, 42 / 255)
        page.draw_rect(pymupdf.Rect(32, 24, _PAGE_W - 32, 86), color=banner_rgb, fill=banner_rgb)
        page.insert_text(
            (44, 49), title_txt[:82], fontsize=13.0, fontname=_FONT_NAME, color=(1, 1, 1)
        )
        page.insert_text(
            (44, 68),
            sub_txt[:108],
            fontsize=8.0,
            fontname=_FONT_NAME,
            color=(0.82, 0.88, 0.96),
        )
        return 98.0

    def _draw_hero(self, meta_kpis: list[tuple[str, str]]) -> None:
        top_y = self._draw_banner(self.page, self.title, self.subtitle)
        # Right column QR card: x=[410, 558] (148x148 pt)
        qr_x0, qr_y0, qr_x1, qr_y1 = 410.0, top_y, 558.0, top_y + 148.0
        self.page.draw_rect(
            pymupdf.Rect(qr_x0, qr_y0, qr_x1, qr_y1),
            color=(0.82, 0.86, 0.91),
            fill=(1, 1, 1),
            width=0.7,
        )
        self.page.insert_image(
            pymupdf.Rect(qr_x0 + 4, qr_y0 + 4, qr_x1 - 4, qr_y1 - 4), stream=self.qr_png
        )
        self.page.insert_text(
            (qr_x0 + 12, qr_y1 + 12),
            "Offline ISO QR + Ed25519 DSSE",
            fontsize=7.3,
            fontname=_FONT_NAME,
            color=(0.24, 0.29, 0.38),
        )

        # Left KPI block strictly confined to x=[36, 396] (width 360 pt) — ZERO QR overlap
        left_w = 360.0
        cur_y = top_y + 12.0
        for label, value in meta_kpis:
            full = f"{label}: {value}"
            wrapped = _wrap_text(full, left_w, 8.6)
            for idx, ln in enumerate(wrapped):
                col = (
                    _cell_tone_color(ln)
                    if idx > 0 or any(k in ln for k in ("Z3", "PROVED", "GAP", "POISON", "Gate"))
                    else (0.10, 0.14, 0.22)
                )
                self.page.insert_text(
                    (_MARGIN_L, cur_y), ln, fontsize=8.6, fontname=_FONT_NAME, color=col
                )
                cur_y += 12.0
            cur_y += 2.0

        self.y = max(cur_y + 10.0, qr_y1 + 28.0)

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=_PAGE_W, height=_PAGE_H)
        self.y = self._draw_banner(
            self.page,
            f"{self.title} (Cont.)",
            self.subtitle,
        )

    def ensure_space(self, needed_h: float) -> None:
        if self.y + needed_h > _SAFE_BOTTOM_Y:
            self._new_page()

    def add_section_heading(self, text: str) -> None:
        self.ensure_space(28.0)
        self.page.insert_text(
            (_MARGIN_L, self.y + 11.0),
            text,
            fontsize=10.5,
            fontname=_FONT_NAME,
            color=(0.06, 0.10, 0.18),
        )
        self.y += 18.0

    def add_note(
        self, text: str, *, color: tuple[float, float, float] = (0.16, 0.20, 0.28)
    ) -> None:
        lines = _wrap_text(text, _CONTENT_W - 8.0, 8.2)
        needed = len(lines) * 11.5 + 8.0
        self.ensure_space(needed)
        for ln in lines:
            self.page.insert_text(
                (_MARGIN_L + 4.0, self.y + 9.0), ln, fontsize=8.2, fontname=_FONT_NAME, color=color
            )
            self.y += 11.5
        self.y += 4.0

    def add_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[Any]],
        *,
        col_widths: list[float] | None = None,
        fontsize: float = 7.4,
    ) -> None:
        """Render a vector grid table with multi-line cell wrap and repeating headers."""
        n_cols = len(headers)
        if col_widths is None or len(col_widths) != n_cols:
            widths = [_CONTENT_W / n_cols] * n_cols
        else:
            scale = _CONTENT_W / sum(col_widths)
            widths = [w * scale for w in col_widths]

        self.add_section_heading(title)
        hdr_h = 19.0
        line_h = fontsize + 3.0

        def _draw_header_row() -> None:
            hdr_fill = (0.11, 0.17, 0.28)
            self.page.draw_rect(
                pymupdf.Rect(_MARGIN_L, self.y, _MARGIN_L + _CONTENT_W, self.y + hdr_h),
                color=hdr_fill,
                fill=hdr_fill,
            )
            cx = _MARGIN_L
            for h_txt, w in zip(headers, widths, strict=True):
                h_lines = _wrap_text(h_txt, w - 6.0, fontsize)
                self.page.insert_text(
                    (cx + 3.0, self.y + 12.0),
                    h_lines[0],
                    fontsize=fontsize,
                    fontname=_FONT_NAME,
                    color=(1, 1, 1),
                )
                cx += w
            self.y += hdr_h

        self.ensure_space(hdr_h + 24.0)
        _draw_header_row()

        if not rows:
            self.add_note("No rows recorded.")
            return

        for r_idx, row in enumerate(rows):
            wrapped_cells: list[list[str]] = []
            max_lines = 1
            for c_idx in range(n_cols):
                val = str(row[c_idx]) if c_idx < len(row) else ""
                cell_lines = _wrap_text(val, widths[c_idx] - 6.0, fontsize)
                wrapped_cells.append(cell_lines)
                max_lines = max(max_lines, len(cell_lines))
            row_h = max(16.0, max_lines * line_h + 6.0)

            if self.y + row_h > _SAFE_BOTTOM_Y:
                self._new_page()
                _draw_header_row()

            fill_col = (0.965, 0.975, 0.992) if (r_idx % 2 == 1) else (1.0, 1.0, 1.0)
            self.page.draw_rect(
                pymupdf.Rect(_MARGIN_L, self.y, _MARGIN_L + _CONTENT_W, self.y + row_h),
                color=(0.84, 0.87, 0.92),
                fill=fill_col,
                width=0.45,
            )
            cx = _MARGIN_L
            for c_lines, w in zip(wrapped_cells, widths, strict=True):
                cell_txt = " ".join(c_lines)
                col = _cell_tone_color(cell_txt)
                ty = self.y + 10.5
                for ln in c_lines:
                    self.page.insert_text(
                        (cx + 3.0, ty),
                        ln,
                        fontsize=fontsize,
                        fontname=_FONT_NAME,
                        color=col,
                    )
                    ty += line_h
                cx += w
            self.y += row_h
        self.y += 10.0

    def add_bbox_thumbnail(self, img_bytes: bytes, caption: str) -> None:
        self.ensure_space(108.0)
        self.page.insert_image(
            pymupdf.Rect(_MARGIN_L + 4.0, self.y, _MARGIN_L + 184.0, self.y + 92.0),
            stream=img_bytes,
        )
        lines = _wrap_text(caption, _CONTENT_W - 196.0, 8.0)
        ty = self.y + 18.0
        for ln in lines:
            self.page.insert_text(
                (_MARGIN_L + 194.0, ty),
                ln,
                fontsize=8.0,
                fontname=_FONT_NAME,
                color=(0.68, 0.09, 0.12),
            )
            ty += 11.0
        self.y += 100.0

    def finalize_signed(
        self,
        *,
        attestation_payload: dict[str, Any],
        private_key_pem: bytes,
        public_key_pem: bytes,
        metadata_title: str,
        output_path: Path | str | None = None,
    ) -> dict[str, Any]:
        dsse_envelope = sign_attestation_dsse(attestation_payload, private_key_pem)
        dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")

        total_pages = len(self.doc)
        for p_idx in range(total_pages):
            pg = self.doc[p_idx]
            pg.draw_line(
                pymupdf.Point(_MARGIN_L, 804),
                pymupdf.Point(_PAGE_W - _MARGIN_R, 804),
                color=(0.82, 0.85, 0.90),
                width=0.6,
            )
            footer = (
                f"This tool assists a human reviewer. It does not determine compliance. | "
                f"Page {p_idx + 1} / {total_pages} | Merkle {self.merkle_root[:16]}"
            )
            pg.insert_text(
                (_MARGIN_L, 818),
                footer,
                fontsize=7.3,
                fontname=_FONT_NAME,
                color=(0.35, 0.40, 0.48),
            )

        self.doc.embfile_add(
            _DSSE_ATTACHMENT_NAME,
            dsse_bytes,
            filename=_DSSE_ATTACHMENT_NAME,
            desc="DSSE v1 Ed25519 Signed Attestation Envelope",
        )
        self.doc.embfile_add(
            _PUBKEY_ATTACHMENT_NAME,
            public_key_pem,
            filename=_PUBKEY_ATTACHMENT_NAME,
            desc="Ed25519 Verification Public Key (PEM)",
        )
        self.doc.set_metadata(
            {
                "title": metadata_title,
                "subject": f"merkle={self.merkle_root}",
                "keywords": self.qr_payload,
                "creator": self.creator,
            }
        )
        pdf_bytes = self.doc.tobytes(deflate=True)
        self.doc.close()

        out_str: str | None = None
        if output_path is not None:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(pdf_bytes)
            out_str = str(out_p)
        return {
            "pdf_bytes": pdf_bytes,
            "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "merkle_root": self.merkle_root,
            "qr_payload": self.qr_payload,
            "dsse_envelope": dsse_envelope,
            "public_key_pem": public_key_pem.decode("ascii"),
            "page_count": total_pages,
            "output_path": out_str,
        }


def compute_dsse_sig_prefix(attestation_payload: dict[str, Any], private_key_pem: bytes) -> str:
    """Pre-compute deterministic signature SHA-256 prefix for offline QR encoding."""
    dsse = sign_attestation_dsse(attestation_payload, private_key_pem)
    sig_raw = base64.b64decode(dsse["signatures"][0]["sig"])
    return hashlib.sha256(sig_raw).hexdigest()
