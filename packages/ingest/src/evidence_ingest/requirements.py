from __future__ import annotations

import re

from evidence_ingest.blocks import Block

ID_RE = re.compile(
    r"\b(?:"
    r"VTOL\.\d{4}"
    r"|CS-(?:23|25|27|29|E|P|APU|VLA|LSA)\.\d{1,4}(?:\([a-z0-9]+\))*"
    r"|FAR[\s-]?\d{2,3}\.\d{1,4}(?:\([a-z0-9]+\))*"
    r"|AMC[\s-]?\d{2}\.\d{1,4}"
    r"|DO-\d{3}[A-Z]?"
    r"|SL-\d+\.REQ-\d+"
    r"|REQ-\d+(?:\.\d+)*"
    r")"
)
FIXTURE_NOTE = (
    "The fixture is synthetic text shaped like an identifier. "
    "A title label of VERIFIED here means the title is an exact slice of that fixture, "
    "not a hashed authority file."
)


def parse_requirements(blocks: list[Block]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    seen: set[str] = set()
    for block in blocks:
        for match in ID_RE.finditer(block.text):
            req_id = match.group(0)
            if req_id in seen:
                continue
            seen.add(req_id)
            line_tail = block.text[match.end() :].split("\n", 1)[0].strip(" :\t.")
            title = (
                line_tail
                if line_tail
                and any(char.isalpha() for char in line_tail)
                and line_tail in block.text
                else None
            )
            if title is None:
                quote = req_id
                span_start = match.start()
                span_end = match.end()
                title_label = "NOT_VERIFIED"
            else:
                quote = title
                span_start = block.text.find(title, match.end())
                span_end = span_start + len(title)
                title_label = "VERIFIED"
            found.append(
                {
                    "id": req_id,
                    "title": title,
                    "title_label": title_label,
                    "source_url": "",
                    "source_file_hash": block.source_hash,
                    "source_file_hash_label": "ASSUMPTION",
                    "computable": True,
                    "node_role": "requirement",
                    "provenance_note": FIXTURE_NOTE,
                    "quotation": quote,
                    "span_start": str(span_start),
                    "span_end": str(span_end),
                    "page_no": block.page_no,
                    "bbox": (
                        [f"{float(v):.2f}" for v in block.bbox] if block.bbox is not None else None
                    ),
                }
            )
    return found
