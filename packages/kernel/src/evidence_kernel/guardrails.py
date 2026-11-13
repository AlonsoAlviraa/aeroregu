"""Deterministic input/output guardrails against prompt injection, obfuscation, and secret leaks."""

from __future__ import annotations

import base64
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

MAX_BLOCK_CHARS = 32_000

_INVISIBLE_OR_BIDI_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_BASE64_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+|any\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+|the\s+)?(?:system|prior)\s+prompt", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+|your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"ignora\s+(?:todas?\s+las?\s+)?instrucciones\s+anteriores", re.IGNORECASE),
    re.compile(r"olvida\s+(?:todas?\s+las?\s+)?reglas\s+anteriores", re.IGNORECASE),
    re.compile(r"revela\s+(?:el\s+|tu\s+)?prompt\s+del?\s+sistema", re.IGNORECASE),
    re.compile(r"<\|(?:im_start|im_end|system|endoftext)\|>", re.IGNORECASE),
    re.compile(r"^\s*system\s*:\s*override", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\b(?:tool_call|function_call)\s*:\s*\{", re.IGNORECASE),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN\s+(?:RSA|EC|OPENSSH|ED25519|PGP)?\s*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)


def _matches_injection(normalized: str) -> bool:
    return any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS)


def _contains_encoded_injection(text: str) -> bool:
    for match in _BASE64_CANDIDATE_RE.finditer(text):
        token = match.group(0)
        if len(token) % 4 != 0:
            continue
        try:
            decoded_bytes = base64.b64decode(token, validate=True)
            decoded_text = unicodedata.normalize("NFKC", decoded_bytes.decode("utf-8"))
        except Exception:
            continue
        if _matches_injection(decoded_text):
            return True
    return False


def check_text_safety(text: str) -> str | None:
    """Return an abstain reason on injection markers, bidi smuggling, or control chars."""
    if not isinstance(text, str):
        return "invalid_text_input"
    if len(text) > MAX_BLOCK_CHARS:
        return "input_too_large"
    if "\x00" in text:
        return "unsafe_control_chars"
    if _INVISIBLE_OR_BIDI_RE.search(text):
        return "unsafe_control_chars"

    normalized = unicodedata.normalize("NFKC", text)
    if _matches_injection(normalized) or _contains_encoded_injection(text):
        return "prompt_injection_detected"
    return None


def check_output_safety(text: str) -> str | None:
    """Scan model output text for accidental private key or secret/token leakage."""
    if not isinstance(text, str):
        return "invalid_text_output"
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return "secret_leak_detected"
    return None


def validate_blocks_safety(blocks: Sequence[dict[str, Any]]) -> str | None:
    """Check every source block in a case before calling any model gateway."""
    for block in blocks:
        reason = check_text_safety(str(block.get("text", "")))
        if reason is not None:
            return reason
    return None
