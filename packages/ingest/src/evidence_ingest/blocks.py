from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class IngestAbstain(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Block:
    text: str
    span_start: int
    span_end: int
    source_hash: str
    page_no: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    block_kind: str = "text"
    table_rows: list[list[str]] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": self.text,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "source_hash": self.source_hash,
        }
        if self.page_no is not None:
            payload["page_no"] = self.page_no
        if self.bbox is not None:
            payload["bbox"] = [round(coord, 2) for coord in self.bbox]
        if self.block_kind != "text":
            payload["block_kind"] = self.block_kind
        if self.table_rows is not None:
            payload["table_rows"] = self.table_rows
        return payload


def blocks_from_text(
    full: str,
    source_hash: str,
    *,
    page_no: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    block_kind: str = "text",
) -> list[Block]:
    """Split text into blocks in O(N) time while preserving exact character spans."""
    if not full.strip():
        raise IngestAbstain("no_text_layer")
    blocks: list[Block] = []
    offset = 0
    for raw_line in full.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line.strip():
            blocks.append(
                Block(
                    line,
                    offset,
                    offset + len(line),
                    source_hash,
                    page_no,
                    bbox,
                    block_kind,
                )
            )
        offset += len(raw_line)
    if not blocks:
        raise IngestAbstain("no_text_layer")
    return blocks
