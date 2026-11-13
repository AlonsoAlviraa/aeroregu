"""Deterministic input/output guardrails against prompt injection and control smuggling."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

MAX_BLOCK_CHARS = 32_000

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+|any\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+|the\s+)?(?:system|prior)\s+prompt", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+|your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"<\|(?:im_start|im_end|system|endoftext)\|>", re.IGNORECASE),
    re.compile(r"^\s*system\s*:\s*override", re.IGNORECASE | re.MULTILINE),
)


def check_text_safety(text: str) -> str | None:
    """Return an abstain reason if text contains injection markers or unsafe control chars."""
    if not isinstance(text, str):
        return "invalid_text_input"
    if len(text) > MAX_BLOCK_CHARS:
        return "input_too_large"
    if "\x00" in text:
        return "unsafe_control_chars"
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return "prompt_injection_detected"
    return None


def validate_blocks_safety(blocks: Sequence[dict[str, Any]]) -> str | None:
    """Check every source block in a case before calling any model gateway."""
    for block in blocks:
        reason = check_text_safety(str(block.get("text", "")))
        if reason is not None:
            return reason
    return None
