"""RFC 8785 (JCS) canonical JSON for the types this repo stores.

Floats are rejected. Strings are Unicode NFC-normalized before RFC 8785 serialization.
Physical quantities must already be strings before they reach this function.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

import rfc8785


def _prepare_jcs(value: Any) -> Any:
    """Validate allowed types (no floats) and apply Unicode NFC normalization."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed in canonical JSON")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {
            unicodedata.normalize("NFC", str(key)): _prepare_jcs(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_prepare_jcs(item) for item in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonicalize(value: Any) -> str:
    """Emit compact UTF-8 RFC 8785 canonical JSON text."""
    prepared = _prepare_jcs(value)
    return rfc8785.dumps(prepared).decode("utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inputs_hash(value: Any) -> str:
    return sha256_text(canonicalize(value))


def event_hash(prev_hash: str, body: Mapping[str, Any]) -> str:
    """SHA-256 of the ASCII join of prev_hash and the hex SHA-256 of the canonical body."""

    inner = sha256_text(canonicalize(body))
    return hashlib.sha256((prev_hash + inner).encode("ascii")).hexdigest()
