from evidence_kernel.spans import (
    exact_slice,
    quotation_in_blocks,
    resolve_span_in_block,
    substring_slice,
)


def test_exact_slice_remains_strict() -> None:
    text = "Alpha   item\r\nis listed."
    assert exact_slice(text, 0, 5, "Alpha")
    assert not exact_slice(text, 0, 22, "Alpha item is listed.")
    assert not exact_slice(text, -1, 5, "Alpha")


def test_resolve_span_handles_whitespace_normalization_with_real_offsets() -> None:
    raw = "  Alpha\r\n  item   is   listed.  "
    quote = "Alpha item is listed."

    # Model cites real block slice boundaries around raw text
    real_bounds = resolve_span_in_block(raw, quote, 2, 30)
    assert real_bounds == (2, 30)
    assert quotation_in_blocks([{"text": raw}], quote, "2", "30")

    # Model computes normalized string offsets [0, 21) -> snaps back to real bounds (2, 30)
    mapped = resolve_span_in_block(raw, quote, 0, len(quote))
    assert mapped == (2, 30)
    assert quotation_in_blocks([{"text": raw}], quote, "0", str(len(quote)))

    # Global document block offset shift works when exact slice uses block_offset
    assert quotation_in_blocks(
        [{"text": "Header target section", "offset": 100}],
        "target section",
        "107",
        "121",
    )


def test_wrong_offsets_and_fabricated_quotes_still_fail() -> None:
    raw = "Second block with target quotation."
    assert not quotation_in_blocks([{"text": raw}], raw, "0", "5")
    assert not quotation_in_blocks([{"text": raw}], "Fabricated sentence.", "0", "20")


def test_substring_slice_rejects_trivial_tokens() -> None:
    source = "Alpha item is listed in the certified block."
    assert not substring_slice(source, "")
    assert not substring_slice(source, "a")
    assert not substring_slice(source, "Alpha")
    assert substring_slice(source, "Alpha item is listed")
    assert substring_slice(
        "Alpha\r\n  item   is listed.",
        "Alpha item is listed.",
    )
    assert substring_slice("Short", "Short")
