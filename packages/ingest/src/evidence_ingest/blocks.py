from __future__ import annotations

from dataclasses import dataclass


class IngestAbstain(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Block:
    text: str
    span_start: int
    span_end: int
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "source_hash": self.source_hash,
        }


def blocks_from_text(full: str, source_hash: str) -> list[Block]:
    if not full.strip():
        raise IngestAbstain("no_text_layer")
    blocks: list[Block] = []
    for index, line in enumerate(full.splitlines()):
        if not line.strip():
            continue
        start = _offset(full, index)
        blocks.append(Block(line, start, start + len(line), source_hash))
    if not blocks:
        raise IngestAbstain("no_text_layer")
    return blocks


def _offset(full: str, line_index: int) -> int:
    lines = full.splitlines(keepends=True)
    return sum(len(lines[i]) for i in range(line_index))
