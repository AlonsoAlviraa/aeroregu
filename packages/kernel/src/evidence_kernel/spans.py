from __future__ import annotations


def exact_slice(text: str, start: int, end: int, quotation: str) -> bool:
    if quotation == "":
        return False
    if start < 0 or end > len(text) or start > end:
        return False
    return text[start:end] == quotation


def quotation_in_blocks(blocks: list[dict], quotation: str, span_start: str, span_end: str) -> bool:
    try:
        start = int(span_start)
        end = int(span_end)
    except (TypeError, ValueError):
        return False
    for block in blocks:
        text = str(block.get("text", ""))
        if exact_slice(text, start, end, quotation):
            return True
    return False


def substring_slice(text: str, quotation: str) -> bool:
    if quotation == "":
        return False
    return quotation in text
