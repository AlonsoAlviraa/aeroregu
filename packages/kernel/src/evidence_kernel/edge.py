"""Deterministic edge compute pre-flight, SLM context compaction, and hardware profiles."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

EDGE_PRESETS: dict[str, dict[str, Any]] = {
    "laptop-cpu-16gb": {
        "preset_id": "laptop-cpu-16gb",
        "backend": "ollama_or_llamacpp",
        "quantization": "Q4_K_M",
        "num_ctx": 4096,
        "max_context_chars": 6000,
        "max_output_tokens": 512,
        "recommended_model": "qwen2.5:3b",
        "structured_mode": "json_schema",
        "offline_capable": True,
        "notes": "Low-RAM CPU/iGPU local workstation edge profile.",
    },
    "jetson-orin-8gb": {
        "preset_id": "jetson-orin-8gb",
        "backend": "vllm_or_ollama",
        "quantization": "AWQ_INT4",
        "num_ctx": 4096,
        "max_context_chars": 5000,
        "max_output_tokens": 512,
        "recommended_model": "llama3.2:3b",
        "structured_mode": "guided_json",
        "offline_capable": True,
        "notes": "Embedded GPU field-bench edge profile with strict 512-token output cap.",
    },
    "apple-silicon-edge": {
        "preset_id": "apple-silicon-edge",
        "backend": "ollama_or_mlx",
        "quantization": "Q5_K_M",
        "num_ctx": 8192,
        "max_context_chars": 12000,
        "max_output_tokens": 768,
        "recommended_model": "qwen2.5:7b",
        "structured_mode": "json_schema",
        "offline_capable": True,
        "notes": "Unified-memory laptop edge profile for 7B constrained generation.",
    },
    "offline-wasm-webgpu": {
        "preset_id": "offline-wasm-webgpu",
        "backend": "browser_webgpu_or_local_slm",
        "quantization": "Q4F16",
        "num_ctx": 2048,
        "max_context_chars": 3000,
        "max_output_tokens": 384,
        "recommended_model": "qwen2.5:1.5b",
        "structured_mode": "json_schema",
        "offline_capable": True,
        "notes": (
            "Ultra-compact client edge window; physics, Z3 SMT, and Merkle proofs stay on CPU."
        ),
    },
}

_SIGNAL_RE = re.compile(
    r"(?:\b[A-Z][A-Z0-9_-]{1,12}[.-]\d+(?:\.\d+)*\b|\bshall\b|\bmaximum\b|\bminimum\b|\d+\.\d+)",
    re.IGNORECASE,
)


def get_edge_preset(preset_id: str | None) -> dict[str, Any]:
    """Return a known edge hardware profile, defaulting to laptop-cpu-16gb."""
    key = (preset_id or "").strip()
    if key in EDGE_PRESETS:
        return dict(EDGE_PRESETS[key])
    return dict(EDGE_PRESETS["laptop-cpu-16gb"])


def compact_blocks_for_edge(
    blocks: list[dict[str, Any]],
    *,
    max_chars: int = 6000,
) -> list[dict[str, Any]]:
    """Select signal-bearing blocks within max_chars while preserving exact original spans."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not blocks:
        return []

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, block in enumerate(blocks):
        text = str(block.get("text", ""))
        hits = len(_SIGNAL_RE.findall(text))
        priority = (2 if hits > 0 else 0) + (1 if idx == 0 else 0)
        scored.append((-priority, idx, dict(block)))

    chosen_indices: list[int] = []
    remaining = max_chars
    # Keep deterministic high-signal subset within budget
    for _, idx, block in sorted(scored):
        text = str(block.get("text", ""))
        if not text.strip():
            continue
        cost = len(text) + 1
        if cost <= remaining:
            chosen_indices.append(idx)
            remaining -= cost

    if not chosen_indices:
        first = dict(blocks[0])
        first_text = str(first.get("text", ""))[:max_chars]
        base_start = int(first.get("span_start", 0))
        first["text"] = first_text
        first["span_start"] = base_start
        first["span_end"] = base_start + len(first_text)
        return [first]

    chosen_indices.sort()
    return [dict(blocks[idx]) for idx in chosen_indices]


def preflight_edge_screening(
    blocks: list[dict[str, Any]],
    *,
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Run deterministic CPU edge pre-screening and token-savings estimation before SLM calls."""
    preset = get_edge_preset(preset_id)
    max_chars = int(preset["max_context_chars"])
    original_chars = sum(len(str(b.get("text", ""))) for b in blocks)
    compacted = compact_blocks_for_edge(blocks, max_chars=max_chars)
    compacted_chars = sum(len(str(b.get("text", ""))) for b in compacted)

    candidate_hits = sum(
        1 for b in compacted if _SIGNAL_RE.search(str(b.get("text", ""))) is not None
    )
    if original_chars > 0:
        ratio = (Decimal(original_chars - compacted_chars) / Decimal(original_chars)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_EVEN
        )
    else:
        ratio = Decimal("0.000")

    return {
        "preset": preset,
        "original_block_count": len(blocks),
        "compacted_block_count": len(compacted),
        "signal_block_count": candidate_hits,
        "original_chars": original_chars,
        "compacted_chars": compacted_chars,
        "estimated_input_tokens": (compacted_chars + 3) // 4,
        "token_savings_ratio": format(ratio, "f"),
        "compacted_blocks": compacted,
    }


def edge_deployment_recipe(
    *,
    preset_id: str | None = None,
    runtime_kind: str = "ollama",
) -> dict[str, Any]:
    """Describe deterministic + SLM edge execution split without guessing local availability."""
    preset = get_edge_preset(preset_id)
    model = preset["recommended_model"]
    if runtime_kind == "llamacpp":
        env_hint = {
            "EDGE_MODEL_URL": "http://127.0.0.1:8080/v1",
            "EDGE_MODEL_PROVIDER": "llamacpp",
            "EDGE_MODEL_NAME": model,
            "OUTLINES_CONSTRAINED": "true",
        }
    else:
        env_hint = {
            "EDGE_MODEL_URL": "http://127.0.0.1:11434",
            "EDGE_MODEL_PROVIDER": "ollama",
            "EDGE_MODEL_NAME": model,
            "OUTLINES_CONSTRAINED": "true",
        }
    return {
        "preset": preset,
        "runtime_kind": runtime_kind,
        "env": env_hint,
        "deterministic_edge_core": [
            "evidence_calc deterministic physics & unit conversions",
            "z3-solver formal SMT bounds proofs",
            "SHA-256 append-only hash chain & O(log N) Merkle proofs",
            "SchemaFSM + stray_physical_numbers guard",
        ],
    }
