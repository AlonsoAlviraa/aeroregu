"""Unified text-layer and CAD/CAE ingestion dispatch."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from evidence_ingest.blocks import Block, IngestAbstain, blocks_from_text
from evidence_ingest.cad_iges import parse_iges
from evidence_ingest.cad_step import parse_step_ap242
from evidence_ingest.catia_bridge import parse_catia_native, parse_catia_xml
from evidence_ingest.docx import ingest_docx_bytes
from evidence_ingest.fem_parsers import parse_abaqus_inp, parse_nastran_bdf, parse_nastran_f06
from evidence_ingest.pdf import ingest_pdf_bytes
from evidence_ingest.requirements import parse_requirements
from evidence_ingest.xlsx import ingest_xlsx_bytes

CAD_CAE_MEDIA_TYPES = {
    ".stp": "step_ap242",
    ".step": "step_ap242",
    ".p21": "step_ap242",
    ".igs": "iges",
    ".iges": "iges",
    ".xml": "catia_xml",
    ".catxml": "catia_xml",
    ".catpart": "catia_native",
    ".catproduct": "catia_native",
    ".bdf": "nastran_bdf",
    ".dat": "nastran_bdf",
    ".nas": "nastran_bdf",
    ".f06": "nastran_f06",
    ".inp": "abaqus_inp",
}


def ingest_bytes(raw: bytes, filename: str) -> dict[str, Any]:
    """Extract text blocks, CAD/CAE structures, and requirement spans without guessing."""
    suffix = Path(filename).suffix.lower()
    source_hash = hashlib.sha256(raw).hexdigest()
    cad_cae: dict[str, Any] | None = None

    if suffix == ".pdf":
        blocks: list[Block] = ingest_pdf_bytes(raw)
        media_type = "pdf"
    elif suffix == ".docx":
        blocks = ingest_docx_bytes(raw)
        media_type = "docx"
    elif suffix == ".xlsx":
        blocks = ingest_xlsx_bytes(raw)
        media_type = "xlsx"
    elif suffix in {".txt", ".md"}:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestAbstain("invalid_utf8") from exc
        blocks = blocks_from_text(text, source_hash)
        media_type = "text"
    elif suffix in {".stp", ".step", ".p21"}:
        parsed = parse_step_ap242(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "step_ap242"
    elif suffix in {".igs", ".iges"}:
        parsed = parse_iges(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "iges"
    elif suffix in {".xml", ".catxml"}:
        parsed = parse_catia_xml(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "catia_xml"
    elif suffix in {".catpart", ".catproduct"}:
        parsed = parse_catia_native(raw, source_hash, Path(filename).name)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "catia_native"
    elif suffix in {".bdf", ".dat", ".nas"}:
        parsed = parse_nastran_bdf(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "nastran_bdf"
    elif suffix == ".f06":
        parsed = parse_nastran_f06(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "nastran_f06"
    elif suffix == ".inp":
        parsed = parse_abaqus_inp(raw, source_hash)
        blocks = parsed.pop("blocks")
        cad_cae = parsed
        media_type = "abaqus_inp"
    else:
        raise IngestAbstain("unsupported_media_type")

    requirements = parse_requirements(blocks)
    out: dict[str, Any] = {
        "filename": Path(filename).name,
        "media_type": media_type,
        "source_hash": source_hash,
        "blocks": [block.as_dict() for block in blocks],
        "requirements": requirements,
    }
    if cad_cae is not None:
        out["cad_cae"] = cad_cae
    return out
