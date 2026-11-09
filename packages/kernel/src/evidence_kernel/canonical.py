"""RFC 8785-style canonical JSON for the types this repo stores.

Floats are rejected. Object keys sort by UTF-16 code units. Output is compact UTF-8 text.
Physical quantities must already be strings before they reach this function.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def _key_sort(key: str) -> bytes:
    return key.encode("utf-16-be")


def canonicalize(value: Any) -> str:
    return _emit(value)


def _emit(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        raise TypeError("float is not allowed in canonical JSON")
    if isinstance(value, Mapping):
        keys = sorted((str(key) for key in value), key=_key_sort)
        parts = [f"{_emit(key)}:{_emit(value[key])}" for key in keys]
        return "{" + ",".join(parts) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(_emit(item) for item in value) + "]"
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inputs_hash(value: Any) -> str:
    return sha256_text(canonicalize(value))


def event_hash(prev_hash: str, body: Mapping[str, Any]) -> str:
    """SHA-256 of the ASCII join of prev_hash and the hex SHA-256 of the canonical body."""

    inner = sha256_text(canonicalize(body))
    return hashlib.sha256((prev_hash + inner).encode("ascii")).hexdigest()
