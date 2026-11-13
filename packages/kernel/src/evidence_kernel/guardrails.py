"""Deterministic input/output guardrails against prompt injection, obfuscation, and secret leaks."""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from collections.abc import Sequence
from typing import Any
from urllib.parse import unquote

MAX_BLOCK_CHARS = 32_000

_INVISIBLE_OR_BIDI_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\U000e0000-\U000e007f]"
)
_BASE64_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")
_HEX_CANDIDATE_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}){16,}\b")

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+|any\s+|every\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(
        r"disregard\s+(?:all\s+|the\s+)?(?:system|prior|above)\s+(?:prompt|instructions)",
        re.IGNORECASE,
    ),
    re.compile(
        r"reveal\s+(?:the\s+|your\s+)?(?:system\s+prompt|hidden\s+instructions|secrets?)",
        re.IGNORECASE,
    ),
    re.compile(r"ignora\s+(?:todas?\s+)?(?:las?\s+)?instrucciones\s+anteriores", re.IGNORECASE),
    re.compile(r"olvida\s+(?:todas?\s+)?(?:las?\s+)?reglas\s+anteriores", re.IGNORECASE),
    re.compile(r"revela\s+(?:el\s+|tu\s+)?prompt\s+del?\s+sistema", re.IGNORECASE),
    re.compile(
        r"(?:saltate|sáltate|desactiva|anula)\s+(?:los?\s+|las?\s+)?"
        r"(?:filtros?|reglas?|guardrails?|restricciones?|verificaci[oó]n)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:muestra|revela|imprime|devuelve)\s+(?:las?\s+|los?\s+)?"
        r"(?:claves?|secretos?|contrase[nñ]as?|variables?\s+de\s+entorno)",
        re.IGNORECASE,
    ),
    re.compile(r"<\|(?:im_start|im_end|system|endoftext)\|>", re.IGNORECASE),
    re.compile(
        r"^\s*(?:###\s*)?(?:system|developer|assistant)\s*:\s*"
        r"(?:override|ignore|you\s+must|new\s+rule)",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"\[(?:SYSTEM|ADMIN|INSTRUCTION|ASSISTANT)\s*:[^\]]*\]", re.IGNORECASE),
    re.compile(r"<\s*(?:system|admin|tool_use|function_call)\b", re.IGNORECASE),
    re.compile(r"\b(?:tool_call|function_call)\s*:\s*\{", re.IGNORECASE),
    re.compile(
        r"\b(?:you\s+are\s+now\s+(?:in\s+)?developer\s+mode|enable\s+dan\s+mode|"
        r"act\s+as\s+(?:dan|unrestricted|root|admin)|jailbreak)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:bypass|override|disable|circumvent)\s+(?:all\s+|the\s+|your\s+)?"
        r"(?:safety|guardrails?|security|filters?|verification|constraints?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:forget|drop)\s+(?:all\s+|any\s+|every\s+)?"
        r"(?:rules?|instructions?|constraints?|directives?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:print|dump|leak|exfiltrate|export)\s+(?:the\s+|your\s+|all\s+)?"
        r"(?:env|environment\s+variables|secrets?|api[_ ]?keys?|"
        r"private[_ ]?keys?|passwords?|tokens?|system\s+prompt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"!\[[^\]]*\]\(https?://[^)\s]+\?[^)\s]*(?:secret|token|key|prompt|data)=",
        re.IGNORECASE,
    ),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN\s+(?:RSA|EC|OPENSSH|ED25519|PGP)?\s*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b"),
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    re.compile(
        r"\b(?:ssn|dni|nif|passport|pasaporte|phone|tel[eé]fono)\s*[:=]\s*[A-Za-z0-9+()-]{6,}\b",
        re.IGNORECASE,
    ),
)


def _matches_injection(normalized: str) -> bool:
    return any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS)


def _contains_encoded_injection(text: str) -> bool:
    # 1. URL-decoded inspection (%XX obfuscation)
    if "%" in text:
        try:
            url_decoded = unicodedata.normalize("NFKC", unquote(text))
            if _matches_injection(url_decoded):
                return True
        except Exception:
            pass

    # 2. Base64 payload inspection
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

    # 3. Hex-encoded payload inspection
    for match in _HEX_CANDIDATE_RE.finditer(text):
        try:
            decoded_bytes = binascii.unhexlify(match.group(0))
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
    """Scan model output text for accidental secret, PII, or injection leakage."""
    if not isinstance(text, str):
        return "invalid_text_output"
    if "\x00" in text or _INVISIBLE_OR_BIDI_RE.search(text):
        return "unsafe_control_chars"
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return "secret_leak_detected"
    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            return "pii_leak_detected"
    normalized = unicodedata.normalize("NFKC", text)
    if _matches_injection(normalized) or _contains_encoded_injection(text):
        return "prompt_injection_detected"
    return None


def check_structure_safety(value: Any, *, mode: str = "output") -> str | None:
    """Recursively validate all nested strings inside agent/context structures."""
    checker = check_output_safety if mode == "output" else check_text_safety
    if isinstance(value, str):
        return checker(value)
    if isinstance(value, dict):
        for val in value.values():
            reason = check_structure_safety(val, mode=mode)
            if reason is not None:
                return reason
    elif isinstance(value, (list, tuple)):
        for item in value:
            reason = check_structure_safety(item, mode=mode)
            if reason is not None:
                return reason
    return None


def validate_blocks_safety(blocks: Sequence[dict[str, Any]]) -> str | None:
    """Check every source block in a case before calling any model gateway."""
    for block in blocks:
        reason = check_text_safety(str(block.get("text", "")))
        if reason is not None:
            return reason
    return None
