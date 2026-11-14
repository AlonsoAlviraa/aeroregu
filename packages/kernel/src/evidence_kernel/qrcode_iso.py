"""Pure-Python ISO/IEC 18004 QR Code encoder (Byte mode, EC Level M, Versions 1-8)."""

from __future__ import annotations

import io

from PIL import Image

# ISO/IEC 18004 Table 9 capacities (Byte mode, EC Level M:
# total_data_bytes, ec_bytes_per_block, blocks)
_VERSION_SPECS: dict[int, tuple[int, int, int, list[int]]] = {
    1: (16, 10, 1, []),
    2: (28, 16, 1, [6, 18]),
    3: (44, 26, 1, [6, 22]),
    4: (64, 18, 2, [6, 26]),
    5: (86, 24, 2, [6, 30]),
    6: (108, 16, 4, [6, 34]),
    7: (124, 18, 4, [6, 22, 38]),
    8: (154, 22, 4, [6, 24, 42]),
}

# GF(256) with primitive polynomial 0x11D (285)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_val = 1
for _i in range(255):
    _GF_EXP[_i] = _val
    _GF_LOG[_val] = _i
    _val <<= 1
    if _val & 0x100:
        _val ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return _GF_EXP[_GF_LOG[x] + _GF_LOG[y]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        root = _GF_EXP[i]
        for j, coef in enumerate(poly):
            next_poly[j] ^= coef
            next_poly[j + 1] ^= _gf_mul(coef, root)
        poly = next_poly
    return poly


def _rs_remainder(data: list[int], ec_count: int) -> list[int]:
    gen = _rs_generator(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data) :]


