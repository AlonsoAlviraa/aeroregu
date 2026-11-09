from __future__ import annotations

import re

from evidence_ingest.blocks import Block

ID_RE = re.compile(r"VTOL\.\d{4}")
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
            tail = block.text[match.end() :].strip(" :\t.")
            title = (
                tail
                if tail and any(char.isalpha() for char in tail) and tail in block.text
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
                }
            )
    return found
