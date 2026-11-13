from __future__ import annotations


def exact_slice(text: str, start: int, end: int, quotation: str) -> bool:
    if quotation == "":
        return False
    if start < 0 or end > len(text) or start > end:
        return False
    return text[start:end] == quotation


def _normalize_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    """Collapse whitespace runs to single spaces while tracking original [start, end) offsets."""
    norm_chars: list[str] = []
    char_starts: list[int] = []
    char_ends: list[int] = []
    n = len(text)
    idx = 0
    while idx < n and text[idx].isspace():
        idx += 1
    in_space = False
    while idx < n:
        ch = text[idx]
        if ch.isspace():
            ws_start = idx
            while idx < n and text[idx].isspace():
                idx += 1
            if idx < n and not in_space:
                norm_chars.append(" ")
                char_starts.append(ws_start)
                char_ends.append(idx)
                in_space = True
            continue
        norm_chars.append(ch)
        char_starts.append(idx)
        char_ends.append(idx + 1)
        in_space = False
        idx += 1
    return "".join(norm_chars), char_starts, char_ends


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def resolve_span_in_block(
    text: str,
    quotation: str,
    span_start: str | int,
    span_end: str | int,
    *,
    block_offset: int = 0,
) -> tuple[int, int] | None:
    """Resolve [span_start, span_end) against exact or whitespace-normalized real text offsets."""
    if not quotation or not quotation.strip():
        return None
    try:
        start = int(span_start)
        end = int(span_end)
    except (TypeError, ValueError):
        return None

    candidates = [(start, end)]
    if block_offset > 0 and start >= block_offset:
        candidates.append((start - block_offset, end - block_offset))

    for cand_start, cand_end in candidates:
        if exact_slice(text, cand_start, cand_end, quotation):
            return (cand_start, cand_end)

    norm_quote = _normalize_ws(quotation)
    if not norm_quote:
        return None

    norm_text, char_starts, char_ends = _normalize_with_offsets(text)
    for cand_start, cand_end in candidates:
        if 0 <= cand_start <= cand_end <= len(text):
            if _normalize_ws(text[cand_start:cand_end]) == norm_quote:
                # Snap bounds past outer whitespace to exact real text slice matching quotation
                inner_start = cand_start
                while inner_start < cand_end and text[inner_start].isspace():
                    inner_start += 1
                inner_end = cand_end
                while inner_end > inner_start and text[inner_end - 1].isspace():
                    inner_end -= 1
                return (inner_start, inner_end)
        if 0 <= cand_start < cand_end <= len(norm_text):
            if norm_text[cand_start:cand_end] == norm_quote:
                return (char_starts[cand_start], char_ends[cand_end - 1])
    return None


def quotation_in_blocks(blocks: list[dict], quotation: str, span_start: str, span_end: str) -> bool:
    for block in blocks:
        text = str(block.get("text", ""))
        raw_offset = block.get("offset", 0)
        try:
            block_offset = int(raw_offset)
        except (TypeError, ValueError):
            block_offset = 0
        if resolve_span_in_block(text, quotation, span_start, span_end, block_offset=block_offset):
            return True
    return False


def substring_slice(text: str, quotation: str, *, min_chars: int = 8) -> bool:
    if quotation == "":
        return False
    norm_quote = _normalize_ws(quotation)
    norm_text = _normalize_ws(text)
    if not norm_quote:
        return False
    if len(norm_quote) < min_chars and norm_quote != norm_text:
        return False
    return quotation in text or norm_quote in norm_text