def _encode_data_codewords(payload: bytes) -> tuple[int, list[int]]:
    length = len(payload)
    chosen_version = None
    for ver in range(1, 9):
        total_data, _, _, _ = _VERSION_SPECS[ver]
        # Header: 4-bit mode (0100) + 8-bit length = 12 bits + payload*8 + 4 term <= total_data*8
        if 12 + length * 8 <= total_data * 8:
            chosen_version = ver
            break
    if chosen_version is None:
        raise ValueError(f"QR payload too large for v1-8 M: {length} bytes")

    total_data, ec_per_block, num_blocks, _ = _VERSION_SPECS[chosen_version]
    bits: list[int] = [0, 1, 0, 0]  # Byte mode indicator 0100
    for shift in range(7, -1, -1):
        bits.append((length >> shift) & 1)
    for byte in payload:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)

    max_bits = total_data * 8
    term_len = min(4, max_bits - len(bits))
    bits.extend([0] * term_len)
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = []
    for idx in range(0, len(bits), 8):
        byte_val = 0
        for b in bits[idx : idx + 8]:
            byte_val = (byte_val << 1) | b
        data_bytes.append(byte_val)

    pad_cycle = (0xEC, 0x11)
    pad_idx = 0
    while len(data_bytes) < total_data:
        data_bytes.append(pad_cycle[pad_idx & 1])
        pad_idx += 1

    # Split into Group 1 and Group 2 blocks for versions >= 7 where needed
    if chosen_version == 5:
        blocks_meta = [(2, 43)]
    elif chosen_version == 7:
        blocks_meta = [(4, 31)]
    elif chosen_version == 8:
        blocks_meta = [(2, 38), (2, 39)]
    else:
        blocks_meta = [(num_blocks, total_data // num_blocks)]

    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    offset = 0
    for count, blk_len in blocks_meta:
        for _ in range(count):
            blk = data_bytes[offset : offset + blk_len]
            offset += blk_len
            data_blocks.append(blk)
            ec_blocks.append(_rs_remainder(blk, ec_per_block))

    interleaved: list[int] = []
    max_data_len = max(len(b) for b in data_blocks)
    for i in range(max_data_len):
        for b in data_blocks:
            if i < len(b):
                interleaved.append(b[i])
    for i in range(ec_per_block):
        for ec in ec_blocks:
            interleaved.append(ec[i])

    return chosen_version, interleaved


def _place_finder(
    grid: list[list[int | None]], reserved: list[list[bool]], r0: int, c0: int
) -> None:
    size = len(grid)
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            r, c = r0 + dr, c0 + dc
            if not (0 <= r < size and 0 <= c < size):
                continue
            reserved[r][c] = True
            if 0 <= dr <= 6 and 0 <= dc <= 6:
                border = dr in (0, 6) or dc in (0, 6)
                inner = 2 <= dr <= 4 and 2 <= dc <= 4
                grid[r][c] = 1 if (border or inner) else 0
            else:
                grid[r][c] = 0


def _place_alignment(
    grid: list[list[int | None]], reserved: list[list[bool]], r0: int, c0: int
) -> None:
    size = len(grid)
    if (r0 < 9 and c0 < 9) or (r0 < 9 and c0 > size - 9) or (r0 > size - 9 and c0 < 9):
        return
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            r, c = r0 + dr, c0 + dc
            reserved[r][c] = True
            grid[r][c] = 1 if (max(abs(dr), abs(dc)) in (0, 2)) else 0


def _format_bits(mask: int) -> int:
    # EC Level M -> indicator bits 00; format = (0b00 << 3) | mask = mask
    data = mask
    rem = data << 10
    for i in range(4, -1, -1):
        if (rem >> (i + 10)) & 1:
            rem ^= 0x537 << i
    return ((data << 10) | rem) ^ 0x5412


def _version_bits(version: int) -> int:
    rem = version << 12
    for i in range(5, -1, -1):
        if (rem >> (i + 12)) & 1:
            rem ^= 0x1F25 << i
    return (version << 12) | rem


def _apply_format_and_version(grid: list[list[int]], version: int, mask: int) -> None:
    size = len(grid)
    fmt = _format_bits(mask)
    for i in range(15):
        bit = (fmt >> i) & 1
        # Top-left around finder: bit 0 (LSB) at (0,8) .. bit 14 (MSB) at (8,0)
        if i < 6:
            grid[i][8] = bit
        elif i == 6:
            grid[7][8] = bit
        elif i == 7:
            grid[8][8] = bit
        elif i == 8:
            grid[8][7] = bit
        else:
            grid[8][14 - i] = bit
        # Top-right horizontal (bits 0..7) & bottom-left vertical (bits 8..14)
        if i < 8:
            grid[8][size - 1 - i] = bit
        else:
            grid[size - 15 + i][8] = bit

    if version >= 7:
        vbits = _version_bits(version)
        for i in range(18):
            bit = (vbits >> i) & 1
            a = size - 11 + (i % 3)
            b = i // 3
            grid[a][b] = bit
            grid[b][a] = bit


def _mask_cond(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return ((r // 2) + (c // 3)) % 2 == 0
    if mask == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _penalty_score(grid: list[list[int]]) -> int:
    n = len(grid)
    score = 0
    # Rule 1: adjacent runs >= 5
    for r in range(n):
        run = 1
        for c in range(1, n):
            if grid[r][c] == grid[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for c in range(n):
        run = 1
        for r in range(1, n):
            if grid[r][c] == grid[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 blocks
    for r in range(n - 1):
        for c in range(n - 1):
            v = grid[r][c]
            if grid[r][c + 1] == v and grid[r + 1][c] == v and grid[r + 1][c + 1] == v:
                score += 3
    # Rule 4: dark ratio deviation from 50%
    dark = sum(sum(row) for row in grid)
    pct = (dark * 100) // (n * n)
    score += (abs(pct - 50) // 5) * 10
    return score


def build_qr_matrix(text: str) -> list[list[int]]:
    """Build a deterministic ISO/IEC 18004 QR boolean matrix (1=dark, 0=light)."""
    payload = text.encode("utf-8")
    version, codewords = _encode_data_codewords(payload)
    size = 17 + 4 * version
    base: list[list[int | None]] = [[None] * size for _ in range(size)]
    reserved: list[list[bool]] = [[False] * size for _ in range(size)]

    _place_finder(base, reserved, 0, 0)
    _place_finder(base, reserved, 0, size - 7)
    _place_finder(base, reserved, size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        reserved[6][i] = True
        base[6][i] = bit
        reserved[i][6] = True
        base[i][6] = bit

    # Dark module
    reserved[4 * version + 9][8] = True
    base[4 * version + 9][8] = 1

    # Alignment patterns
    centers = _VERSION_SPECS[version][3]
    for r in centers:
        for c in centers:
            _place_alignment(base, reserved, r, c)

    # Reserve format info areas
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True
    if version >= 7:
        for i in range(6):
            for j in range(3):
                reserved[size - 11 + j][i] = True
                reserved[i][size - 11 + j] = True

    # Place bitstream zigzag
    all_bits: list[int] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            all_bits.append((cw >> shift) & 1)
    # Remainder bits (7 remainder bits for versions 2-6, 0 for v1/v7-8)
    rem_bits = 7 if 2 <= version <= 6 else 0
    all_bits.extend([0] * rem_bits)

    bit_idx = 0
    up = True
    c = size - 1
    while c > 0:
        if c == 6:
            c -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for r in rows:
            for dc in (0, -1):
                col = c + dc
                if not reserved[r][col]:
                    bit = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    base[r][col] = bit
                    bit_idx += 1
        up = not up
        c -= 2

    best_grid: list[list[int]] | None = None
    best_penalty = 10**9
    for mask in range(8):
        cand = [
            [
                (base[r][c] or 0) ^ (1 if (not reserved[r][c] and _mask_cond(mask, r, c)) else 0)
                for c in range(size)
            ]
            for r in range(size)
        ]
        _apply_format_and_version(cand, version, mask)
        pen = _penalty_score(cand)
        if pen < best_penalty:
            best_penalty = pen
            best_grid = cand

    assert best_grid is not None
    return best_grid


def render_qr_png(text: str, *, scale: int = 5, border: int = 4) -> bytes:
    """Render an ISO/IEC 18004 QR code to PNG bytes suitable for PDF embedding."""
    matrix = build_qr_matrix(text)
    n = len(matrix)
    total = (n + 2 * border) * scale
    img = Image.new("L", (total, total), 255)
    px = img.load()
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                y0 = (r + border) * scale
                x0 = (c + border) * scale
                for dy in range(scale):
                    for dx in range(scale):
                        px[x0 + dx, y0 + dy] = 0
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
